import logging
from datetime import datetime, timezone
from typing import Any

from src.collectors.sentiment import analyze_sentiment
from src.config import personal
from src.db.connection import get_session
from src.db.models import SentimentSignal, SocialPost

logger = logging.getLogger(__name__)

FINANCE_KEYWORDS = {
    "акци",
    "рынок",
    "инвестици",
    "дивиденд",
    "портфел",
    "трейдинг",
    "фондов",
    "облигаци",
    "валюта",
    "нефть",
    "рубль",
    "индекс",
    "волатильност",
    "доходность",
    "ставк",
    "ифя",
    "IPO",
    "прибыль",
    "убыт",
    "капитал",
    "лонг",
    "шорт",
    "трейд",
    "цена",
    "покупк",
    "продаж",
}


def _is_finance_post(text: str, tickers: list[str]) -> bool:
    if tickers:
        return True
    text_lower = text.lower()
    return any(kw in text_lower for kw in FINANCE_KEYWORDS)


def _post_text(p: SocialPost) -> str:
    return str(p.text or "")


def _post_tickers(p: SocialPost) -> list[str]:
    val: Any = p.tickers_mentioned
    return list(val) if val else []


class SocialSentimentAnalyzer:
    def __init__(self) -> None:
        cfg: dict[str, Any] = personal.get("social_sentiment", {})  # type: ignore[assignment]
        self._batch_size: int = cfg.get("batch_size", 5)
        self._min_length: int = cfg.get("min_post_length", 20)

    async def process_new_posts(self) -> int:
        db = get_session()
        try:
            posts: list[SocialPost] = (
                db.query(SocialPost)
                .filter(SocialPost.processed == False, SocialPost.deferred == False)  # noqa: E712
                .order_by(SocialPost.created_at)
                .all()
            )

            posts = [p for p in posts if _post_text(p) and len(_post_text(p)) >= self._min_length]
            if not posts:
                return 0

            relevant = [p for p in posts if _is_finance_post(_post_text(p), _post_tickers(p))]
            skipped = len(posts) - len(relevant)
            if skipped:
                skipped_ids = [p.id for p in posts if p not in relevant]
                db.query(SocialPost).filter(SocialPost.id.in_(skipped_ids)).update(
                    {
                        "processed": True,
                        "processed_at": datetime.now(timezone.utc),
                    },
                    synchronize_session="fetch",
                )
                db.commit()
                logger.info("Social: skipped %d non-finance posts", skipped)

            if not relevant:
                logger.info("Social: no finance-relevant posts to analyze")
                return 0

            post_ids = [p.id for p in relevant]
            signals_created = 0

            for i in range(0, len(post_ids), self._batch_size):
                batch_ids = post_ids[i : i + self._batch_size]
                batch = [p for p in relevant if p.id in batch_ids]

                result = self._process_batch(db, batch)
                signals_created += result

                db.query(SocialPost).filter(SocialPost.id.in_(batch_ids)).update(
                    {
                        "processed": True,
                        "processed_at": datetime.now(timezone.utc),
                    },
                    synchronize_session="fetch",
                )
                db.commit()

            logger.info("Social: %d signals created", signals_created)
            return signals_created
        finally:
            db.close()

    def _process_batch(self, db: Any, batch: list[SocialPost]) -> int:
        if not batch:
            return 0

        signals_created = 0
        for post in batch:
            text = _post_text(post)
            if not text:
                continue

            try:
                sent = analyze_sentiment(text, source_name="pulse")
            except Exception as e:
                logger.warning("ruBERT failed for post %d: %s", post.id, e)
                continue

            score = sent.get("score", 0)
            confidence = abs(score)
            if confidence < 0.1:
                continue

            bullish_score = max(score, 0)
            bearish_score = max(-score, 0)
            tickers = _post_tickers(post)
            ticker = tickers[0] if tickers else None

            sig = SentimentSignal(
                post_id=post.id,
                ticker=ticker,
                bullish_score=round(bullish_score, 4),
                bearish_score=round(bearish_score, 4),
                confidence=round(confidence, 4),
                llm_reasoning=f"ruBERT: score={score:.3f}",
                source_weight=1.0,
            )
            sig.composite_score = round((sig.bullish_score - sig.bearish_score) * sig.confidence, 4)
            db.add(sig)
            signals_created += 1

        return signals_created


analyzer = SocialSentimentAnalyzer()
