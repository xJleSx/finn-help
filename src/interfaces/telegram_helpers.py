import logging
import re

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from src.db.connection import get_session
from src.db.models import Instrument, Price
from src.db.models import Portfolio as PortModel

logger = logging.getLogger(__name__)

ACTION_EMOJI = {
    "BUY": "\U0001f7e2",
    "CAUTIOUS_BUY": "\U0001f7e1",
    "HOLD": "\u26aa",
    "SELL": "\U0001f534",
    "NEUTRAL": "\u26aa",
}

RUSSIAN_NAMES: dict[str, str] = {
    "сбер": "SBER", "сбера": "SBER", "сбербанк": "SBER",
    "газпром": "GAZP", "газпрома": "GAZP",
    "лукойл": "LKOH", "лукойла": "LKOH",
    "втб": "VTBR",
    "яндекс": "YNDX", "yandex": "YNDX",
    "нлмк": "NLMK",
    "магнит": "MGNT", "магнита": "MGNT",
    "мтс": "MTSS",
    "татнефть": "TATN", "татнефти": "TATN",
    "ростелеком": "RTKM",
    "фосагро": "PHOR",
    "афк система": "AFKS", "система": "AFKS",
    "аэрофлот": "AFLT",
    "роснефть": "ROSN", "роснефти": "ROSN",
    "норникель": "GMKN", "норильский никель": "GMKN",
    "полюс": "PLZL",
    "алроса": "ALRS",
    "северсталь": "CHMF",
    "магнитогорский": "MAGN",
    "интер рао": "IRAO",
    "ozon": "OZON",
    "тинькофф": "TCSG", "ткс": "TCSG", "tcsg": "TCSG",
    "озон": "OZON",
    "московская биржа": "MOEX", "биржа": "MOEX", "moex": "MOEX",
    "распадская": "RASP",
    "транснефть": "TRNFP",
    "преф сбер": "SBERP", "преф татнефть": "TATNP", "преф": "SNGSP",
    "самараэнерго": "SMLT", "юнипро": "UPRO",
    "всм": "VSMO", "всмпо": "VSMO",
    "полиметалл": "POLY", "русал": "RUAL",
    "пик": "PIKK", "пикк": "PIKK", "лср": "LSRG", "лсрг": "LSRG",
    "мосэнерго": "MSNG", "фск": "FEES", "федеральная сетевая": "FEES",
    "русгидро": "HYDR", "гидро": "HYDR",
    "башнефть": "BANE", "преф башнефть": "BANEP",
    "селенга": "SELG", "трубная": "TRNR",
    "five": "FIVE", "пятерочка": "FIVE", "x5": "FIVE", "икс5": "FIVE",
    "fix": "FIX", "фикс": "FIX",
}


def build_main_keyboard() -> InlineKeyboardMarkup:
    keyboard = [
        [
            InlineKeyboardButton("\U0001f50d Анализ", callback_data="action:top"),
            InlineKeyboardButton("🏭 Сектора", callback_data="action:sectors"),
        ],
        [
            InlineKeyboardButton("\U0001f4ca Портфель", callback_data="action:portfolio"),
            InlineKeyboardButton("\U0001f4dd Сводка", callback_data="action:daily"),
        ],
        [
            InlineKeyboardButton("\U0001f9ea Стресс-тест", callback_data="action:stress"),
            InlineKeyboardButton("\U0001f4e5 Экспорт CSV", callback_data="action:export"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)


def build_analyze_keyboard(ticker: str) -> InlineKeyboardMarkup:
    keyboard = [
        [
            InlineKeyboardButton("\u2795 Добавить 1 шт", callback_data=f"add:{ticker}"),
            InlineKeyboardButton("\U0001f4ca История", callback_data=f"history:{ticker}"),
        ],
        [
            InlineKeyboardButton("🏭 Сектора", callback_data="action:sectors"),
            InlineKeyboardButton("🏆 Топ", callback_data="action:top"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)


def build_top_keyboard() -> InlineKeyboardMarkup:
    keyboard = [
        [InlineKeyboardButton("\U0001f4b0 Распределить 100 000 ₽", callback_data="action:portfolio")]
    ]
    return InlineKeyboardMarkup(keyboard)


def _find_tickers(text: str) -> list[str]:
    text_lower = text.lower().strip()
    matched = re.findall(r"([а-яёa-z]+)", text_lower)
    for word in matched:
        if word in RUSSIAN_NAMES:
            return [RUSSIAN_NAMES[word]]
    for phrase, ticker in RUSSIAN_NAMES.items():
        if phrase in text_lower:
            return [ticker]
    try:
        db = get_session()
        try:
            instruments = db.query(Instrument.ticker).all()
            db_tickers = {r[0] for r in instruments}
        finally:
            db.close()
    except Exception:
        db_tickers = set()
    words = re.findall(r"[A-Za-z0-9]{2,}", text.upper())
    found = [w for w in words if w in db_tickers or w in RUSSIAN_NAMES.values()]
    if found:
        return found
    return []


def _find_excluded_tickers(text: str) -> set[str]:
    text_lower = text.lower()
    exclude: set[str] = set()
    exclude_keywords = [
        "без ", "кроме ", "недоступ", "не учитывай", "исключ",
        "убери ", "не рассматривай", "без учета", "без участия",
        "нет ", "нету ", "отсутств", "не им", "пока нет",
        "ещё нет", "нет в наличии", "не интересу", "не нужно",
        "не хочу", "не рассматрива",
    ]
    has_exclusion = any(k in text_lower for k in exclude_keywords)
    if not has_exclusion:
        return exclude
    all_tickers = _find_tickers(text)
    for ticker in all_tickers:
        t_lower = ticker.lower()
        if any(
            re.search(rf"\b{kw}\s*{re.escape(t_lower)}\b", text_lower)
            for kw in ["без", "кроме", "нет", "нету", "недоступ", "исключ", "убери", "отсутств", "не интересу", "не нужно"]
        ):
            exclude.add(ticker)
        elif any(
            re.search(rf"\b{re.escape(t_lower)}\s*{kw}\b", text_lower)
            for kw in ["нет", "нету", "отсутств", "недоступ", "исключ"]
        ):
            exclude.add(ticker)
    rev_map = {v.lower(): v for v in RUSSIAN_NAMES.values()}
    for t_lower, ticker in rev_map.items():
        if any(kw + t_lower in text_lower for kw in ["без ", "кроме ", "нет "]):
            exclude.add(ticker)
        if any(t_lower + " " + kw in text_lower for kw in ["нет", "отсутств", "недоступ", "исключ"]):
            exclude.add(ticker)
        if t_lower in text_lower and any(kw in text_lower for kw in ["недоступ", "исключ", "не учитывай", "убери"]):
            exclude.add(ticker)
    for phrase, ticker in RUSSIAN_NAMES.items():
        if any(kw + phrase in text_lower for kw in ["без ", "кроме ", "нет ", "недоступ", "исключ", "убери "]):
            exclude.add(ticker)
        if any(phrase + " " + kw in text_lower for kw in ["нет", "нету", "отсутств", "недоступ", "исключ", "убери"]):
            exclude.add(ticker)
    return exclude


def _extract_allocation_amount(text: str) -> float | None:
    text_lower = text.lower().strip()
    alloc_keywords = ["вложить", "инвестировать", "распредели", "распределение", "allocate", "разложить", "разместить"]
    if not any(k in text_lower for k in alloc_keywords):
        return None
    numbers = re.findall(r"(\d[\d\s]*\d|\d)", text_lower.replace(",", ".").replace(" ", ""))
    if numbers:
        return float(numbers[-1])
    return None


def _simplify_reasons(reasons: list[str]) -> str:
    if not reasons:
        return ""
    simple = []
    for r in reasons:
        r_lower = r.lower()
        if "RSI" in r:
            if "перепроданность" in r_lower:
                simple.append("📉 Акция недооценена — потенциальный разворот вверх")
            elif "перекупленность" in r_lower:
                simple.append("📈 Акция переоценена — возможна коррекция")
            else:
                simple.append("📊 Нейтральный баланс спроса и предложения")
        elif "macd" in r_lower:
            if "положитель" in r_lower:
                simple.append("🟢 Краткосрочный тренд восходящий")
            elif "отрицатель" in r_lower:
                simple.append("🔴 Краткосрочный тренд нисходящий")
        elif "цена ниже" in r_lower:
            simple.append("📉 Цена ниже средних значений — потенциальная зона для покупки")
        elif "цена выше" in r_lower:
            simple.append("📈 Цена выше средних значений — позитивный сигнал")
        elif "bollinger" in r_lower:
            if "отскок" in r_lower:
                simple.append("🎯 Цена у нижней границы — возможен отскок вверх")
            elif "коррекция" in r_lower:
                simple.append("⚠️ Цена у верхней границы — возможна коррекция вниз")
        elif "волатильность" in r_lower:
            if "high" in r_lower:
                simple.append("🌊 Высокая волатильность — повышенный риск")
            elif "low" in r_lower:
                simple.append("🌊 Низкая волатильность — рынок спокоен")
            else:
                simple.append("🌊 Нормальная волатильность")
        elif "risk:" in r_lower or "sharpe" in r_lower:
            continue
        elif "ml-прогноз" in r_lower or "ml" in r_lower:
            if "+" in r:
                simple.append("🤖 Прогноз модели: умеренный рост")
            elif "-" in r:
                simple.append("🤖 Прогноз модели: возможное снижение")
            else:
                simple.append("🤖 Прогноз модели: без изменений")
        elif "аномалии" in r_lower:
            simple.append("⚠️ Обнаружены аномалии в фундаментальных показателях")
        elif "геополитический" in r_lower:
            simple.append("🌍 Повышенные геополитические риски")
        elif "news" in r_lower or "новости" in r_lower:
            if "позитив" in r_lower or ">" in r:
                simple.append("📰 Новости положительные")
            elif "негатив" in r_lower:
                simple.append("📰 Новости негативные")
        elif "макро:" in r_lower or "brent" in r_lower or "ключевая" in r_lower:
            simple.append("🏛️ Макроэкономическая ситуация учитывается")
    if not simple:
        simple.append("↔️ Нейтральный сигнал")
    return "\n".join("• " + s for s in simple[:4])


def _format_allocation_plan(picks: list[dict], capital: float) -> str:
    candidates = []
    for p in picks:
        score = p.get("score", 0)
        price = p.get("last_price")
        if score > 0 and price and price > 0:
            candidates.append(p)
    if not candidates:
        return ""
    total_score = sum(c["score"] for c in candidates)
    if total_score <= 0:
        return ""
    max_positions = 7
    if capital < 1000:
        max_positions = 2
    elif capital < 5000:
        max_positions = 4
    used: list[dict] = []
    for p in candidates:
        if len(used) >= max_positions:
            break
        share = p["score"] / total_score
        amt = capital * share
        price = p["last_price"]
        if amt < price:
            continue
        shares = int(amt / price)
        if shares < 1:
            continue
        used.append({**p, "amount": amt, "shares": shares, "pct": amt / capital})
        total_score -= p["score"]
    if not used:
        return ""
    allocated = sum(u["amount"] for u in used)
    leftover = capital - allocated
    if leftover > 0:
        weights = [u["amount"] for u in used]
        total_w = sum(weights) or 1
        for i, u in enumerate(used):
            extra = leftover * weights[i] / total_w
            extra_shares = int(extra / (u["last_price"] or 1))
            if extra_shares > 0:
                u["shares"] += extra_shares
                u["amount"] = u["shares"] * (u["last_price"] or 1)
            u["pct"] = u["amount"] / capital
    text = "📊 *Как бы я распределил эти деньги:*\n\n"
    allocated = 0.0
    for item in used:
        allocated += item["amount"]
        text += f"• *{item['ticker']}* ({item.get('name', '')}): {item['amount']:,.0f} ₽ ({item['pct'] * 100:.0f}%)"
        if item["shares"] > 0:
            text += f" → {item['shares']} шт. по {item['last_price']:.0f} ₽"
        risk = item.get("risk", {})
        if risk:
            sl = risk.get("stop_loss")
            sl_pct = risk.get("stop_loss_pct")
            var = risk.get("var_95")
            if sl and sl_pct:
                text += f"\n   ⛔️ Продавать при падении ниже {sl:.0f} ₽ (–{abs(sl_pct):.1f}%)"
            if var:
                text += f"\n   ⚠️ Риск дневного падения: до {var:.1f}%"
        text += "\n"
    leftover = round(capital - allocated, 2)
    text += f"\n💰 *Итого:* {allocated:,.0f} из {capital:,.0f} ₽"
    if leftover > 0:
        text += f"\n💤 *Остаток:* {leftover:,.0f} ₽"
    return text


def _chunk_text(text: str, max_len: int) -> list[str]:
    if len(text) <= max_len:
        return [text]
    return [text[i : i + max_len] for i in range(0, len(text), max_len)]


def get_portfolio_positions(db) -> list[dict]:
    positions = db.query(PortModel).all()
    rows = []
    for p in positions:
        inst = db.query(Instrument).filter_by(id=p.instrument_id).first()
        price = db.query(Price).filter_by(instrument_id=p.instrument_id).order_by(Price.date.desc()).first()
        last_price = price.close if price else 0
        current_value = float(last_price * p.quantity) if last_price and p.quantity else 0
        profit_pct = round(((last_price / p.avg_price) - 1) * 100, 2) if last_price and p.avg_price and p.avg_price > 0 else 0
        rows.append({
            "ticker": inst.ticker if inst else "?",
            "name": inst.full_name if inst else "",
            "sector": inst.sector or "Прочее",
            "quantity": float(p.quantity),
            "avg_price": float(p.avg_price) if p.avg_price else 0,
            "current_price": float(last_price) if last_price else 0,
            "value": current_value,
            "allocation_pct": 0,
            "profit_pct": profit_pct,
        })
    return rows
