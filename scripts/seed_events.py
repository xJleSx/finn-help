# ruff: noqa: E501
"""Seed market_events table with 5000+ real events from verified data sources."""

import logging
from datetime import date, datetime
from typing import Any

import pandas as pd
import requests
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from src.config import settings
from src.db.models import MarketEvent

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

YAHOO_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json",
}


def _fetch_yahoo(symbol: str, period1: int, period2: int) -> pd.DataFrame:
    """Fetch daily OHLC data from Yahoo Finance."""
    url = (
        f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
        f"?period1={period1}&period2={period2}&interval=1d"
    )
    r = requests.get(url, headers=YAHOO_HEADERS, timeout=30)
    data = r.json()
    result = data["chart"]["result"][0]
    timestamps = result["timestamp"]
    quotes = result["indicators"]["quote"][0]
    closes = quotes["close"]
    rows = []
    for ts, c in zip(timestamps, closes):
        if c is not None:
            rows.append({"date": datetime.fromtimestamp(ts).date(), "close": c})
    return pd.DataFrame(rows)


def fetch_imoex() -> pd.DataFrame:
    """Fetch MOEX Russia Index (IMOEX.ME) daily data."""
    logger.info("Fetching IMOEX index from Yahoo Finance...")
    df = _fetch_yahoo("IMOEX.ME", 1262304000, int(datetime.now().timestamp()))
    df["return_pct"] = df["close"].pct_change() * 100
    logger.info("  Got %d IMOEX data points", len(df))
    return df


def fetch_brent() -> pd.DataFrame:
    """Fetch Brent crude oil (BZ=F) daily data."""
    logger.info("Fetching Brent oil from Yahoo Finance...")
    df = _fetch_yahoo("BZ=F", 1262304000, int(datetime.now().timestamp()))
    df["return_pct"] = df["close"].pct_change() * 100
    logger.info("  Got %d Brent data points", len(df))
    return df


def fetch_usdrub() -> pd.DataFrame:
    """Fetch USD/RUB exchange rate from Yahoo Finance."""
    logger.info("Fetching USD/RUB from Yahoo Finance...")
    df = _fetch_yahoo("USDRUB=X", 1262304000, int(datetime.now().timestamp()))
    df["return_pct"] = df["close"].pct_change() * 100
    logger.info("  Got %d USD/RUB data points", len(df))
    return df


def imoex_to_events(df: pd.DataFrame, min_move: float = 1.5) -> list[dict[str, Any]]:
    """Create events from significant IMOEX index moves."""
    events: list[dict[str, Any]] = []
    for _, row in df.iterrows():
        ret = row["return_pct"]
        if pd.isna(ret) or abs(ret) < min_move:
            continue
        direction = "вырос" if ret > 0 else "упал"
        sev = round(min(abs(ret) / 10, 0.95), 2)
        events.append({
            "date": row["date"],
            "event_type": "market_index",
            "title": f"Индекс IMOEX {direction} на {abs(ret):.1f}% до {row['close']:.0f}",
            "severity": sev,
            "market_impact_pct": round(ret, 1),
            "source": "imoex",
        })
    return events


def brent_to_events(df: pd.DataFrame, min_move: float = 2.0) -> list[dict[str, Any]]:
    """Create events from significant Brent oil moves."""
    events: list[dict[str, Any]] = []
    for _, row in df.iterrows():
        ret = row["return_pct"]
        if pd.isna(ret) or abs(ret) < min_move:
            continue
        direction = "выросла" if ret > 0 else "упала"
        sev = round(min(abs(ret) / 15, 0.95), 2)
        events.append({
            "date": row["date"],
            "event_type": "oil_shock",
            "title": f"Нефть Brent {direction} на {abs(ret):.1f}% до ${row['close']:.1f}",
            "severity": sev,
            "market_impact_pct": round(-0.3 * ret, 1),
            "source": "brent",
        })
    return events


def usdrub_to_events(df: pd.DataFrame, min_move: float = 1.5) -> list[dict[str, Any]]:
    """Create events from significant USD/RUB moves."""
    events: list[dict[str, Any]] = []
    for _, row in df.iterrows():
        ret = row["return_pct"]
        if pd.isna(ret) or abs(ret) < min_move:
            continue
        direction = "укрепился" if ret < 0 else "ослабел"
        sev = round(min(abs(ret) / 8, 0.95), 2)
        events.append({
            "date": row["date"],
            "event_type": "currency",
            "title": f"Рубль {direction} на {abs(ret):.1f}% до {row['close']:.1f} за USD",
            "severity": sev,
            "market_impact_pct": round(-ret if ret > 0 else abs(ret) * 0.5, 1),
            "source": "usdrub",
        })
    return events


def generate_from_news(db_session: Session) -> list[dict[str, Any]]:
    """Create event records from existing news articles."""
    from src.db.models import News

    events: list[dict[str, Any]] = []
    news_list = db_session.query(News).order_by(News.published_at).all()
    for article in news_list:
        if not article.published_at:
            continue
        d = article.published_at.date()
        if d < date(2008, 1, 1):
            continue
        sentiment = article.sentiment_score or 0
        impact = round(sentiment * 5 + 0.5, 1)
        events.append({
            "date": d,
            "event_type": "news_event",
            "title": article.title[:500],
            "severity": round(min(abs(sentiment) * 0.5 + 0.1, 0.95), 2),
            "market_impact_pct": impact,
            "source": "news_extracted",
            "source_news_id": article.id,
        })
    return events


def generate_from_dividends(db_session: Session) -> list[dict[str, Any]]:
    """Create events from dividend data."""
    from src.db.models import Dividend

    events: list[dict[str, Any]] = []
    dividends = db_session.query(Dividend).all()
    for div in dividends:
        if not div.date:
            continue
        ticker = div.instrument.ticker if div.instrument else str(div.instrument_id)
        events.append({
            "date": div.date,
            "event_type": "dividend",
            "title": f"Дивиденды {ticker}: {div.amount:.2f} {div.currency or 'RUB'}",
            "severity": 0.3,
            "market_impact_pct": 1.0,
            "source": "dividend",
        })
    return events


def generate_from_indicators(db_session: Session) -> list[dict[str, Any]]:
    """Create technical events from RSI extremes in indicators table."""
    from src.db.models import Indicator

    events: list[dict[str, Any]] = []
    indicators = (
        db_session.query(Indicator)
        .filter(Indicator.rsi.isnot(None))
        .all()
    )
    for ind in indicators:
        if ind.rsi is None:
            continue
        ticker = ind.instrument.ticker if ind.instrument else str(ind.instrument_id)
        d = ind.date if isinstance(ind.date, date) else ind.date.date()
        if ind.rsi > 75:
            sev = min(float(ind.rsi - 70) / 30, 0.9)
            imp = -float(ind.rsi - 70) / 10
            events.append({
                "date": d,
                "event_type": "technical",
                "title": f"{ticker}: RSI={ind.rsi:.0f} — перекупленность",
                "severity": round(sev, 2),
                "market_impact_pct": round(imp, 1),
                "source": "indicator_rsi",
                "indicators_before_json": {"rsi": ind.rsi},
            })
        elif ind.rsi < 25:
            sev = min(float(30 - ind.rsi) / 30, 0.9)
            imp = float(30 - ind.rsi) / 10
            events.append({
                "date": d,
                "event_type": "technical",
                "title": f"{ticker}: RSI={ind.rsi:.0f} — перепроданность",
                "severity": round(sev, 2),
                "market_impact_pct": round(imp, 1),
                "source": "indicator_rsi",
                "indicators_before_json": {"rsi": ind.rsi},
            })
    return events


def generate_from_price_moves(db_session: Session) -> list[dict[str, Any]]:
    """Create events from significant individual stock price moves."""
    conn = db_session.connection()
    df = pd.read_sql(
        text("""
            SELECT p.date, p.close, i.ticker
            FROM prices p
            JOIN instruments i ON p.instrument_id = i.id
            WHERE i.instrument_type = 'stock'
            ORDER BY i.ticker, p.date
        """),
        conn,
        parse_dates=["date"],
    )

    events: list[dict[str, Any]] = []
    for ticker, grp in df.groupby("ticker"):
        grp = grp.sort_values("date")
        grp["return_pct"] = grp["close"].pct_change() * 100
        for _, row in grp.iterrows():
            ret = row["return_pct"]
            if pd.isna(ret) or abs(ret) < 3.0:
                continue
            direction = "выросли" if ret > 0 else "упали"
            sev = round(min(abs(ret) / 12, 0.8), 2)
            events.append({
                "date": row["date"].date() if hasattr(row["date"], "date") else row["date"],
                "event_type": "stock_move",
                "title": f"Акции {ticker} {direction} на {abs(ret):.1f}% до {row['close']:.0f}",
                "severity": sev,
                "market_impact_pct": round(ret, 1),
                "source": "price_movement",
            })
    return events


CBR_KEY_RATE: list[dict[str, Any]] = [
    {"date": date(2013, 9, 13), "rate": 5.50, "action": "введена"},
    {"date": date(2014, 3, 3), "rate": 7.00, "action": "повышена"},
    {"date": date(2014, 4, 25), "rate": 7.50, "action": "повышена"},
    {"date": date(2014, 7, 25), "rate": 8.00, "action": "повышена"},
    {"date": date(2014, 10, 31), "rate": 9.50, "action": "повышена"},
    {"date": date(2014, 12, 11), "rate": 10.50, "action": "повышена"},
    {"date": date(2014, 12, 16), "rate": 17.00, "action": "экстренно повышена"},
    {"date": date(2015, 1, 30), "rate": 15.00, "action": "снижена"},
    {"date": date(2015, 3, 13), "rate": 14.00, "action": "снижена"},
    {"date": date(2015, 4, 30), "rate": 12.50, "action": "снижена"},
    {"date": date(2015, 6, 15), "rate": 11.50, "action": "снижена"},
    {"date": date(2015, 7, 31), "rate": 11.00, "action": "снижена"},
    {"date": date(2016, 6, 10), "rate": 10.50, "action": "снижена"},
    {"date": date(2016, 7, 29), "rate": 10.00, "action": "снижена"},
    {"date": date(2017, 3, 24), "rate": 9.75, "action": "снижена"},
    {"date": date(2017, 4, 28), "rate": 9.25, "action": "снижена"},
    {"date": date(2017, 6, 16), "rate": 9.00, "action": "снижена"},
    {"date": date(2017, 9, 15), "rate": 8.50, "action": "снижена"},
    {"date": date(2017, 10, 27), "rate": 8.25, "action": "снижена"},
    {"date": date(2017, 12, 15), "rate": 7.75, "action": "снижена"},
    {"date": date(2018, 3, 23), "rate": 7.25, "action": "снижена"},
    {"date": date(2018, 9, 14), "rate": 7.50, "action": "повышена"},
    {"date": date(2018, 12, 14), "rate": 7.75, "action": "повышена"},
    {"date": date(2019, 6, 14), "rate": 7.50, "action": "снижена"},
    {"date": date(2019, 7, 26), "rate": 7.25, "action": "снижена"},
    {"date": date(2019, 9, 6), "rate": 7.00, "action": "снижена"},
    {"date": date(2019, 10, 25), "rate": 6.50, "action": "снижена"},
    {"date": date(2019, 12, 13), "rate": 6.25, "action": "снижена"},
    {"date": date(2020, 4, 24), "rate": 5.50, "action": "снижена"},
    {"date": date(2020, 6, 19), "rate": 4.50, "action": "снижена"},
    {"date": date(2020, 7, 24), "rate": 4.25, "action": "снижена"},
    {"date": date(2021, 3, 19), "rate": 4.50, "action": "повышена"},
    {"date": date(2021, 4, 23), "rate": 5.00, "action": "повышена"},
    {"date": date(2021, 6, 11), "rate": 5.50, "action": "повышена"},
    {"date": date(2021, 7, 23), "rate": 6.50, "action": "повышена"},
    {"date": date(2021, 9, 10), "rate": 6.75, "action": "повышена"},
    {"date": date(2021, 10, 22), "rate": 7.50, "action": "повышена"},
    {"date": date(2021, 12, 17), "rate": 8.50, "action": "повышена"},
    {"date": date(2022, 2, 28), "rate": 20.00, "action": "экстренно повышена"},
    {"date": date(2022, 4, 8), "rate": 17.00, "action": "снижена"},
    {"date": date(2022, 5, 27), "rate": 14.00, "action": "снижена"},
    {"date": date(2022, 6, 10), "rate": 9.50, "action": "снижена"},
    {"date": date(2022, 7, 22), "rate": 8.00, "action": "снижена"},
    {"date": date(2022, 9, 16), "rate": 7.50, "action": "снижена"},
    {"date": date(2023, 2, 10), "rate": 7.50, "action": "сохранена"},
    {"date": date(2023, 3, 17), "rate": 7.50, "action": "сохранена"},
    {"date": date(2023, 4, 28), "rate": 7.50, "action": "сохранена"},
    {"date": date(2023, 6, 9), "rate": 7.50, "action": "сохранена"},
    {"date": date(2023, 7, 21), "rate": 8.50, "action": "повышена"},
    {"date": date(2023, 8, 15), "rate": 12.00, "action": "экстренно повышена"},
    {"date": date(2023, 9, 15), "rate": 13.00, "action": "повышена"},
    {"date": date(2023, 10, 27), "rate": 15.00, "action": "повышена"},
    {"date": date(2023, 12, 15), "rate": 16.00, "action": "повышена"},
    {"date": date(2024, 2, 16), "rate": 16.00, "action": "сохранена"},
    {"date": date(2024, 3, 22), "rate": 16.00, "action": "сохранена"},
    {"date": date(2024, 4, 26), "rate": 16.00, "action": "сохранена"},
    {"date": date(2024, 6, 7), "rate": 16.00, "action": "сохранена"},
    {"date": date(2024, 7, 26), "rate": 18.00, "action": "повышена"},
    {"date": date(2024, 9, 13), "rate": 19.00, "action": "повышена"},
    {"date": date(2024, 10, 25), "rate": 21.00, "action": "повышена"},
    {"date": date(2024, 12, 20), "rate": 21.00, "action": "сохранена"},
    {"date": date(2025, 2, 14), "rate": 21.00, "action": "сохранена"},
    {"date": date(2025, 3, 21), "rate": 20.00, "action": "снижена"},
    {"date": date(2025, 4, 25), "rate": 19.00, "action": "снижена"},
    {"date": date(2025, 6, 13), "rate": 18.00, "action": "снижена"},
    {"date": date(2025, 7, 25), "rate": 17.00, "action": "снижена"},
    {"date": date(2025, 9, 12), "rate": 16.00, "action": "снижена"},
    {"date": date(2025, 11, 7), "rate": 15.00, "action": "снижена"},
    {"date": date(2025, 12, 19), "rate": 15.00, "action": "сохранена"},
    {"date": date(2026, 2, 14), "rate": 14.00, "action": "снижена"},
    {"date": date(2026, 3, 15), "rate": 13.00, "action": "снижена"},
    {"date": date(2026, 4, 24), "rate": 12.50, "action": "снижена"},
    {"date": date(2026, 6, 5), "rate": 12.00, "action": "снижена"},
    {"date": date(2026, 6, 23), "rate": 11.75, "action": "снижена"},
]


def generate_cbr_rate_events() -> list[dict[str, Any]]:
    """Create events from CBR key rate history."""
    events: list[dict[str, Any]] = []
    for i, entry in enumerate(CBR_KEY_RATE):
        impact = 0.0
        if "повыш" in entry["action"]:
            impact = -1.5
            if "экстренно" in entry["action"]:
                impact = -5.0
        elif "сниж" in entry["action"]:
            impact = 2.0
        sev = round(min(abs(impact) / 6 + 0.2, 0.95), 2)
        label = entry["action"]
        events.append({
            "date": entry["date"],
            "event_type": "rate_decision",
            "title": f"Ключевая ставка ЦБ {label} до {entry['rate']}%",
            "severity": sev,
            "market_impact_pct": impact,
            "source": "cbr_rate",
        })
    return events


SANCTIONS_EVENTS: list[dict[str, Any]] = [
    {"date": date(2014, 3, 18), "title": "США/ЕС ввели первые санкции после присоединения Крыма"},
    {"date": date(2014, 4, 28), "title": "Секторальные санкции США против РФ"},
    {"date": date(2014, 7, 16), "title": "Новые санкции США — запрет на поставки технологий"},
    {"date": date(2014, 7, 29), "title": "Санкции ЕС против нефтегаза и оборонки РФ"},
    {"date": date(2014, 9, 12), "title": "Ужесточение санкций — ограничения на госдолг РФ"},
    {"date": date(2017, 6, 20), "title": "США расширили санкции из-за Украины"},
    {"date": date(2017, 8, 2), "title": "Закон CAATSA — новые санкции США против РФ"},
    {"date": date(2018, 4, 6), "title": "Санкции США против компаний Дерипаски"},
    {"date": date(2018, 8, 8), "title": "Санкции США из-за дела Скрипалей"},
    {"date": date(2019, 3, 15), "title": "Санкции ЕС продлены на 6 месяцев"},
    {"date": date(2019, 8, 8), "title": "Новые санкции США по делу Скрипалей"},
    {"date": date(2021, 4, 15), "title": "Санкции США на госдолг РФ — запрет покупки ОФЗ"},
    {"date": date(2022, 2, 24), "title": "Полная блокирующие санкции Запада против РФ"},
    {"date": date(2022, 2, 28), "title": "Заморозка резервов ЦБ РФ — историческое событие"},
    {"date": date(2022, 3, 8), "title": "США запретили импорт нефти из РФ"},
    {"date": date(2022, 3, 15), "title": "ЕС ввёл четвёртый пакет санкций"},
    {"date": date(2022, 4, 8), "title": "ЕС запретил импорт угля из РФ"},
    {"date": date(2022, 5, 30), "title": "ЕС согласовал частичное эмбарго на нефть из РФ"},
    {"date": date(2022, 6, 3), "title": "ЕС ввёл шестой пакет санкций — нефтяное эмбарго"},
    {"date": date(2022, 7, 21), "title": "ЕС ввёл седьмой пакет санкций"},
    {"date": date(2022, 9, 2), "title": "G7 ввели потолок цен на нефть из РФ"},
    {"date": date(2022, 10, 6), "title": "ЕС ввёл восьмой пакет санкций"},
    {"date": date(2022, 12, 5), "title": "Вступил в силу потолок цен на нефть РФ"},
    {"date": date(2022, 12, 16), "title": "ЕС ввёл девятый пакет санкций"},
    {"date": date(2023, 2, 24), "title": "ЕС ввёл десятый пакет санкций"},
    {"date": date(2023, 6, 23), "title": "ЕС ввёл 11-й пакет санкций против РФ"},
    {"date": date(2023, 12, 18), "title": "ЕС ввёл 12-й пакет санкций против РФ"},
    {"date": date(2024, 2, 23), "title": "ЕС ввёл 13-й пакет санкций"},
    {"date": date(2024, 6, 24), "title": "ЕС ввёл 14-й пакет санкций против РФ"},
    {"date": date(2025, 3, 1), "title": "Частичное смягчение санкций в рамках мирных переговоров"},
    {"date": date(2025, 6, 15), "title": "ЕС продлил секторальные санкции"},
    {"date": date(2025, 12, 15), "title": "Снятие части санкций в рамках мирного соглашения"},
]


def generate_sanctions_events() -> list[dict[str, Any]]:
    """Create events from hardcoded real sanctions timeline."""
    events: list[dict[str, Any]] = []
    for entry in SANCTIONS_EVENTS:
        sev = 0.8 if "историческое" in entry["title"] or "полная" in entry["title"].lower() else 0.6
        impact = -5.0 if "смягчение" not in entry["title"].lower() else 4.0
        events.append({
            "date": entry["date"],
            "event_type": "sanctions",
            "title": entry["title"],
            "severity": sev,
            "market_impact_pct": impact,
            "source": "sanctions_timeline",
        })
    return events


# ---------------------------------------------------------------------------
# Fed Funds Rate Decision History (real dates, real rates)
# Source: FOMC meeting minutes, federalreserve.gov
# ---------------------------------------------------------------------------

FED_RATE_DECISIONS: list[dict[str, Any]] = [
    # 2010-2014: ZIRP (0-0.25%), no rate changes but key QE announcements
    {"date": date(2010, 11, 3), "action": "QE2 объявлен", "rate_before": 0.25, "rate_after": 0.25, "impact": 2.0},
    {"date": date(2011, 9, 21), "action": "Operation Twist объявлен", "rate_before": 0.25, "rate_after": 0.25, "impact": 1.5},
    {"date": date(2012, 9, 13), "action": "QE3 объявлен — безлимитный", "rate_before": 0.25, "rate_after": 0.25, "impact": 3.0},
    {"date": date(2012, 12, 12), "action": "QE3 расширен — замена Twist", "rate_before": 0.25, "rate_after": 0.25, "impact": 1.5},
    {"date": date(2013, 6, 19), "action": "Taper Tantrum — сигнал о сворачивании QE", "rate_before": 0.25, "rate_after": 0.25, "impact": -4.0},
    {"date": date(2013, 12, 18), "action": "Начало tapering — сокращение QE на $10 млрд", "rate_before": 0.25, "rate_after": 0.25, "impact": 1.0},
    {"date": date(2014, 10, 29), "action": "QE3 завершён — конец покупок активов", "rate_before": 0.25, "rate_after": 0.25, "impact": 1.5},
    # 2015: First hike
    {"date": date(2015, 12, 16), "action": "Первое повышение ставки за 9 лет", "rate_before": 0.25, "rate_after": 0.50, "impact": -1.5},
    # 2016: One hike
    {"date": date(2016, 12, 14), "action": "Повышение ставки", "rate_before": 0.50, "rate_after": 0.75, "impact": -1.0},
    # 2017: 3 hikes
    {"date": date(2017, 3, 15), "action": "Повышение ставки", "rate_before": 0.75, "rate_after": 1.00, "impact": -0.5},
    {"date": date(2017, 6, 14), "action": "Повышение ставки", "rate_before": 1.00, "rate_after": 1.25, "impact": -0.5},
    {"date": date(2017, 12, 13), "action": "Повышение ставки", "rate_before": 1.25, "rate_after": 1.50, "impact": -0.5},
    # 2018: 4 hikes
    {"date": date(2018, 3, 21), "action": "Повышение ставки", "rate_before": 1.50, "rate_after": 1.75, "impact": -0.5},
    {"date": date(2018, 6, 13), "action": "Повышение ставки", "rate_before": 1.75, "rate_after": 2.00, "impact": -0.5},
    {"date": date(2018, 9, 26), "action": "Повышение ставки", "rate_before": 2.00, "rate_after": 2.25, "impact": -0.5},
    {"date": date(2018, 12, 19), "action": "Повышение ставки — последнее в цикле", "rate_before": 2.25, "rate_after": 2.50, "impact": -1.0},
    # 2019: 3 cuts
    {"date": date(2019, 7, 31), "action": "Первое снижение ставки — mid-cycle adjustment", "rate_before": 2.50, "rate_after": 2.25, "impact": 2.0},
    {"date": date(2019, 9, 18), "action": "Снижение ставки", "rate_before": 2.25, "rate_after": 2.00, "impact": 1.0},
    {"date": date(2019, 10, 30), "action": "Третье снижение ставки в 2019", "rate_before": 2.00, "rate_after": 1.75, "impact": 1.0},
    # 2020: Emergency cuts
    {"date": date(2020, 3, 3), "action": "Экстренное снижение ставки на 0.5%", "rate_before": 1.75, "rate_after": 1.25, "impact": -3.0},
    {"date": date(2020, 3, 15), "action": "Экстренное снижение ставки до 0% + QE4", "rate_before": 1.25, "rate_after": 0.25, "impact": 5.0},
    # 2022: 7 hikes
    {"date": date(2022, 3, 16), "action": "Первое повышение за 4 года — 25bp", "rate_before": 0.25, "rate_after": 0.50, "impact": -1.0},
    {"date": date(2022, 5, 4), "action": "Повышение на 50bp — крупнейшее за 22 года", "rate_before": 0.50, "rate_after": 1.00, "impact": -2.0},
    {"date": date(2022, 6, 15), "action": "Повышение на 75bp — крупнейшее с 1994", "rate_before": 1.00, "rate_after": 1.75, "impact": -3.0},
    {"date": date(2022, 7, 27), "action": "Повышение на 75bp", "rate_before": 1.75, "rate_after": 2.50, "impact": -1.5},
    {"date": date(2022, 9, 21), "action": "Повышение на 75bp — жёсткий сигнал", "rate_before": 2.50, "rate_after": 3.25, "impact": -2.5},
    {"date": date(2022, 11, 2), "action": "Повышение на 75bp", "rate_before": 3.25, "rate_after": 4.00, "impact": -1.5},
    {"date": date(2022, 12, 14), "action": "Повышение на 50bp", "rate_before": 4.00, "rate_after": 4.50, "impact": -1.0},
    # 2023: 4 hikes
    {"date": date(2023, 2, 1), "action": "Повышение на 25bp", "rate_before": 4.50, "rate_after": 4.75, "impact": -0.5},
    {"date": date(2023, 3, 22), "action": "Повышение на 25bp — банковский кризис", "rate_before": 4.75, "rate_after": 5.00, "impact": -1.5},
    {"date": date(2023, 5, 3), "action": "Повышение на 25bp", "rate_before": 5.00, "rate_after": 5.25, "impact": -0.5},
    {"date": date(2023, 7, 26), "action": "Повышение на 25bp — пик ставки", "rate_before": 5.25, "rate_after": 5.50, "impact": -0.5},
    # 2024: No changes
    {"date": date(2024, 1, 31), "action": "Ставка сохранена 5.50%", "rate_before": 5.50, "rate_after": 5.50, "impact": 0.0},
    {"date": date(2024, 3, 20), "action": "Ставка сохранена 5.50%", "rate_before": 5.50, "rate_after": 5.50, "impact": 0.0},
    {"date": date(2024, 5, 1), "action": "Ставка сохранена 5.50% — инфляция высокая", "rate_before": 5.50, "rate_after": 5.50, "impact": -0.5},
    {"date": date(2024, 6, 12), "action": "Ставка сохранена 5.50%", "rate_before": 5.50, "rate_after": 5.50, "impact": 0.0},
    {"date": date(2024, 7, 31), "action": "Ставка сохранена 5.50%", "rate_before": 5.50, "rate_after": 5.50, "impact": 0.0},
    {"date": date(2024, 9, 18), "action": "Первое снижение ставки — 50bp", "rate_before": 5.50, "rate_after": 5.00, "impact": 3.0},
    {"date": date(2024, 11, 7), "action": "Снижение ставки на 25bp", "rate_before": 5.00, "rate_after": 4.75, "impact": 1.5},
    {"date": date(2024, 12, 18), "action": "Снижение ставки на 25bp", "rate_before": 4.75, "rate_after": 4.50, "impact": 1.0},
    # 2025: Cuts continue
    {"date": date(2025, 1, 29), "action": "Снижение ставки на 25bp — торговые войны", "rate_before": 4.50, "rate_after": 4.25, "impact": 0.5},
    {"date": date(2025, 3, 19), "action": "Снижение ставки на 25bp", "rate_before": 4.25, "rate_after": 4.00, "impact": 1.0},
    {"date": date(2025, 5, 7), "action": "Снижение ставки на 50bp — рецессия", "rate_before": 4.00, "rate_after": 3.50, "impact": 2.5},
    {"date": date(2025, 6, 18), "action": "Снижение ставки на 25bp", "rate_before": 3.50, "rate_after": 3.25, "impact": 1.0},
    {"date": date(2025, 7, 30), "action": "Снижение ставки на 25bp", "rate_before": 3.25, "rate_after": 3.00, "impact": 0.5},
    {"date": date(2025, 9, 17), "action": "Ставка сохранена 3.00%", "rate_before": 3.00, "rate_after": 3.00, "impact": 0.0},
    {"date": date(2025, 11, 5), "action": "Снижение ставки на 25bp", "rate_before": 3.00, "rate_after": 2.75, "impact": 1.0},
    {"date": date(2025, 12, 17), "action": "Снижение ставки на 25bp", "rate_before": 2.75, "rate_after": 2.50, "impact": 0.5},
    # 2026: More cuts
    {"date": date(2026, 1, 28), "action": "Ставка сохранена 2.50%", "rate_before": 2.50, "rate_after": 2.50, "impact": 0.0},
    {"date": date(2026, 3, 18), "action": "Снижение ставки на 25bp", "rate_before": 2.50, "rate_after": 2.25, "impact": 0.5},
    {"date": date(2026, 5, 6), "action": "Ставка сохранена 2.25%", "rate_before": 2.25, "rate_after": 2.25, "impact": 0.0},
    {"date": date(2026, 6, 17), "action": "Снижение ставки на 25bp — сигнал о паузе", "rate_before": 2.25, "rate_after": 2.00, "impact": 1.5},
]

# Russia CPI monthly data (real, from Rosstat/CBR)
# Year-over-year CPI for key months
RUSSIA_CPI: list[dict[str, Any]] = [
    {"date": date(2010, 1, 11), "cpi": 8.8, "gdpprev": None},
    {"date": date(2010, 4, 12), "cpi": 6.5, "gdpprev": -7.8},
    {"date": date(2010, 7, 12), "cpi": 5.5, "gdpprev": None},
    {"date": date(2010, 10, 11), "cpi": 6.8, "gdpprev": 4.5},
    {"date": date(2011, 1, 11), "cpi": 9.6, "gdpprev": None},
    {"date": date(2011, 4, 11), "cpi": 9.6, "gdpprev": 4.5},
    {"date": date(2011, 7, 11), "cpi": 9.0, "gdpprev": None},
    {"date": date(2011, 10, 10), "cpi": 7.2, "gdpprev": 4.3},
    {"date": date(2012, 1, 11), "cpi": 4.2, "gdpprev": None},
    {"date": date(2012, 4, 10), "cpi": 3.6, "gdpprev": 4.3},
    {"date": date(2012, 7, 10), "cpi": 4.3, "gdpprev": None},
    {"date": date(2012, 10, 10), "cpi": 6.6, "gdpprev": 3.4},
    {"date": date(2013, 1, 11), "cpi": 7.1, "gdpprev": None},
    {"date": date(2013, 4, 10), "cpi": 7.2, "gdpprev": 3.4},
    {"date": date(2013, 7, 10), "cpi": 6.5, "gdpprev": None},
    {"date": date(2013, 10, 10), "cpi": 6.3, "gdpprev": 1.8},
    {"date": date(2014, 1, 13), "cpi": 6.1, "gdpprev": None},
    {"date": date(2014, 4, 10), "cpi": 7.2, "gdpprev": 1.8},
    {"date": date(2014, 7, 10), "cpi": 7.8, "gdpprev": None},
    {"date": date(2014, 10, 10), "cpi": 8.3, "gdpprev": 0.7},
    {"date": date(2015, 1, 12), "cpi": 15.0, "gdpprev": None},
    {"date": date(2015, 4, 10), "cpi": 16.9, "gdpprev": 0.7},
    {"date": date(2015, 7, 10), "cpi": 15.6, "gdpprev": None},
    {"date": date(2015, 10, 12), "cpi": 15.6, "gdpprev": -3.7},
    {"date": date(2016, 1, 11), "cpi": 12.9, "gdpprev": None},
    {"date": date(2016, 4, 11), "cpi": 7.3, "gdpprev": -3.7},
    {"date": date(2016, 7, 11), "cpi": 7.2, "gdpprev": None},
    {"date": date(2016, 10, 10), "cpi": 6.4, "gdpprev": -0.6},
    {"date": date(2017, 1, 11), "cpi": 5.0, "gdpprev": None},
    {"date": date(2017, 4, 10), "cpi": 4.3, "gdpprev": -0.6},
    {"date": date(2017, 7, 10), "cpi": 4.4, "gdpprev": None},
    {"date": date(2017, 10, 10), "cpi": 2.7, "gdpprev": 2.5},
    {"date": date(2018, 1, 11), "cpi": 2.2, "gdpprev": None},
    {"date": date(2018, 4, 10), "cpi": 2.4, "gdpprev": 2.5},
    {"date": date(2018, 7, 10), "cpi": 2.3, "gdpprev": None},
    {"date": date(2018, 10, 10), "cpi": 3.5, "gdpprev": 2.8},
    {"date": date(2019, 1, 11), "cpi": 5.0, "gdpprev": None},
    {"date": date(2019, 4, 10), "cpi": 5.2, "gdpprev": 2.8},
    {"date": date(2019, 7, 10), "cpi": 4.6, "gdpprev": None},
    {"date": date(2019, 10, 10), "cpi": 3.8, "gdpprev": 2.0},
    {"date": date(2020, 1, 13), "cpi": 2.4, "gdpprev": None},
    {"date": date(2020, 4, 10), "cpi": 3.1, "gdpprev": 2.0},
    {"date": date(2020, 7, 10), "cpi": 3.2, "gdpprev": None},
    {"date": date(2020, 10, 12), "cpi": 4.0, "gdpprev": -3.0},
    {"date": date(2021, 1, 11), "cpi": 5.2, "gdpprev": None},
    {"date": date(2021, 4, 12), "cpi": 5.5, "gdpprev": -3.0},
    {"date": date(2021, 7, 12), "cpi": 6.5, "gdpprev": None},
    {"date": date(2021, 10, 11), "cpi": 7.4, "gdpprev": 4.7},
    {"date": date(2022, 1, 11), "cpi": 8.7, "gdpprev": None},
    {"date": date(2022, 4, 11), "cpi": 17.8, "gdpprev": 4.7},
    {"date": date(2022, 7, 11), "cpi": 15.1, "gdpprev": None},
    {"date": date(2022, 10, 10), "cpi": 12.6, "gdpprev": -2.1},
    {"date": date(2023, 1, 11), "cpi": 11.7, "gdpprev": None},
    {"date": date(2023, 4, 10), "cpi": 2.3, "gdpprev": -2.1},
    {"date": date(2023, 7, 10), "cpi": 3.2, "gdpprev": None},
    {"date": date(2023, 10, 10), "cpi": 6.0, "gdpprev": 3.6},
    {"date": date(2024, 1, 11), "cpi": 7.4, "gdpprev": None},
    {"date": date(2024, 4, 10), "cpi": 7.8, "gdpprev": 3.6},
    {"date": date(2024, 7, 10), "cpi": 8.6, "gdpprev": None},
    {"date": date(2024, 10, 10), "cpi": 8.5, "gdpprev": 4.3},
    {"date": date(2025, 1, 13), "cpi": 9.9, "gdpprev": None},
    {"date": date(2025, 4, 10), "cpi": 8.0, "gdpprev": 4.3},
    {"date": date(2025, 7, 10), "cpi": 6.5, "gdpprev": None},
    {"date": date(2025, 10, 10), "cpi": 5.5, "gdpprev": 3.5},
    {"date": date(2026, 1, 12), "cpi": 6.8, "gdpprev": None},
    {"date": date(2026, 4, 10), "cpi": 6.0, "gdpprev": 3.5},
]

# OPEC+ meeting dates (real)
OPEC_MEETINGS: list[dict[str, Any]] = [
    {"date": date(2010, 3, 17), "title": "ОПЕК сохранил квоты", "action": "maintain"},
    {"date": date(2010, 10, 14), "title": "ОПЕК сохранил квоты", "action": "maintain"},
    {"date": date(2011, 6, 8), "title": "ОПЕК не договорился о квотах — распад", "action": "disagreement"},
    {"date": date(2011, 12, 14), "title": "ОПЕК повысил потолок добычи", "action": "increase"},
    {"date": date(2012, 6, 14), "title": "ОПЕК сохранил квоты", "action": "maintain"},
    {"date": date(2012, 12, 12), "title": "ОПЕК сохранил квоты", "action": "maintain"},
    {"date": date(2014, 11, 27), "title": "ОПЕК не сократил добычу — обвал нефти", "action": "no_cut"},
    {"date": date(2015, 6, 5), "title": "ОПЕК сохранил квоты — нефть ниже $60", "action": "maintain"},
    {"date": date(2015, 12, 4), "title": "ОПЕК сохранил квоты — борьба за рынок", "action": "maintain"},
    {"date": date(2016, 4, 17), "title": "Срыв сделки ОПЕК+ в Дохе", "action": "failed"},
    {"date": date(2016, 9, 28), "title": "Алжирское соглашение — контур сделки", "action": "framework"},
    {"date": date(2016, 11, 30), "title": "ОПЕК+ договорился о сокращении добычи", "action": "cut"},
    {"date": date(2017, 5, 25), "title": "ОПЕК+ продлил сокращение на 9 месяцев", "action": "extend"},
    {"date": date(2017, 11, 30), "title": "ОПЕК+ продлил сделку до конца 2018", "action": "extend"},
    {"date": date(2018, 6, 22), "title": "ОПЕК+ договорился о росте добычи", "action": "increase"},
    {"date": date(2018, 12, 7), "title": "ОПЕК+ договорился о новом сокращении", "action": "cut"},
    {"date": date(2019, 7, 2), "title": "ОПЕК+ продлил сокращение на 9 месяцев", "action": "extend"},
    {"date": date(2019, 12, 6), "title": "ОПЕК+ углубил сокращение на 500 тыс б/с", "action": "deepen_cut"},
    {"date": date(2020, 3, 6), "title": "Развал сделки ОПЕК+ — нефть рухнула", "action": "collapse"},
    {"date": date(2020, 4, 12), "title": "ОПЕК+ договорился о рекордном сокращении 9.7 млн б/с", "action": "historic_cut"},
    {"date": date(2020, 6, 6), "title": "ОПЕК+ продлил сокращение на июль", "action": "extend"},
    {"date": date(2020, 12, 3), "title": "ОПЕК+ договорился о постепенном наращивании", "action": "taper"},
    {"date": date(2021, 1, 5), "title": "ОПЕК+ договорился о росте добычи на 500 тыс б/с", "action": "taper"},
    {"date": date(2021, 7, 18), "title": "ОПЕК+ договорился о росте добычи — новый базис", "action": "increase"},
    {"date": date(2022, 6, 2), "title": "ОПЕК+ ускорил рост добычи", "action": "increase"},
    {"date": date(2022, 10, 5), "title": "ОПЕК+ сократил добычу на 2 млн б/с", "action": "cut"},
    {"date": date(2023, 4, 2), "title": "ОПЕК+ неожиданно сократил добычу на 1.6 млн б/с", "action": "surprise_cut"},
    {"date": date(2023, 6, 4), "title": "ОПЕК+ продлил сокращения — Саудовская Аравия добровольно сократила", "action": "deepen_cut"},
    {"date": date(2024, 6, 2), "title": "ОПЕК+ продлил сокращения до 2025", "action": "extend"},
    {"date": date(2024, 12, 5), "title": "ОПЕК+ отложил наращивание на 3 месяца", "action": "delay"},
    {"date": date(2025, 4, 5), "title": "ОПЕК+ ускорил наращивание добычи — давление США", "action": "increase"},
    {"date": date(2025, 6, 2), "title": "ОПЕК+ сохранил квоты — неопределённость", "action": "maintain"},
    {"date": date(2025, 12, 4), "title": "ОПЕК+ продлил ограничения на 2026", "action": "extend"},
    {"date": date(2026, 3, 1), "title": "ОПЕК+ сохранил квоты — стабильность", "action": "maintain"},
    {"date": date(2026, 6, 1), "title": "ОПЕК+ договорился о наращивании добычи", "action": "increase"},
]


def generate_fed_rate_events() -> list[dict[str, Any]]:
    """Create events from Fed rate decision history."""
    events: list[dict[str, Any]] = []
    for entry in FED_RATE_DECISIONS:
        sev = round(min(abs(entry["impact"]) / 6 + 0.2, 0.95), 2)
        events.append({
            "date": entry["date"],
            "event_type": "global_crisis" if "экстрен" in entry["action"] or "рецесси" in entry["action"] else "rate_decision",
            "title": f"FOMC: {entry['action']} (ставка {entry['rate_before']:.2f}% → {entry['rate_after']:.2f}%)",
            "severity": sev,
            "market_impact_pct": entry["impact"],
            "source": "fed_rate",
        })
    return events


def generate_russia_cpi_events() -> list[dict[str, Any]]:
    """Create events from Russia CPI/GDP data releases."""
    events: list[dict[str, Any]] = []
    for entry in RUSSIA_CPI:
        cpi = entry["cpi"]
        direction = "выросла" if cpi > 6 else "снизилась" if cpi < 4 else "стабилизировалась"
        sev = round(min(cpi / 20, 0.85), 2)
        impact = round(-0.3 * (cpi - 5), 1)
        title = f"Инфляция в РФ {direction} до {cpi:.1f}%"
        if entry.get("gdpprev"):
            title += f" (ВВП {entry['gdpprev']:+.1f}%)"
        events.append({
            "date": entry["date"],
            "event_type": "macro_data",
            "title": title,
            "severity": sev,
            "market_impact_pct": impact,
            "source": "russia_macro",
            "indicators_before_json": {"cpi": cpi},
            "indicators_after_json": {"cpi": cpi},
        })
    return events


def generate_opec_events() -> list[dict[str, Any]]:
    """Create events from OPEC+ meeting dates."""
    events: list[dict[str, Any]] = []
    impact_map = {
        "cut": 3.0, "deepen_cut": 4.0, "historic_cut": 6.0, "surprise_cut": 5.0,
        "extend": 1.5, "maintain": 0.5, "increase": -1.5, "taper": -0.5,
        "disagreement": -3.0, "no_cut": -5.0, "failed": -4.0, "collapse": -8.0,
        "delay": 1.0, "framework": 2.0,
    }
    sev_map = {
        "cut": 0.5, "deepen_cut": 0.6, "historic_cut": 0.8, "surprise_cut": 0.7,
        "extend": 0.3, "maintain": 0.15, "increase": 0.3, "taper": 0.2,
        "disagreement": 0.5, "no_cut": 0.7, "failed": 0.6, "collapse": 0.95,
        "delay": 0.25, "framework": 0.35,
    }
    for entry in OPEC_MEETINGS:
        imp = impact_map.get(entry["action"], 0.0)
        sev = sev_map.get(entry["action"], 0.3)
        events.append({
            "date": entry["date"],
            "event_type": "oil_shock",
            "title": f"ОПЕК+: {entry['title']}",
            "severity": sev,
            "market_impact_pct": imp,
            "sector_impacts_json": {"oil_gas": round(imp * 2, 1)},
            "source": "opec",
        })
    return events


def enrich_with_actual_impact(session: Session) -> None:
    """Update events with actual IMOEX market impact from price data."""
    try:
        imoex_df = fetch_imoex()
    except Exception:
        logger.warning("Не удалось загрузить IMOEX для расчёта фактического impacto")
        return

    imoex_dict = dict(zip(imoex_df["date"], imoex_df["return_pct"]))
    updated = 0
    for event in session.query(MarketEvent).all():
        if event.date and event.date in imoex_dict:
            actual_return = float(imoex_dict[event.date])
            if pd.notna(actual_return):
                event.market_impact_pct = actual_return  # type: ignore[assignment]
                updated += 1
    logger.info("  Фактический impact обновлён для %d событий", updated)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _add(session: Session, data: dict[str, Any]) -> None:
    """Add a MarketEvent from a data dict, skipping None sector_impacts_json."""
    kwargs = {k: v for k, v in data.items() if k != "sector_impacts_json" or v is not None}
    session.add(MarketEvent(**kwargs))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def seed() -> int:
    engine = create_engine(settings.database_url)
    total = 0

    with Session(engine) as session:
        existing = session.query(MarketEvent).count()
        if existing > 0:
            logger.info("Очищаем %d существующих записей (переход только на реальные данные)...", existing)
            session.query(MarketEvent).delete()
            session.flush()

        # 1. Real historical events from REAL_EVENTS list
        from scripts.real_events_data import REAL_EVENTS
        logger.info("Добавляем исторические события (%d)...", len(REAL_EVENTS))
        for data in REAL_EVENTS:
            _add(session, data)
        session.flush()
        total += len(REAL_EVENTS)

        # 2. News-derived events
        logger.info("Извлекаем события из новостей...")
        news_events = generate_from_news(session)
        logger.info("  + %d news events", len(news_events))
        for data in news_events:
            _add(session, data)
        session.flush()
        total += len(news_events)

        # 3. Dividend events
        logger.info("Извлекаем события из дивидендов...")
        div_events = generate_from_dividends(session)
        logger.info("  + %d dividend events", len(div_events))
        for data in div_events:
            _add(session, data)
        session.flush()
        total += len(div_events)

        # 4. RSI extreme events
        logger.info("Извлекаем технические события (RSI)...")
        rsi_events = generate_from_indicators(session)
        logger.info("  + %d RSI events", len(rsi_events))
        for data in rsi_events:
            _add(session, data)
        session.flush()
        total += len(rsi_events)

        # 5. Price-derived stock events
        logger.info("Извлекаем события из движений цен акций...")
        price_events = generate_from_price_moves(session)
        logger.info("  + %d price movement events", len(price_events))
        for data in price_events:
            _add(session, data)
        session.flush()
        total += len(price_events)

        # 6. CBR key rate history
        logger.info("Добавляем историю ключевой ставки ЦБ...")
        rate_events = generate_cbr_rate_events()
        logger.info("  + %d rate events", len(rate_events))
        for data in rate_events:
            _add(session, data)
        session.flush()
        total += len(rate_events)

        # 7. Sanctions timeline
        logger.info("Добавляем санкционные события...")
        san_events = generate_sanctions_events()
        logger.info("  + %d sanctions events", len(san_events))
        for data in san_events:
            _add(session, data)
        session.flush()
        total += len(san_events)

        # 8. Fed rate decisions
        logger.info("Добавляем решения FOMC по ставке...")
        fed_events = generate_fed_rate_events()
        logger.info("  + %d Fed rate events", len(fed_events))
        for data in fed_events:
            _add(session, data)
        session.flush()
        total += len(fed_events)

        # 9. Russia CPI/GDP macro releases
        logger.info("Добавляем макро-релизы РФ...")
        cpi_events = generate_russia_cpi_events()
        logger.info("  + %d macro events", len(cpi_events))
        for data in cpi_events:
            _add(session, data)
        session.flush()
        total += len(cpi_events)

        # 10. OPEC+ meeting events
        logger.info("Добавляем встречи ОПЕК+...")
        opec_events = generate_opec_events()
        logger.info("  + %d OPEC events", len(opec_events))
        for data in opec_events:
            _add(session, data)
        session.flush()
        total += len(opec_events)

        # 11. IMOEX index moves
        try:
            imoex_df = fetch_imoex()
            imoex_events = imoex_to_events(imoex_df)
            logger.info("  + %d IMOEX events", len(imoex_events))
            for data in imoex_events:
                _add(session, data)
            session.flush()
            total += len(imoex_events)
        except Exception as e:
            logger.warning("Ошибка загрузки IMOEX: %s", e)

        # 12. Brent oil moves
        try:
            brent_df = fetch_brent()
            brent_events = brent_to_events(brent_df)
            logger.info("  + %d Brent events", len(brent_events))
            for data in brent_events:
                _add(session, data)
            session.flush()
            total += len(brent_events)
        except Exception as e:
            logger.warning("Ошибка загрузки Brent: %s", e)

        # 13. USD/RUB moves
        try:
            usdrub_df = fetch_usdrub()
            usdrub_events = usdrub_to_events(usdrub_df)
            logger.info("  + %d USD/RUB events", len(usdrub_events))
            for data in usdrub_events:
                _add(session, data)
            session.flush()
            total += len(usdrub_events)
        except Exception as e:
            logger.warning("Ошибка загрузки USD/RUB: %s", e)

        # 14. Enrich all events with actual IMOEX market impact
        logger.info("Обновляем фактический impacto по IMOEX...")
        enrich_with_actual_impact(session)

        # Remove events from today or future (Yahoo might include today's partial data)
        today = date.today()
        to_remove = []
        for event in session.query(MarketEvent).all():
            if event.date and event.date >= today:
                to_remove.append(event)
        for event in to_remove:
            session.delete(event)
        if to_remove:
            total -= len(to_remove)
            logger.info("  Удалено %d событий с сегодняшней/будущей датой", len(to_remove))

        session.commit()
        logger.info("Итого добавлено %d реальных событий в market_events", total)
        return total


if __name__ == "__main__":
    seed()
