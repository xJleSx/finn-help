import asyncio
import contextlib
import logging
from datetime import date, timedelta, timezone
from typing import Any, Optional

import pandas as pd
from sqlalchemy import and_, delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from src.collectors.cbr import CBRCollector
from src.collectors.moex import MOEXCollector, fill_price_gaps
from src.collectors.news import NewsCollector
from src.config import (
    DEFAULT_HISTORY_DAYS,
    DIVIDEND_CHECK_DAYS,
    NEWS_MAX_PER_FEED,
)
from src.db.connection import get_async_session, get_session
from src.db.models import (
    Dividend,
    GeoRiskScore,
    Indicator,
    Instrument,
    News,
    Price,
)
from src.db.queries import async_bulk_upsert
from src.geo.risk_scorer import GeoRiskScorer
from src.geo.sentiment_divergence import SentimentDivergenceDetector
from src.utils import _safe_float, _safe_int

logger = logging.getLogger(__name__)

STALENESS_THRESHOLD_DAYS = 2

divergence = SentimentDivergenceDetector()
geo_risk = GeoRiskScorer()


def _first(v1: Any, v2: Any) -> Any:
    return v1 if v1 is not None else v2


ETF_BOARDS = ["etf", "etf_tqtd", "shares"]

async def _fetch_prices_for_instrument(db: AsyncSession, inst: Instrument, from_date: str, moex: MOEXCollector) -> int:
    itype = str(inst.instrument_type)
    boards = ETF_BOARDS if itype == "etf" else [{"stock": "stock", "bond": "bond"}.get(itype, "shares")]
    history: list[dict] = []
    for board in boards:
        history = await moex.get_history(str(inst.ticker), from_date=from_date, board=board)
        if history:
            break
    if not history:
        logger.debug("No price history for %s (boards=%s, from=%s)", inst.ticker, boards, from_date)
        return 0

    nominal: float | None = None
    if board == "bond":
        nominal = float(inst.nominal) if inst.nominal is not None else None
        if nominal is None:
            info = await moex.get_security_info(str(inst.ticker))
            fv = info.get("face_value")
            if fv:
                nominal = float(fv)
                inst.nominal = nominal
                await db.flush()

    def _bond_normalize(v: float | None) -> float | None:
        if v is not None and nominal is not None:
            return v * nominal / 100
        return v

    rows_to_upsert: list[dict[str, Any]] = []
    for row in history:
        d = row.get("TRADEDATE") or row.get("tradedate")
        if isinstance(d, str):
            d = date.fromisoformat(d)
        if not d:
            continue

        _o = _first(row.get("OPEN"), row.get("open"))
        _h = _first(row.get("HIGH"), row.get("high"))
        _l = _first(row.get("LOW"), row.get("low"))
        _c = _first(row.get("CLOSE"), row.get("close"))
        if nominal:
            _o = _bond_normalize(_o)
            _h = _bond_normalize(_h)
            _l = _bond_normalize(_l)
            _c = _bond_normalize(_c)

        rows_to_upsert.append({
            "instrument_id": int(inst.id),
            "date": d,
            "open": _o,
            "high": _h,
            "low": _l,
            "close": _c,
            "volume": _first(row.get("VOLUME"), row.get("volume")),
        })

    if not rows_to_upsert:
        return 0

    df = pd.DataFrame(rows_to_upsert)
    df = fill_price_gaps(df)
    rows_to_upsert = df.to_dict("records")

    return await async_bulk_upsert(
        db, Price, rows_to_upsert,
        conflict_columns=["instrument_id", "date"],
        update_columns=["open", "high", "low", "close", "volume"],
    )


async def fetch_price_history_for_instrument(ticker: str, instrument_type: str) -> int:
    """Авто-загрузка цен для нового инструмента при синке портфеля."""
    from_date = (date.today() - timedelta(days=DEFAULT_HISTORY_DAYS)).isoformat()
    async with get_async_session() as db:
        inst = (await db.execute(select(Instrument).filter_by(ticker=ticker))).scalars().first()
        if not inst:
            logger.warning("Instrument %s not found in DB, cannot fetch price history", ticker)
            return 0
        async with MOEXCollector() as moex:
            return await _fetch_prices_for_instrument(db, inst, from_date, moex)


async def collect_prices(db: AsyncSession) -> set[int]:
    updated_ids: set[int] = set()
    async with MOEXCollector() as moex:
        result = await db.execute(select(Instrument))
        instruments = result.scalars().all()
        if not instruments:
            return updated_ids

        from sqlalchemy import func as sqlfunc

        last_dates_result = await db.execute(
            select(Price.instrument_id, sqlfunc.max(Price.date).label("max_date"))
            .group_by(Price.instrument_id)
        )
        last_dates: dict[int, date | None] = {}
        for row in last_dates_result:
            last_dates[row.instrument_id] = row.max_date

        for inst in instruments:
            last_dt = last_dates.get(int(inst.id))
            days_back = DEFAULT_HISTORY_DAYS
            from_date = last_dt.isoformat() if last_dt else (date.today() - timedelta(days=days_back)).isoformat()
            new_count = await _fetch_prices_for_instrument(db, inst, from_date, moex)
            await db.commit()
            if new_count > 0:
                updated_ids.add(int(inst.id))
    await _check_price_freshness(db)
    return updated_ids


async def _check_price_freshness(db: AsyncSession, max_age_days: int = STALENESS_THRESHOLD_DAYS) -> None:
    from sqlalchemy import func as sqlfunc

    subq = (
        select(
            Price.instrument_id,
            sqlfunc.max(Price.date).label("last_date"),
        )
        .group_by(Price.instrument_id)
        .subquery()
    )
    stmt = (
        select(Instrument.ticker, Instrument.instrument_type, subq.c.last_date)
        .join(subq, Instrument.id == subq.c.instrument_id)
        .where(subq.c.last_date < date.today() - timedelta(days=max_age_days))
    )
    result = await db.execute(stmt)
    for ticker, itype, last_date in result:
        logger.warning("Stale data: %s (%s) — last price %s, >%d days ago", ticker, itype, last_date, max_age_days)


async def collect_dividends(db: AsyncSession) -> None:
    async with MOEXCollector() as moex:
        result = await db.execute(
            select(Instrument).filter(Instrument.instrument_type.in_(["stock", "etf"]))
        )
        instruments = result.scalars().all()
        if not instruments:
            return

        from sqlalchemy import func as sqlfunc

        last_dates_result = await db.execute(
            select(Dividend.instrument_id, sqlfunc.max(Dividend.date).label("max_date"))
            .group_by(Dividend.instrument_id)
        )
        last_dates: dict[int, date | None] = {}
        for row in last_dates_result:
            last_dates[row.instrument_id] = row.max_date

        for inst in instruments:
            last_dt = last_dates.get(int(inst.id))
            if last_dt and (date.today() - last_dt).days < DIVIDEND_CHECK_DAYS:
                continue
            try:
                dividends = await moex.get_dividends(str(inst.ticker))
                rows_to_upsert: list[dict[str, Any]] = []
                for row in dividends:
                    d = row.get("registryclosedate") or row.get("recordDate") or row.get("recorddate")
                    amt = row.get("value") or row.get("dividendGross")
                    if not d or not amt:
                        continue
                    if isinstance(d, str):
                        d = date.fromisoformat(d)
                    rows_to_upsert.append({
                        "instrument_id": int(inst.id),
                        "date": d,
                        "amount": float(amt),
                        "currency": "RUB",
                    })

                if rows_to_upsert:
                    await async_bulk_upsert(
                        db, Dividend, rows_to_upsert,
                        conflict_columns=["instrument_id", "date", "amount"],
                        update_columns=["currency"],
                    )
                await db.commit()
            except Exception as e:
                logger.warning(f"Dividends failed for {inst.ticker}: {e}")


def compute_indicators(db: Session, instrument_ids: set[int] | None = None) -> None:
    from src.analysis.technical import TechnicalAnalyzer
    from src.db.queries import bulk_upsert

    analyzer = TechnicalAnalyzer()
    q = db.query(Instrument)
    if instrument_ids is not None:
        q = q.filter(Instrument.id.in_(instrument_ids))
    instruments = q.all()
    if not instruments:
        return

    ids = [inst.id for inst in instruments]
    all_prices = db.query(Price).filter(Price.instrument_id.in_(ids)).order_by(Price.instrument_id, Price.date).all()
    prices_by_inst: dict[int, list[Price]] = {}
    for p in all_prices:
        prices_by_inst.setdefault(int(p.instrument_id), []).append(p)

    for inst in instruments:
        prices = prices_by_inst.get(int(inst.id), [])
        if len(prices) < 50:
            continue
        df = pd.DataFrame(
            [
                {
                    "date": p.date,
                    "open": p.open,
                    "high": p.high,
                    "low": p.low,
                    "close": p.close,
                    "volume": p.volume,
                }
                for p in prices
            ]
        )
        df = analyzer.compute_all(df)
        rows_to_upsert: list[dict[str, Any]] = []
        for _, row in df.iterrows():
            rows_to_upsert.append({
                "instrument_id": int(inst.id),
                "date": row["date"],
                "rsi": row.get("rsi"),
                "macd_line": row.get("macd_line"),
                "macd_signal": row.get("macd_signal"),
                "macd_hist": row.get("macd_hist"),
                "sma_20": row.get("sma_20"),
                "sma_50": row.get("sma_50"),
                "sma_200": row.get("sma_200"),
                "bb_upper": row.get("bb_upper"),
                "bb_lower": row.get("bb_lower"),
                "bb_mid": row.get("bb_mid"),
                "volume_sma_20": row.get("volume_sma_20"),
                "atr": row.get("atr"),
            })

        if rows_to_upsert:
            bulk_upsert(
                db, Indicator, rows_to_upsert,
                conflict_columns=["instrument_id", "date"],
                update_columns=["rsi", "macd_line", "macd_signal", "macd_hist", "sma_20", "sma_50", "sma_200", "bb_upper", "bb_lower", "bb_mid", "volume_sma_20", "atr"],
            )
        db.commit()


async def collect_news(db: AsyncSession) -> list[dict[str, Any]]:
    from src.db.models import NewsInstrument

    collector = NewsCollector()
    news_list = await collector.fetch_all(max_per_feed=NEWS_MAX_PER_FEED)

    result = await db.execute(select(Instrument))
    instruments = result.scalars().all()
    ticker_map: dict[str, int] = {}
    for inst in instruments:
        ticker_map[str(inst.ticker).upper()] = int(inst.id)

    saved_news: list[News] = []
    news_rows: list[dict[str, Any]] = []
    for item in news_list:
        detail = item.get("sentiment_detail", {})
        news_rows.append({
            "url": item["url"],
            "title": item["title"],
            "summary": item.get("summary", ""),
            "source_type": item["source_type"],
            "source_name": item["source_name"],
            "published_at": item["published_at"],
            "sentiment_score": item.get("sentiment_score"),
            "sentiment_weighted": item.get("sentiment_weighted"),
            "sentiment_bert_score": detail.get("bert_score"),
            "source_weight": detail.get("source_weight"),
        })

    if news_rows:
        await async_bulk_upsert(
            db, News, news_rows,
            conflict_columns=["url"],
            update_columns=["title", "summary", "sentiment_score", "sentiment_weighted", "sentiment_bert_score", "source_weight"],
        )
        await db.flush()

        for item in news_list:
            n_result = await db.execute(select(News).filter_by(url=item["url"]))
            n = n_result.scalars().first()
            if n:
                saved_news.append(n)

    candidate_pairs: list[tuple[int, int]] = []
    for n in saved_news:
        search_text = f"{n.title or ''} {n.summary or ''}".upper()
        for ticker, inst_id in ticker_map.items():
            if len(ticker) >= 2 and ticker in search_text:
                candidate_pairs.append((n.id, inst_id))

    if candidate_pairs:
        news_ids = list({p[0] for p in candidate_pairs})
        links_result = await db.execute(
            select(NewsInstrument).filter(NewsInstrument.news_id.in_(news_ids))
        )
        existing_links = {
            (r.news_id, r.instrument_id)
            for r in links_result.scalars().all()
        }
    else:
        existing_links = set()

    for news_id, inst_id in candidate_pairs:
        if (news_id, inst_id) not in existing_links:
            db.add(NewsInstrument(news_id=news_id, instrument_id=inst_id))

    await db.commit()
    return news_list


async def compute_geo_risk(db: AsyncSession, news_list: list[dict[str, Any]]) -> None:
    sent = divergence.detect(news_list=news_list)
    cbr = CBRCollector()
    try:
        rates = await cbr.get_rates()
    except Exception:
        logger.exception("Unhandled exception")
        logger.warning("Failed to fetch CBR rates", exc_info=True)
        rates = []
    usd_rate = next((r for r in rates if r["code"] == "USD"), None)
    currency_vol = 0.0
    if usd_rate:
        prev_result = await db.execute(
            select(GeoRiskScore).order_by(GeoRiskScore.date.desc()).limit(1)
        )
        prev = prev_result.scalars().first()
        if prev and prev.components_json:
            prev_stress = prev.components_json.get("currency_stress", 0)
            currency_vol = prev_stress * 0.7 + min(abs(usd_rate.get("change_pct", 0)) * 5, 2.0) * 0.3
        else:
            currency_vol = min(abs(usd_rate.get("change_pct", 0)) * 5, 2.0)

    risk = geo_risk.score(news_list, currency_volatility=currency_vol)

    today = date.today()
    await async_bulk_upsert(
        db, GeoRiskScore,
        [{
            "date": today,
            "country": "global",
            "score": risk["score"],
            "components_json": dict(risk.get("components") or {}),
            "sources_json": {"sentiment_divergence": sent, "news_count": len(news_list)},
        }],
        conflict_columns=["date", "country"],
        update_columns=["score", "components_json", "sources_json"],
    )
    await db.commit()


async def collect_fundamental(db: AsyncSession) -> None:
    from src.collectors.fundamental import FundamentalDataCollector
    from src.db.models import FundamentalMetric, Price

    result = await db.execute(
        select(Instrument).filter(Instrument.instrument_type.in_(["stock", "etf"]))
    )
    instruments = result.scalars().all()
    if not instruments:
        return

    today = date.today()
    inst_ids = [inst.id for inst in instruments]

    from sqlalchemy import func as sqlfunc

    latest_price_subq = (
        select(
            Price.instrument_id,
            sqlfunc.max(Price.date).label('max_date'),
        )
        .filter(Price.instrument_id.in_(inst_ids))
        .group_by(Price.instrument_id)
        .subquery()
    )

    prices_result = await db.execute(
        select(Price)
        .join(
            latest_price_subq,
            and_(
                Price.instrument_id == latest_price_subq.c.instrument_id,
                Price.date == latest_price_subq.c.max_date,
            ),
        )
    )
    last_prices: dict[int, float | None] = {}
    for r in prices_result.scalars().all():
        last_prices[int(r.instrument_id)] = float(r.close) if r.close is not None else None

    async with FundamentalDataCollector() as collector:
        for inst in instruments:
            last_price = last_prices.get(int(inst.id))

            try:
                data = await collector.fetch(str(inst.ticker), last_price=last_price)
            except Exception as e:
                logger.warning("Fundamental fetch failed for %s: %s", inst.ticker, e)
                continue

            await async_bulk_upsert(
                db, FundamentalMetric,
                [{
                    "instrument_id": int(inst.id),
                    "date": today,
                    "market_cap": data["market_cap"],
                    "shares_outstanding": data["shares_outstanding"],
                    "extra": data.get("extra"),
                }],
                conflict_columns=["instrument_id", "date"],
                update_columns=["market_cap", "shares_outstanding", "extra"],
            )
        await db.commit()


async def generate_signals(db: AsyncSession, updated_ids: set[int] | None = None) -> list[dict[str, Any]]:
    from src.analysis.service import analysis_service

    return await analysis_service.analyze_all(db, updated_ids=updated_ids)


async def collect_macro(db: AsyncSession) -> None:
    from src.collectors.macro import MacroCollector
    from src.db.models import MacroIndicator

    collector = MacroCollector()
    items = await collector.fetch_all()
    today = date.today()
    if not items:
        return

    rows: list[dict[str, Any]] = []
    for item in items:
        rows.append({
            "date": item.get("date", today),
            "indicator_type": item["indicator_type"],
            "value": item["value"],
            "source": item.get("source"),
        })

    if rows:
        await async_bulk_upsert(
            db, MacroIndicator, rows,
            conflict_columns=["date", "indicator_type"],
            update_columns=["value", "source"],
        )
    await db.commit()


def _train_sentiment_evolution() -> None:
    from src.analysis.ml.sentiment_evolution import SentimentEvolutionModel

    try:
        model = SentimentEvolutionModel(ticker="__all__")
        model.train()
        logger.info("Sentiment evolution model trained")
    except Exception as e:
        logger.warning("Sentiment evolution training failed: %s", e)


async def collect_social_sentiment() -> None:
    from src.social.registry import registry
    from src.social.sentiment.analyzer import analyzer

    try:
        registry.build_from_config()
        sources = registry.get_active()
        if not sources:
            logger.info("No active social sources, skipping social collection")
            return

        from src.db.models import SocialPost

        for src in sources:
            try:
                posts = await src.fetch_posts()
                async with get_async_session() as db:
                    rows_to_upsert: list[dict[str, Any]] = []
                    for post in posts:
                        rows_to_upsert.append({
                            "source": post.source,
                            "external_id": post.external_id,
                            "author_nick": post.author_nick,
                            "author_id": post.author_id,
                            "text": post.text,
                            "published_at": post.published_at,
                            "url": post.url,
                            "tickers_mentioned": post.tickers,
                            "raw_json": post.raw,
                        })

                    if rows_to_upsert:
                        processed = await async_bulk_upsert(
                            db, SocialPost, rows_to_upsert,
                            conflict_columns=["source", "external_id"],
                            update_columns=["text", "author_nick", "published_at", "tickers_mentioned"],
                        )
                        logger.info("Social %s: %d posts upserted", src.source_name, processed)
            except Exception as e:
                logger.error("Social collection failed for %s: %s", src.source_name, e)

        count = await analyzer.process_new_posts()
        logger.info("Social sentiment: %d signals created", count)

        # Compute social features for all tickers
        from src.core.executor import get_executor
        from src.social.features import compute_social_features

        async with get_async_session() as db:
            result = await db.execute(select(Instrument.ticker))
            tickers = [r.ticker for r in result]

            loop = asyncio.get_running_loop()
            ex = get_executor()
            for ticker in tickers:
                try:
                    await loop.run_in_executor(ex, compute_social_features, ticker)
                except Exception as e:
                    logger.debug("Social features computation failed for %s: %s", ticker, e)

        # Train sentiment evolution model
        try:
            loop = asyncio.get_running_loop()
            ex = get_executor()
            await loop.run_in_executor(ex, _train_sentiment_evolution)
        except Exception as e:
            logger.warning("Sentiment evolution training failed: %s", e)
    except Exception as e:
        logger.error("Social sentiment cycle failed: %s", e)


async def collect_financial_reports(db: AsyncSession) -> None:
    """Fetch/update IFRS financial reports from SmartLab."""
    from src.collectors.financials import FinancialReportCollector
    from src.db.models import FinancialReport

    result = await db.execute(
        select(Instrument).filter(Instrument.instrument_type.in_(["stock", "etf"]))
    )
    instruments = result.scalars().all()
    if not instruments:
        return

    collector = FinancialReportCollector()
    try:
        rows_to_upsert: list[dict[str, Any]] = []
        for inst in instruments:
            data = await collector.fetch(inst.ticker)
            if not data:
                continue
            report_date_str = data.pop("reporting_date", None)
            period_type = data.pop("period_type", "FY")
            if not report_date_str:
                continue
            rd = date.fromisoformat(report_date_str) if isinstance(report_date_str, str) else report_date_str

            row: dict[str, Any] = {
                "instrument_id": int(inst.id),
                "report_date": rd,
                "period_type": period_type,
                "source": "smartlab",
            }
            for k, v in data.items():
                if hasattr(FinancialReport, k):
                    row[k] = v
            rows_to_upsert.append(row)

        if rows_to_upsert:
            await async_bulk_upsert(
                db, FinancialReport, rows_to_upsert,
                conflict_columns=["instrument_id", "report_date", "period_type"],
                update_columns=[k for k in rows_to_upsert[0] if k not in ("instrument_id", "report_date", "period_type")],
            )
        await db.commit()
        logger.info("Financial reports collected for %d instruments", len(instruments))
    finally:
        await collector.close()


async def collect_bond_offerings(db: AsyncSession) -> None:
    """Fetch/update bond offerings from MOEX ISS. Updates existing records."""
    from src.collectors.bonds import BondOfferingCollector
    from src.db.models import BondCouponSchedule, BondOffering, BondOfferingHistory

    result = await db.execute(
        select(Instrument).filter(Instrument.instrument_type == "bond")
    )
    instruments = result.scalars().all()
    if not instruments:
        return

    collector = BondOfferingCollector()
    updated_count = 0
    new_count = 0
    coupon_count = 0

    try:
        collected_bonds: list[tuple[Instrument, dict]] = []
        for inst in instruments:
            data = await collector.fetch_by_ticker(inst.ticker)
            if not data or not data.get("isin"):
                continue
            collected_bonds.append((inst, data))

        if collected_bonds:
            bond_inst_ids = list({c[0].id for c in collected_bonds})
            existing_offering_map: dict[tuple[int, str], BondOffering] = {}
            offering_result = await db.execute(
                select(BondOffering).filter(BondOffering.instrument_id.in_(bond_inst_ids))
            )
            for o in offering_result.scalars().all():
                existing_offering_map[(int(o.instrument_id), str(o.isin))] = o
        else:
            existing_offering_map = {}

        for inst, data in collected_bonds:
            isin = data["isin"]
            existing = existing_offering_map.get((int(inst.id), isin))

            offering_kwargs = {
                "offering_date": data.get("offering_date"),
                "isin": isin,
                "coupon_type": data.get("coupon_type", "fixed"),
                "coupon_rate": data.get("coupon_rate"),
                "coupon_period_days": data.get("coupon_period_days"),
                "yield_to_maturity": data.get("yield_to_maturity"),
                "maturity_date": data.get("maturity_date"),
                "maturity_years": (data["maturity_date"] - date.today()).days / 365.25 if data.get("maturity_date") else None,
                "credit_rating": data.get("credit_rating"),
                "volume": data.get("volume"),
                "has_amortization": data.get("has_amortization", False),
                "has_offer": data.get("has_offer", False),
                "min_lot_rub": data.get("min_lot_rub"),
                "qual_investor_only": data.get("qual_investor_only", False),
                "nominal_price": data.get("nominal_price"),
                "current_price_pct": data.get("current_price_pct"),
                "duration_years": data.get("duration_years"),
            }

            emit_extra = {}
            if data.get("emitter_id") is not None:
                emit_extra["emitter_id"] = data["emitter_id"]
            if data.get("company_name"):
                emit_extra["company_name"] = data["company_name"]

            if existing:
                for key, val in offering_kwargs.items():
                    if val is not None:
                        setattr(existing, key, val)
                if emit_extra:
                    existing_extra = existing.extra or {}
                    existing_extra.update(emit_extra)
                    existing.extra = existing_extra
                updated_count += 1
            else:
                offering = BondOffering(
                    instrument_id=inst.id,
                    extra=emit_extra or None,
                    **offering_kwargs,
                )
                db.add(offering)
                new_count += 1

            # Store coupon schedule
            coupon_schedule = data.get("coupon_schedule", [])
            if coupon_schedule:
                await db.execute(
                    delete(BondCouponSchedule).filter_by(instrument_id=inst.id)
                )
                for cpn in coupon_schedule:
                    cpn_date = _parse_coupon_date(cpn.get("coupondate") or cpn.get("couponDate"))
                    if not cpn_date:
                        continue
                    with contextlib.suppress(ValueError, TypeError):
                        value = float(cpn.get("value", 0))
                    schedule_entry = BondCouponSchedule(
                        instrument_id=inst.id,
                        coupon_date=cpn_date,
                        coupon_value=value,
                        coupon_number=_safe_int(cpn.get("couponnumber") or cpn.get("couponNumber")),
                        currency=cpn.get("currency", "RUB"),
                        fix_date=_parse_coupon_date(cpn.get("fixdate") or cpn.get("fixDate")),
                        face_value=_safe_float(cpn.get("facevalue") or cpn.get("faceValue")),
                        initial_face_value=_safe_float(cpn.get("initialfacevalue") or cpn.get("initialFaceValue")),
                    )
                    db.add(schedule_entry)
                    coupon_count += 1

            # Save history snapshot
            if data.get("yield_to_maturity") is not None or data.get("current_price_pct") is not None:
                history_entry = BondOfferingHistory(
                    instrument_id=inst.id,
                    snapshot_date=date.today(),
                    offering_date=data.get("offering_date"),
                    isin=isin,
                    coupon_type=data.get("coupon_type", "fixed"),
                    coupon_rate=data.get("coupon_rate"),
                    coupon_period_days=data.get("coupon_period_days"),
                    yield_to_maturity=data.get("yield_to_maturity"),
                    duration_years=data.get("duration_years"),
                    spread_to_key_rate=data.get("spread_to_key_rate"),
                    maturity_date=data.get("maturity_date"),
                    maturity_years=(data["maturity_date"] - date.today()).days / 365.25 if data.get("maturity_date") else None,
                    credit_rating=data.get("credit_rating"),
                    current_price_pct=data.get("current_price_pct"),
                )
                db.add(history_entry)

        await db.commit()
        logger.info("Bond offerings: %d new, %d updated, %d coupons stored", new_count, updated_count, coupon_count)
    finally:
        await collector.close()


async def collect_discover_bonds(db: AsyncSession) -> int:
    """Fetch latest bond list from MOEX, add newly issued bonds to DB.

    Returns the number of new bonds discovered and added.
    """
    from src.analysis.bonds.new_bond_locator import discover_new_bonds

    results = await discover_new_bonds(db, max_results=1000)
    new_count = len(results)
    if new_count:
        logger.info("collect_discover_bonds: %d new bonds added to DB", new_count)
    return new_count


def _parse_coupon_date(val: Any) -> Optional[date]:
    if not val:
        return None
    if isinstance(val, date):
        return val
    if isinstance(val, str):
        try:
            return date.fromisoformat(val[:10])
        except (ValueError, TypeError):
            logger.debug("Could not parse date: %s", val[:10])
    return None



def collect_company_profiles(db: Session) -> None:
    """Fetch/update company profiles from SmartLab. Sync, run in executor."""
    from src.collectors.profiles import SmartLabProfileCollector, store_company_profile

    instruments = db.query(Instrument).filter(Instrument.instrument_type.in_(["stock", "etf"])).all()
    if not instruments:
        return

    collector = SmartLabProfileCollector()
    try:
        for inst in instruments:
            profile = collector.fetch_profile(inst.ticker)
            if profile:
                store_company_profile(db, inst, profile)
                logger.info("Profile updated for %s (%d fields)", inst.ticker, len(profile))
        db.commit()
    finally:
        collector.close()


async def collect_corporate_events(db: AsyncSession) -> None:
    """Fetch/update corporate events from MOEX ISS."""
    from src.collectors.profiles import MOEXCorporateEventCollector, store_corporate_event

    result = await db.execute(
        select(Instrument).filter(Instrument.instrument_type.in_(["stock", "etf"]))
    )
    instruments = result.scalars().all()
    if not instruments:
        return

    collector = MOEXCorporateEventCollector()
    try:
        for inst in instruments:
            events = await collector.fetch_corporate_events(inst.ticker)
            stored = 0
            for event in events:
                if store_corporate_event(db, inst, event):
                    stored += 1
            if stored:
                logger.info("Corporate events for %s: %d new", inst.ticker, stored)
        await db.commit()
    finally:
        await collector.close()


async def collect_alternative_data(db: AsyncSession) -> int:
    """Collect alternative data (CBR rates, Rosstat, Google Trends)."""
    from src.collectors.alternative import AlternativeDataCollector

    collector = AlternativeDataCollector()
    try:
        data = await collector.fetch_all()
        points = await collector.store_to_db(db, data)
        if points:
            logger.info("Alternative data: %d points stored", len(points))
        return len(points)
    finally:
        await collector.close()


async def run_news_summarizer(db: AsyncSession) -> str | None:
    """Cluster and summarize today's news, save digest."""
    from src.analysis.summarizer import NewsSummarizer

    summarizer = NewsSummarizer()
    try:
        digest = summarizer.generate_daily_digest(db)
        if digest and "No news clusters" not in digest:
            logger.info("News digest generated (%d chars)", len(digest))
            return digest
    except Exception as e:
        logger.error("News summarizer failed: %s", e)
    return None


async def run_sector_impact_analysis(db: AsyncSession) -> int:
    """Calculate sector impacts from today's news and store sector risk."""
    from datetime import datetime, timedelta

    from src.data.impact_matrix import ImpactMatrix
    from src.data.sector_impact_engine import SectorImpactEngine
    from src.data.sector_mapper import SectorMapper

    engine = SectorImpactEngine(impact_matrix=ImpactMatrix(), sector_mapper=SectorMapper())
    try:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
        result = await db.execute(
            select(News).filter(News.published_at >= cutoff, News.is_relevant)
        )
        articles = result.scalars().all()
        processed = 0
        for article in articles:
            impacts = engine.calculate_sector_impact_from_news(article, db)
            if impacts:
                engine.store_news_sector_impacts(article, impacts, db)
                processed += 1
        if processed:
            engine.calculate_all_sectors_daily_risk(db)
            logger.info("Sector impact: %d articles processed, risk updated", processed)
        return processed
    except Exception as e:
        logger.error("Sector impact analysis failed: %s", e)
        return 0


async def collect_social_posts(db: AsyncSession) -> int:
    """Collect social media posts (Telegram)."""
    from src.collectors.social import SocialMediaCollector
    from src.config import settings

    api_id = getattr(settings, "tg_api_id", None)
    api_hash = getattr(settings, "tg_api_hash", None)
    channels = getattr(settings, "tg_channels", "https://t.me/s/imoex_talks")
    if not api_id or not api_hash:
        logger.warning("tg_api_id/tg_api_hash not configured, skipping social collection")
        return 0

    collector = SocialMediaCollector(api_id=api_id, api_hash=api_hash)
    try:
        for ch in channels.split(","):
            ch = ch.strip()
            msgs = await collector.collect_telegram(db, ch, limit=30)
            if msgs:
                logger.info("Social posts: %d from %s", len(msgs), ch)
        return 0
    except Exception as e:
        logger.error("Social post collection failed: %s", e)
        return 0


async def async_compute_indicators(instrument_ids: set[int] | None = None) -> None:
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, compute_indicators, get_session(), instrument_ids)


async def async_collect_company_profiles() -> None:
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, collect_company_profiles, get_session())
