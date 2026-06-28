from __future__ import annotations

import asyncio
import hashlib
import logging
import re
from datetime import timezone
from typing import Any

logger = logging.getLogger(__name__)

MOEX_TICKERS: set[str] = {
    "SBER", "GAZP", "LKOH", "VTBR", "MOEX", "NLMK", "MGNT", "MTSS",
    "SNGS", "SNGSP", "TATN", "TATNP", "RTKM", "RTKMP", "PHOR", "AFKS",
    "YNDX", "PLZL", "CHMF", "MAGN", "ROSN", "FIVE", "ALRS", "GMKN",
    "AFLT", "IRAO", "RUAL", "TRNFP", "BANE", "BANEP", "FEES", "HYDR",
    "MRKS", "MSNG", "PIKK", "POLY", "RSTI", "SVAV", "TCSG", "TGKA",
    "TLKM", "UNKL", "UPRO", "USBN", "VSMO",
}

POSITIVE_WORDS: set[str] = {
    "рост", "прибыль", "доход", "выручка", "дивиденд", "увеличение",
    "повышение", "укрепление", "рекорд", "успех", "позитивный",
    "оптимизм", "восстановление", "buyback", "buy",
    "bullish", "outperform", "rally", "surge", "growth", "profit",
    "gain", "rise", "upgrade", "breakthrough", "recovery",
}

NEGATIVE_WORDS: set[str] = {
    "падение", "снижение", "убыток", "долг", "кризис", "санкция",
    "обвал", "крах", "дефолт", "банкротство", "инфляция",
    "рецессия", "потеря", "запрет", "эмбарго",
    "bearish", "decline", "crash", "loss", "downgrade", "drop",
    "plunge", "slump", "debt", "penalty", "restriction",
}


class SocialMediaCollector:
    def __init__(self, api_id: str, api_hash: str, session_name: str = "telegram_social") -> None:
        self.api_id = api_id
        self.api_hash = api_hash
        self.session_name = session_name
        self._last_request_time: float = 0.0
        self._min_interval: float = 0.34

    async def collect_telegram(
        self, db: Any, channel_username: str, limit: int = 50,
    ) -> list[dict[str, Any]]:
        try:
            from telethon import TelegramClient
        except ImportError:
            logger.error("telethon is not installed; run: pip install telethon")
            return []

        async with TelegramClient(self.session_name, self.api_id, self.api_hash) as client:
            try:
                entity = await client.get_entity(channel_username)
            except Exception as exc:
                logger.warning("Cannot resolve channel %s: %s", channel_username, exc)
                return []

            messages: list[dict[str, Any]] = []
            async for msg in client.iter_messages(entity, limit=limit):
                await self._rate_limit()
                if not msg.text:
                    continue
                parsed = self.parse_message(msg.text)
                messages.append({
                    "external_id": str(msg.id),
                    "text": msg.text,
                    "published_at": msg.date.replace(tzinfo=timezone.utc) if msg.date else None,
                    "tickers": parsed["tickers"],
                    "sentiment": parsed["sentiment"],
                    "sentiment_score": parsed["sentiment_score"],
                    "content_hash": hashlib.sha256(msg.text.encode("utf-8")).hexdigest(),
                })

            if not messages:
                return messages

            instrument_map = self._build_instrument_map(db)
            self.save_messages(db, messages, instrument_map)
            logger.info("Saved %d messages from %s", len(messages), channel_username)
            return messages

    async def _rate_limit(self) -> None:
        now = asyncio.get_running_loop().time()
        elapsed = now - self._last_request_time
        if elapsed < self._min_interval:
            await asyncio.sleep(self._min_interval - elapsed)
        self._last_request_time = asyncio.get_running_loop().time()

    @staticmethod
    def parse_message(message_text: str) -> dict[str, Any]:
        text_upper = message_text.upper()
        tickers = [t for t in MOEX_TICKERS if re.search(rf"\b{t}\b", text_upper)]

        text_lower = message_text.lower()
        pos_count = sum(1 for w in POSITIVE_WORDS if w in text_lower)
        neg_count = sum(1 for w in NEGATIVE_WORDS if w in text_lower)

        total = pos_count + neg_count
        if total == 0:
            sentiment: str = "neutral"
            score: float = 0.0
        elif pos_count > neg_count:
            sentiment = "positive"
            score = round(min(pos_count / total, 1.0), 3)
        elif neg_count > pos_count:
            sentiment = "negative"
            score = round(max(-neg_count / total, -1.0), 3)
        else:
            sentiment = "neutral"
            score = 0.0

        return {"tickers": tickers, "sentiment": sentiment, "sentiment_score": score}

    def save_messages(
        self, db: Any, messages: list[dict[str, Any]], instrument_map: dict[str, int],
    ) -> None:
        from src.db.models import News, NewsInstrument

        for msg in messages:
            existing = db.query(News).filter(News.content_hash == msg["content_hash"]).first()
            if existing:
                continue

            n = News(
                url=f"tg://message?id={msg['external_id']}",
                title=msg["text"][:200] if msg["text"] else "",
                summary=msg["text"][:500] if msg["text"] else None,
                content_hash=msg["content_hash"],
                sentiment_score=msg["sentiment_score"],
                source_type="telegram",
                source_count=1,
                sentiment=msg["sentiment"],
                is_relevant=True,
                published_at=msg["published_at"],
            )
            db.add(n)
            db.flush()

            for ticker in msg["tickers"]:
                inst_id = instrument_map.get(ticker.upper())
                if inst_id is None:
                    continue
                if not db.query(NewsInstrument).filter_by(news_id=n.id, instrument_id=inst_id).first():
                    db.add(NewsInstrument(news_id=n.id, instrument_id=inst_id))

            db.commit()

    @staticmethod
    def _build_instrument_map(db: Any) -> dict[str, int]:
        from src.db.models import Instrument
        return {r.ticker.upper(): r.id for r in db.query(Instrument).all()}
