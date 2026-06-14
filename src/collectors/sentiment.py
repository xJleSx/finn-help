import logging
import re

logger = logging.getLogger(__name__)

# Source credibility weights (1.0 = highest)
SOURCE_WEIGHTS = {
    "Интерфакс": 1.0,
    "РБК": 0.9,
    "Коммерсантъ": 0.9,
    "Финам": 0.8,
    "Smart-lab": 0.6,
    "Econs": 0.85,
}

# Russian financial sentiment lexicon (~150 positive, ~150 negative)
POSITIVE_LEXICON = {
    # Financial performance
    "рост",
    "увеличение",
    "прибыль",
    "доход",
    "выручка",
    "капитализация",
    "дивиденд",
    "рентабельность",
    "маржинальность",
    "профицит",
    "оздоровление",
    "восстановление",
    "стабилизация",
    "модернизация",
    "диверсификация",
    "эффективность",
    "производительность",
    "инвестиция",
    "вложение",
    "накопление",
    # Market mood
    "уверенный",
    "позитивный",
    "перспективный",
    "благоприятный",
    "оптимизм",
    "оптимистичный",
    "стабильный",
    "надёжный",
    "устойчивый",
    "сбалансированный",
    "конкурентоспособный",
    "крепкий",
    "сильный",
    "растущий",
    "прогрессивный",
    "высокий",
    "лучший",
    "рекордный",
    "исторический",
    # Actions & events
    "повышение",
    "укрепление",
    "расширение",
    "развитие",
    "успех",
    "достижение",
    "превышение",
    "улучшение",
    "рост",
    "выгода",
    "успешный",
    # Company-specific
    "оферта",
    "выкуп",
    "buyback",
    "обратный",
    "сплит",
    "листинг",
    "IPO",
    "размещение",
    "премия",
    "бонус",
    "награда",
    "рейтинг",
    "повышен",
    "новация",
    "инновация",
    "цифровизация",
    "автоматизация",
    # Government / macro
    "субсидия",
    "поддержка",
    "льгота",
    "стимул",
    "помощь",
    "господдержка",
    "финансирование",
    "софинансирование",
    "снижение ставки",
    "смягчение",
    "либерализация",
    "дедолларизация",
    "импортозамещение",
    # Legal / regulatory
    "одобрение",
    "разрешение",
    "запуск",
    "открытие",
    "регистрация",
    "сертификация",
    "патент",
    # English business terms
    "growth",
    "profit",
    "gain",
    "rise",
    "upgrade",
    "positive",
    "bullish",
    "outperform",
    "upbeat",
    "rally",
    "surge",
    "breakthrough",
    "upturn",
    "recovery",
    "expansion",
    "increase",
    "surplus",
    "upside",
    "dividend",
}

NEGATIVE_LEXICON = {
    # Financial performance
    "падение",
    "снижение",
    "убыток",
    "потеря",
    "убыль",
    "долг",
    "задолженность",
    "дефицит",
    "убыточный",
    "нерентабельный",
    "неплатёжеспособность",
    "несостоятельность",
    "отток",
    "отмывание",
    "схема",
    "нарушение",
    "неустойка",
    "пеня",
    "штраф",
    "санкция",
    "пеня",
    "ликвидация",
    "банкротство",
    "дефолт",
    "реструктуризация",
    # Market mood
    "кризис",
    "рецессия",
    "стагнация",
    "стагфляция",
    "нестабильность",
    "неопределённость",
    "волатильность",
    "негативный",
    "пессимизм",
    "пессимистичный",
    "тревожный",
    "опасный",
    "рискованный",
    "слабый",
    "низкий",
    "плохой",
    "уязвимый",
    "неустойчивый",
    "шаткий",
    "хрупкий",
    "критический",
    "катастрофический",
    "обвальный",
    # Actions & events
    "обвал",
    "крах",
    "коллапс",
    "девальвация",
    "деноминация",
    "заморозка",
    "блокировка",
    "арест",
    "изъятие",
    "конфискация",
    "национализация",
    "экспроприация",
    "ограничение",
    "запрет",
    "эмбарго",
    "бойкот",
    "секвестр",
    "заморозка активов",
    # Company-specific
    "отзыв",
    "отставка",
    "увольнение",
    "сокращение",
    "закрытие",
    "остановка",
    "простой",
    "форс-мажор",
    "дефолт",
    "техдефолт",
    "кросс-дефолт",
    "списание",
    "обеспечение",
    "резерв",
    # Government / macro
    "инфляция",
    "гиперинфляция",
    "дефляция",
    "повышение ставки",
    "ужесточение",
    "закручивание",
    "репрессия",
    "подавление",
    "контроль",
    "мобилизация",
    "военное положение",
    "чрезвычайный",
    # Legal / regulatory
    "иск",
    "судебный",
    "разбирательство",
    "расследование",
    "проверка",
    "обыск",
    "арест",
    "обвинение",
    "претензия",
    "требование",
    "предписание",
    # Geopolitical
    "война",
    "конфликт",
    "агрессия",
    "вторжение",
    "теракт",
    "атака",
    "угроза",
    "давление",
    "изоляция",
    "отключение",
    "отсечение",
    # English business terms
    "decline",
    "drop",
    "fall",
    "loss",
    "downgrade",
    "negative",
    "bearish",
    "downfall",
    "crash",
    "plunge",
    "slump",
    "debt",
    "default",
    "bankruptcy",
    "recession",
    "crisis",
    "sanction",
    "restriction",
    "penalty",
    "devaluation",
}

BERT_LABELS = ["NEGATIVE", "NEUTRAL", "POSITIVE"]

_bert_pipeline = None


def _get_bert_pipeline():
    global _bert_pipeline
    if _bert_pipeline is not None:
        return _bert_pipeline
    try:
        from transformers import pipeline

        _bert_pipeline = pipeline(
            "sentiment-analysis",
            model="blanchefort/rubert-base-cased-sentiment",
            tokenizer="blanchefort/rubert-base-cased-sentiment",
            top_k=None,
        )
        logger.info("ruBERT sentiment model loaded")
    except Exception as e:
        logger.warning(f"ruBERT load failed ({e}), using keyword fallback")
        _bert_pipeline = False
    return _bert_pipeline


def analyze_sentiment(text: str, source_name: str | None = None) -> dict:
    weight = SOURCE_WEIGHTS.get(source_name, 0.5) if source_name else 0.7
    clean = re.sub(r"<[^>]+>", " ", text)
    clean = re.sub(r"\s+", " ", clean)[:512]

    bert_score = _bert_analyze(clean)
    keyword_score = _keyword_analyze(clean)

    if bert_score is not None:
        combined = round(bert_score * 0.6 + keyword_score * 0.4, 3)
    else:
        combined = keyword_score

    return {
        "score": combined,
        "weighted_score": round(combined * weight, 3),
        "keyword_score": keyword_score,
        "bert_score": bert_score,
        "source_weight": weight,
    }


def _bert_analyze(text: str) -> float | None:
    pipe = _get_bert_pipeline()
    if not pipe:
        return None
    try:
        result = pipe(text[:512])
        if isinstance(result, list) and isinstance(result[0], list):
            scores = {item["label"]: item["score"] for item in result[0]}
        elif isinstance(result, list) and isinstance(result[0], dict):
            scores = {item["label"]: item["score"] for item in result}
        else:
            return None

        positive = scores.get("POSITIVE", 0.0)
        negative = scores.get("NEGATIVE", 0.0)
        return round(positive - negative, 3)
    except Exception as e:
        logger.warning(f"BERT sentiment failed: {e}")
        return None


def _keyword_analyze(text: str) -> float:
    words = set(re.findall(r"[а-яёa-z]+", text.lower()))
    pos_count = len(words & POSITIVE_LEXICON)
    neg_count = len(words & NEGATIVE_LEXICON)
    total = pos_count + neg_count
    if total == 0:
        return 0.0
    raw = (pos_count - neg_count) / total
    return round(max(min(raw, 1.0), -1.0), 3)
