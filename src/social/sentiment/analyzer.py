from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from src.collectors.sentiment import analyze_sentiment
from src.config import personal, settings
from src.db.connection import get_session
from src.db.models import SentimentSignal, SocialPost
from src.social.topics import classify_topic

logger = logging.getLogger(__name__)

FINANCE_KEYWORDS = {
    "акци", "рынок", "инвестици", "дивиденд", "портфел",
    "трейдинг", "фондов", "облигаци", "валюта", "нефть",
    "рубль", "индекс", "волатильност", "доходность", "ставк",
    "ифя", "IPO", "прибыль", "убыт", "капитал",
    "лонг", "шорт", "трейд", "цена", "покупк", "продаж",
}

BATCH_LLM_PROMPT = """Анализируй настроение постов. Ответ — JSON-массив.
Формат: [{{"post_index":N,"bullish":0.0-1.0,"bearish":0.0-1.0,"confidence":0.0-1.0,"topic":"macro|tech|oil_gas|finance|consumer|politics|real_estate|other","reason":"2-3 слова"}}]
Будь консервативен: если не уверен ставь confidence < 0.3.
Посты:
{posts_text}"""


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


def _get_source_weight(source: str) -> float:
    cfg: dict[str, Any] = personal.get("social_sources", {})
    return float(cfg.get(source, {}).get("weight", 0.5))


class SocialSentimentAnalyzer:
    def __init__(self) -> None:
        cfg: dict[str, Any] = personal.get("social_sentiment", {})
        self._batch_size: int = cfg.get("batch_size", 5)
        self._min_length: int = cfg.get("min_post_length", 20)
        self._use_llm: bool = settings.llm_social_enabled and bool(settings.groq_api_key)

    async def process_new_posts(self) -> int:
        db = get_session()
        try:
            posts: list[SocialPost] = (
                db.query(SocialPost)
                .filter(SocialPost.processed.is_(False), SocialPost.deferred.is_(False))
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
                    {"processed": True, "processed_at": datetime.now(timezone.utc)},
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

                if self._use_llm:
                    result = await self._process_batch_llm(db, batch)
                else:
                    result = self._process_batch(db, batch)
                signals_created += result

                db.query(SocialPost).filter(SocialPost.id.in_(batch_ids)).update(
                    {"processed": True, "processed_at": datetime.now(timezone.utc)},
                    synchronize_session="fetch",
                )
                db.commit()

            logger.info("Social: %d signals created (llm=%s)", signals_created, self._use_llm)
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
                sent = analyze_sentiment(text, source_name=post.source or "pulse")
            except Exception as e:
                logger.warning("ruBERT failed for post %d: %s", post.id, e)
                continue
            score = sent.get("score", 0)
            confidence = abs(score)
            if confidence < 0.1:
                continue
            signals_created += self._add_signal(post, score, confidence, f"ruBERT: score={score:.3f}")

        return signals_created

    async def _process_batch_llm(self, db: Any, batch: list[SocialPost]) -> int:
        if not batch:
            return 0
        from src.llm.router import llm as _llm

        posts_text = "\n---\n".join(
            f"[{i}] {_post_text(p)[:500]}" for i, p in enumerate(batch)
        )
        try:
            raw = await _llm.analyze_social(BATCH_LLM_PROMPT.format(posts_text=posts_text))
            results = json.loads(raw) if raw.strip().startswith("[") else []
        except Exception as e:
            logger.warning("LLM social analysis failed, fallback to ruBERT: %s", e)
            return self._process_batch(db, batch)

        if not isinstance(results, list):
            return self._process_batch(db, batch)

        signals = 0
        for entry in results:
            idx = entry.get("post_index")
            if idx is None or idx < 0 or idx >= len(batch):
                continue
            post = batch[idx]
            bullish = float(entry.get("bullish", 0))
            bearish = float(entry.get("bearish", 0))
            llm_conf = float(entry.get("confidence", 0.5))
            score = bullish - bearish
            if llm_conf < 0.3:
                sent = analyze_sentiment(_post_text(post), source_name=post.source or "pulse")
                score = sent.get("score", 0)
                llm_conf = abs(score)
                reasoning = f"ruBERT(LLM_low_conf): score={score:.3f}"
            else:
                reasoning = f"LLM({entry.get('reason','')}): bullish={bullish:.2f} bearish={bearish:.2f}"
            if llm_conf >= 0.1:
                signals += self._add_signal(post, score, llm_conf, reasoning)

        return signals

    def _add_signal(self, post: SocialPost, score: float, confidence: float, reasoning: str) -> int:
        tickers = _post_tickers(post)
        source_weight = _get_source_weight(post.source or "")
        topic = classify_topic(_post_text(post))
        enriched_reasoning = f"[{topic}] {reasoning}"
        signals_created = 0
        for ticker in tickers:
            sig = SentimentSignal(
                post_id=post.id,
                ticker=ticker,
                bullish_score=round(max(score, 0), 4),
                bearish_score=round(max(-score, 0), 4),
                confidence=round(confidence, 4),
                llm_reasoning=enriched_reasoning,
                source_weight=source_weight,
            )
            sig.composite_score = round((sig.bullish_score - sig.bearish_score) * sig.confidence, 4)
            db = get_session()
            try:
                db.add(sig)
                db.commit()
                signals_created += 1
            except Exception as e:
                logger.warning("Failed to save signal for post %d: %s", post.id, e)
                db.rollback()
            finally:
                db.close()
        return signals_created


analyzer = SocialSentimentAnalyzer()
