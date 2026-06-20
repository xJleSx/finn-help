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

FINANCE_KEYWORDS = {
    "акци", "рынок", "инвестици", "дивиденд", "портфел", "трейдинг",
    "фондов", "облигаци", "валюта", "нефть", "рубль", "индекс",
    "волатильност", "доходность", "ставк", "ифя", "IPO",
    "прибыль", "убыт", "капитал", "лонг", "шорт", "трейд",
    "цена", "покупк", "продаж",
}


def _is_finance_post(text: str, tickers: list[str]) -> bool:
    if tickers:
        return True
    text_lower = text.lower()
    return any(kw in text_lower for kw in FINANCE_KEYWORDS)


def _estimate_tokens(text: str) -> int:
    return len(text) // 2


def _post_text(p: SocialPost) -> str:
    return str(p.text or "")


def _post_tickers(p: SocialPost) -> list[str]:
    val: Any = p.tickers_mentioned
    return list(val) if val else []


def _estimate_batch_cost(batch: list[SocialPost]) -> int:
    prompt_tokens = sum(_estimate_tokens(_post_text(p)) for p in batch)
    prompt_tokens += 200
    response_tokens = len(batch) * 40
    return prompt_tokens + response_tokens


class SocialSentimentAnalyzer:
    def __init__(self) -> None:
        cfg: dict[str, Any] = personal.get("social_sentiment", {})  # type: ignore[assignment]
        self._batch_size: int = cfg.get("batch_size", 5)
        self._min_length: int = cfg.get("min_post_length", 20)
        self._max_tokens_per_run: int = cfg.get("max_tokens_per_run", 80_000)

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
                # Mark irrelevant as processed (no signal needed)
                for p in posts:
                    if p not in relevant:
                        db.query(SocialPost).filter(SocialPost.id == p.id).update({
                            "processed": True,
                            "processed_at": datetime.now(timezone.utc),
                        })
                db.commit()
                logger.info("Social: skipped %d non-finance posts", skipped)

            if not relevant:
                logger.info("Social: no finance-relevant posts to analyze")
                return 0

            post_ids = [p.id for p in relevant]
            signals_created = 0
            token_budget = self._max_tokens_per_run
            deferred_count = 0

            for i in range(0, len(post_ids), self._batch_size):
                batch_ids = post_ids[i : i + self._batch_size]
                batch = [p for p in relevant if p.id in batch_ids]

                cost = _estimate_batch_cost(batch)
                if cost > token_budget:
                    for p in relevant[i:]:
                        db.query(SocialPost).filter(SocialPost.id == p.id).update({
                            "deferred": True,
                        })
                    db.commit()
                    deferred_count = len(relevant) - i
                    logger.info(
                        "Social: deferred %d posts — budget left %d < cost %d",
                        deferred_count, token_budget, cost,
                    )
                    break

                batch_signals = await self._process_batch(db, batch)
                token_budget -= cost

                for p in batch:
                    db.query(SocialPost).filter(SocialPost.id == p.id).update({
                        "processed": True,
                        "processed_at": datetime.now(timezone.utc),
                    })
                db.commit()
                signals_created += batch_signals

            logger.info(
                "Social: %d signals, %d deferred, budget left %d tokens",
                signals_created, deferred_count, token_budget,
            )
            return signals_created
        finally:
            db.close()

    async def _process_batch(
        self, db: Any, batch: list[SocialPost],
    ) -> int:
        if not batch:
            return 0

        posts_data: list[dict[str, object]] = [
            {
                "index": idx,
                "author": str(p.author_nick),
                "text": _post_text(p)[:800],
                "tickers": _post_tickers(p),
            }
            for idx, p in enumerate(batch)
        ]
        prompt = BATCH_ANALYSIS_PROMPT.format(posts_json=json.dumps(posts_data, ensure_ascii=False))

        try:
            raw = await llm.analyze_social(prompt)
        except Exception as e:
            err_str = str(e)
            if "rate_limit_exceeded" in err_str or "429" in err_str:
                logger.warning("Groq rate limit hit — stopping batch processing")
                raise
            logger.error("LLM batch analysis failed: %s", e)
            return 0

        results = self._parse_llm_response(raw)
        if not results and raw.strip() and raw.strip() != "[]":
            logger.warning("LLM returned unparseable JSON for batch of %d posts", len(batch))
            return 0

        signals_created = 0
        for res in results:
            post_idx = res.get("post_index")
            if post_idx is None or post_idx >= len(batch):
                continue
            post = batch[post_idx]
            ticker = res.get("ticker") or None
            confidence = float(res.get("confidence", 0))
            if confidence <= 0:
                continue
            sig = SentimentSignal(
                post_id=post.id,
                ticker=ticker,
                bullish_score=float(res.get("bullish", res.get("bullish_score", 0))),
                bearish_score=float(res.get("bearish", res.get("bearish_score", 0))),
                confidence=confidence,
                llm_reasoning=res.get("reason", res.get("reasoning", "")),
                source_weight=1.0,
            )
            sig.composite_score = round((sig.bullish_score - sig.bearish_score) * sig.confidence, 4)
            db.add(sig)
            signals_created += 1
        return signals_created

    @staticmethod
    def _parse_llm_response(raw: str) -> list[dict[str, Any]]:
        if not raw or raw.strip() in ("[]", ""):
            return []
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[-1]
            cleaned = cleaned.rsplit("```", 1)[0]
        start = cleaned.find("[")
        end = cleaned.rfind("]")
        if start != -1 and end != -1 and end > start:
            cleaned = cleaned[start : end + 1]
        if not cleaned:
            return []
        # Attempt full parse first
        try:
            data = json.loads(cleaned)
            if isinstance(data, list):
                return data
        except json.JSONDecodeError:
            pass
        # Fallback: try to extract partial objects with lenient parsing
        try:
            partials: list[dict[str, Any]] = []
            decoder = json.JSONDecoder()
            pos = 0
            while pos < len(cleaned):
                pos = cleaned.find("{", pos)
                if pos == -1:
                    break
                try:
                    obj, idx = decoder.raw_decode(cleaned, pos)
                    if isinstance(obj, dict):
                        partials.append(obj)
                    pos = idx
                except json.JSONDecodeError:
                    pos += 1
            if partials:
                return partials
        except Exception:
            pass
        logger.warning("Failed to parse LLM JSON (len=%d): %s...", len(raw), raw[:150])
        return []


analyzer = SocialSentimentAnalyzer()
