import logging
from datetime import date, timedelta

import pandas as pd
from sqlalchemy.orm import Session

from src.collectors.cbr import CBRCollector
from src.collectors.moex import MOEXCollector
from src.collectors.news import NewsCollector
from src.constants import (
    DEFAULT_HISTORY_DAYS,
    DIVIDEND_CHECK_DAYS,
    NEWS_MAX_PER_FEED,
)
from src.db.connection import get_session
from src.db.models import (
    Dividend,
    GeoRiskScore,
    Indicator,
    Instrument,
    News,
    Price,
)
from src.geo.risk_scorer import GeoRiskScorer
from src.geo.sentiment_divergence import SentimentDivergenceDetector

logger = logging.getLogger(__name__)

STALENESS_THRESHOLD_DAYS = 2

divergence = SentimentDivergenceDetector()
geo_risk = GeoRiskScorer()


def _first(v1, v2):
    return v1 if v1 is not None else v2


async def _fetch_prices_for_instrument(db: Session, inst: Instrument, from_date: str, moex: MOEXCollector) -> int:
    board = {"stock": "stock", "bond": "bond", "etf": "etf"}.get(str(inst.instrument_type), "shares")
    history = await moex.get_history(inst.ticker, from_date=from_date, board=board)
    if not history:
        logger.debug("No price history for %s (board=%s, from=%s)", inst.ticker, board, from_date)
        return 0

    nominal: float | None = None
    if str(inst.instrument_type) == "bond":
        nominal = inst.nominal
        if nominal is None:
            info = await moex.get_security_info(inst.ticker)
            fv = info.get("face_value")
            if fv:
                nominal = float(fv)
                inst.nominal = nominal
                db.flush()
        if nominal is None:
            logger.warning("No face value for bond %s, skipping normalization", inst.ticker)

    def _bond_normalize(v: float | None) -> float | None:
        if v is not None and nominal is not None:
            return v * nominal / 100
        return v

    new_count = 0
    for row in history:
        d = row.get("TRADEDATE") or row.get("tradedate")
        if isinstance(d, str):
            d = date.fromisoformat(d)
        if not d:
            continue
        exists = db.query(Price).filter_by(instrument_id=inst.id, date=d).first()
        if exists:
            continue
        p = Price(
            instrument_id=inst.id,
            date=d,
            open=_bond_normalize(_first(row.get("OPEN"), row.get("open"))),
            high=_bond_normalize(_first(row.get("HIGH"), row.get("high"))),
            low=_bond_normalize(_first(row.get("LOW"), row.get("low"))),
            close=_bond_normalize(_first(row.get("CLOSE"), row.get("close"))),
            volume=_first(row.get("VOLUME"), row.get("volume")),
        )
        db.add(p)
        new_count += 1
    return new_count


async def fetch_price_history_for_instrument(ticker: str, instrument_type: str) -> int:
    """Авто-загрузка цен для нового инструмента при синке портфеля."""
    from_date = (date.today() - timedelta(days=DEFAULT_HISTORY_DAYS)).isoformat()
    db = get_session()
    try:
        inst = db.query(Instrument).filter_by(ticker=ticker).first()
        if not inst:
            logger.warning("Instrument %s not found in DB, cannot fetch price history", ticker)
            return 0
        async with MOEXCollector() as moex:
            new_count = await _fetch_prices_for_instrument(db, inst, from_date, moex)
        if new_count:
            db.commit()
        return new_count
    finally:
        db.close()


async def collect_prices(db: Session) -> set[int]:
    updated_ids: set[int] = set()
    async with MOEXCollector() as moex:
        instruments = db.query(Instrument).all()
        if not instruments:
            return updated_ids

        from sqlalchemy import func as sqlfunc

        last_dates = dict(db.query(Price.instrument_id, sqlfunc.max(Price.date)).group_by(Price.instrument_id).all())

        for inst in instruments:
            last_dt = last_dates.get(inst.id)
            days_back = DEFAULT_HISTORY_DAYS
            from_date = last_dt.isoformat() if last_dt else (date.today() - timedelta(days=days_back)).isoformat()
            new_count = await _fetch_prices_for_instrument(db, inst, from_date, moex)
            db.commit()
            if new_count > 0:
                updated_ids.add(int(inst.id))
    _check_price_freshness(db)
    return updated_ids


def _check_price_freshness(db: Session, max_age_days: int = STALENESS_THRESHOLD_DAYS):
    from sqlalchemy import func as sqlfunc

    subq = (
        db.query(
            Price.instrument_id,
            sqlfunc.max(Price.date).label("last_date"),
        )
        .group_by(Price.instrument_id)
        .subquery()
    )
    stale = (
        db.query(Instrument.ticker, Instrument.instrument_type, subq.c.last_date)
        .join(subq, Instrument.id == subq.c.instrument_id)
        .filter(subq.c.last_date < date.today() - timedelta(days=max_age_days))
        .all()
    )
    for ticker, itype, last_date in stale:
        logger.warning("Stale data: %s (%s) — last price %s, >%d days ago", ticker, itype, last_date, max_age_days)


async def collect_dividends(db: Session):
    async with MOEXCollector() as moex:
        instruments = db.query(Instrument).filter(Instrument.instrument_type.in_(["stock", "etf"])).all()
        if not instruments:
            return

        from sqlalchemy import func as sqlfunc

        last_dates = dict(
            db.query(Dividend.instrument_id, sqlfunc.max(Dividend.date)).group_by(Dividend.instrument_id).all()
        )

        for inst in instruments:
            last_dt = last_dates.get(inst.id)
            if last_dt and (date.today() - last_dt).days < DIVIDEND_CHECK_DAYS:
                continue
            try:
                dividends = await moex.get_dividends(inst.ticker)
                for row in dividends:
                    d = row.get("registryclosedate") or row.get("recordDate") or row.get("recorddate")
                    amt = row.get("value") or row.get("dividendGross")
                    if not d or not amt:
                        continue
                    if isinstance(d, str):
                        d = date.fromisoformat(d)
                    exists = db.query(Dividend).filter_by(instrument_id=inst.id, date=d, amount=float(amt)).first()
                    if not exists:
                        div = Dividend(
                            instrument_id=inst.id,
                            date=d,
                            amount=float(amt),
                            currency="RUB",
                        )
                        db.add(div)
                db.commit()
            except Exception as e:
                logger.warning(f"Dividends failed for {inst.ticker}: {e}")


def compute_indicators(db: Session, instrument_ids: set[int] | None = None):
    from src.analysis.technical import TechnicalAnalyzer

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
        prices_by_inst.setdefault(p.instrument_id, []).append(p)

    for inst in instruments:
        prices = prices_by_inst.get(inst.id, [])
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
        for _, row in df.iterrows():
            exists = db.query(Indicator).filter_by(instrument_id=inst.id, date=row["date"]).first()
            if exists:
                continue
            ind = Indicator(
                instrument_id=inst.id,
                date=row["date"],
                rsi=row.get("rsi"),
                macd_line=row.get("macd_line"),
                macd_signal=row.get("macd_signal"),
                macd_hist=row.get("macd_hist"),
                sma_20=row.get("sma_20"),
                sma_50=row.get("sma_50"),
                sma_200=row.get("sma_200"),
                bb_upper=row.get("bb_upper"),
                bb_lower=row.get("bb_lower"),
                bb_mid=row.get("bb_mid"),
                volume_sma_20=row.get("volume_sma_20"),
                atr=row.get("atr"),
            )
            db.add(ind)
        db.commit()


async def collect_news(db: Session) -> list[dict]:
    from src.db.models import NewsInstrument

    collector = NewsCollector()
    news_list = await collector.fetch_all(max_per_feed=NEWS_MAX_PER_FEED)

    ticker_map: dict[str, int] = {}
    for inst in db.query(Instrument).all():
        ticker_map[inst.ticker.upper()] = inst.id

    saved_news: list[News] = []
    for item in news_list:
        exists = db.query(News).filter_by(url=item["url"]).first()
        if exists:
            saved_news.append(exists)
            continue
        detail = item.get("sentiment_detail", {})
        n = News(
            url=item["url"],
            title=item["title"],
            summary=item["summary"],
            source_type=item["source_type"],
            source_name=item["source_name"],
            published_at=item["published_at"],
            sentiment_score=item.get("sentiment_score"),
            sentiment_weighted=item.get("sentiment_weighted"),
            sentiment_bert_score=detail.get("bert_score"),
            source_weight=detail.get("source_weight"),
        )
        db.add(n)
        db.flush()
        saved_news.append(n)

    for n in saved_news:
        search_text = f"{n.title or ''} {n.summary or ''}".upper()
        for ticker, inst_id in ticker_map.items():
            if len(ticker) >= 2 and ticker in search_text:
                exists = db.query(NewsInstrument).filter_by(news_id=n.id, instrument_id=inst_id).first()
                if not exists:
                    db.add(NewsInstrument(news_id=n.id, instrument_id=inst_id))

    db.commit()
    return news_list


async def compute_geo_risk(db: Session, news_list: list[dict]):
    sent = divergence.detect(news_list=news_list)
    cbr = CBRCollector()
    try:
        rates = await cbr.get_rates()
    except Exception:
        logger.warning("Failed to fetch CBR rates", exc_info=True)
        rates = []
    usd_rate = next((r for r in rates if r["code"] == "USD"), None)
    currency_vol = 0.0
    if usd_rate:
        prev = db.query(GeoRiskScore).order_by(GeoRiskScore.date.desc()).first()
        if prev and prev.components_json:
            prev_stress = prev.components_json.get("currency_stress", 0)
            currency_vol = prev_stress * 0.7 + min(abs(usd_rate.get("change_pct", 0)) * 5, 2.0) * 0.3
        else:
            currency_vol = min(abs(usd_rate.get("change_pct", 0)) * 5, 2.0)

    risk = geo_risk.score(news_list, currency_volatility=currency_vol)

    today = date.today()
    existing = db.query(GeoRiskScore).filter_by(date=today).first()
    if existing:
        existing.score = risk["score"]
        existing.components_json = dict(risk.get("components") or {})
        existing.sources_json = {"sentiment_divergence": sent, "news_count": len(news_list)}
    else:
        score = GeoRiskScore(
            date=today,
            score=risk["score"],
            components_json=risk.get("components"),
            sources_json={"sentiment_divergence": sent, "news_count": len(news_list)},
        )
        db.add(score)
    db.commit()


async def collect_fundamental(db: Session):
    from src.collectors.fundamental import FundamentalDataCollector
    from src.db.models import FundamentalMetric, Price

    instruments = db.query(Instrument).filter(Instrument.instrument_type.in_(["stock", "etf"])).all()
    if not instruments:
        return

    today = date.today()
    async with FundamentalDataCollector() as collector:
        for inst in instruments:
            last_price_row = (
                db.query(Price.close)
                .filter_by(instrument_id=inst.id)
                .order_by(Price.date.desc())
                .first()
            )
            last_price = float(last_price_row[0]) if last_price_row and last_price_row[0] is not None else None

            try:
                data = await collector.fetch(inst.ticker, last_price=last_price)
            except Exception as e:
                logger.warning("Fundamental fetch failed for %s: %s", inst.ticker, e)
                continue

            existing = db.query(FundamentalMetric).filter_by(instrument_id=inst.id, date=today).first()
            if existing:
                existing.market_cap = data["market_cap"]
                existing.shares_outstanding = data["shares_outstanding"]
                existing.extra = data.get("extra")
            else:
                metric = FundamentalMetric(
                    instrument_id=inst.id,
                    date=today,
                    market_cap=data["market_cap"],
                    shares_outstanding=data["shares_outstanding"],
                    extra=data.get("extra"),
                )
                db.add(metric)
        db.commit()


async def generate_signals(db: Session, updated_ids: set[int] | None = None) -> list[dict]:
    from src.analysis.service import analysis_service

    return analysis_service.analyze_all_sync(db, updated_ids=updated_ids)


async def collect_macro(db: Session):
    from src.collectors.macro import MacroCollector
    from src.db.models import MacroIndicator

    collector = MacroCollector()
    items = await collector.fetch_all()
    today = date.today()
    for item in items:
        exists = db.query(MacroIndicator).filter_by(date=today, indicator_type=item["indicator_type"]).first()
        if not exists:
            db.add(MacroIndicator(**item))
    db.commit()


async def collect_social_sentiment():
    from src.social.registry import registry
    from src.social.sentiment.analyzer import analyzer

    try:
        registry.build_from_config()
        sources = registry.get_active()
        if not sources:
            logger.info("No active social sources, skipping social collection")
            return

        from src.db.connection import get_session
        from src.db.models import SocialPost

        for src in sources:
            try:
                posts = await src.fetch_posts()
                db = get_session()
                try:
                    new_count = 0
                    for post in posts:
                        exists = (
                            db.query(SocialPost).filter_by(source=post.source, external_id=post.external_id).first()
                        )
                        if exists:
                            continue
                        sp = SocialPost(
                            source=post.source,
                            external_id=post.external_id,
                            author_nick=post.author_nick,
                            author_id=post.author_id,
                            text=post.text,
                            published_at=post.published_at,
                            url=post.url,
                            tickers_mentioned=post.tickers,
                            raw_json=post.raw,
                        )
                        db.add(sp)
                        new_count += 1
                    db.commit()
                    logger.info("Social %s: %d new posts", src.source_name, new_count)
                finally:
                    db.close()
            except Exception as e:
                logger.error("Social collection failed for %s: %s", src.source_name, e)

        count = await analyzer.process_new_posts()
        logger.info("Social sentiment: %d signals created", count)
    except Exception as e:
        logger.error("Social sentiment cycle failed: %s", e)
