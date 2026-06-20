import json
import logging
from datetime import datetime, timezone
from typing import Any

from src.config import personal
from src.db.connection import get_session
from src.db.models import SentimentSignal, SocialPost
from src.llm.router import llm
from src.social.sentiment.prompts import BATCH_ANALYSIS_PROMPT

logger = logging.getLogger(__name__)


class SocialSentimentAnalyzer:
    def __init__(self) -> None:
        cfg = personal.get("social_sentiment", {})
        self._batch_size: int = cfg.get("batch_size", 10)
        self._min_length: int = cfg.get("min_post_length", 20)

    async def process_new_posts(self) -> int:
        db = get_session()
        try:
            posts: list[SocialPost] = (
                db.query(SocialPost)
                .filter(
                    SocialPost.processed == False,  # noqa: E712
                )
                .order_by(SocialPost.created_at)
                .all()
            )

            posts = [p for p in posts if p.text and len(p.text) >= self._min_length]
            if not posts:
                return 0

            post_ids = [p.id for p in posts]
            signals_created = 0
            for i in range(0, len(post_ids), self._batch_size):
                batch_ids = post_ids[i : i + self._batch_size]
                batch_signals = await self._process_batch(db, posts, batch_ids)
                for pid in batch_ids:
                    db.query(SocialPost).filter(SocialPost.id == pid).update(
                        {"processed": True, "processed_at": datetime.now(timezone.utc)},
                    )
                db.commit()
                signals_created += len(batch_signals)

            logger.info("Social: processed %d posts, created %d signals", len(posts), signals_created)
            return signals_created
        finally:
            db.close()

    async def _process_batch(
        self, db: Any, posts: list[SocialPost], batch_ids: list[int]
    ) -> list[SentimentSignal]:
        batch = [p for p in posts if p.id in batch_ids]
        posts_data: list[dict[str, object]] = [
            {
                "index": idx,
                "author": p.author_nick,
                "text": (p.text or "")[:1000],
                "tickers": p.tickers_mentioned or [],
            }
            for idx, p in enumerate(batch)
        ]
        prompt = BATCH_ANALYSIS_PROMPT.format(posts_json=json.dumps(posts_data, ensure_ascii=False))

        try:
            raw = await llm.analyze_social(prompt)
            results = self._parse_llm_response(raw)
        except Exception as e:
            logger.error("LLM batch analysis failed: %s", e)
            return []

        signals: list[SentimentSignal] = []
        for res in results:
            post_idx = res.get("post_index")
            if post_idx is None or post_idx >= len(batch):
                continue
            post = batch[post_idx]
            ticker = res.get("ticker") or None
            sig = SentimentSignal(
                post_id=post.id,
                ticker=ticker,
                bullish_score=float(res.get("bullish_score", 0)),
                bearish_score=float(res.get("bearish_score", 0)),
                confidence=float(res.get("confidence", 0)),
                llm_reasoning=res.get("reasoning", ""),
                source_weight=1.0,
            )
            sig.composite_score = round((sig.bullish_score - sig.bearish_score) * sig.confidence, 4)
            db.add(sig)
            signals.append(sig)
        return signals

    @staticmethod
    def _parse_llm_response(raw: str) -> list[dict[str, Any]]:
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[-1]
            cleaned = cleaned.rsplit("```", 1)[0]
        start = cleaned.find("[")
        end = cleaned.rfind("]")
        if start != -1 and end != -1:
            cleaned = cleaned[start : end + 1]
        try:
            data = json.loads(cleaned)
            if isinstance(data, list):
                return data
        except json.JSONDecodeError:
            logger.warning("Failed to parse LLM response: %s", raw[:200])
        return []


analyzer = SocialSentimentAnalyzer()
