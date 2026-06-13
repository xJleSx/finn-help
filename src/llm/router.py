import json
import logging
from typing import Optional

from src.config import settings
from src.llm import prompts

logger = logging.getLogger(__name__)


class LLMRouter:
    def __init__(self):
        self._groq_client: Optional = None
        self._use_groq = bool(settings.groq_api_key)

    async def advise(self, signal: dict) -> str:
        if self._use_groq:
            try:
                return await self._groq_advise(signal)
            except Exception as e:
                logger.warning(f"Groq failed: {e}, trying local...")

        return await self._ollama_advise(signal)

    async def _groq_advise(self, signal: dict) -> str:
        try:
            from groq import AsyncGroq

            client = AsyncGroq(api_key=settings.groq_api_key)
            response = await client.chat.completions.create(
                model="llama3-70b-8192",
                messages=[
                    {"role": "system", "content": prompts.SYSTEM_PROMPT},
                    {"role": "user", "content": prompts.build_user_message(signal)},
                ],
                temperature=0.3,
                max_tokens=512,
            )
            return response.choices[0].message.content or self._fallback_text(signal)
        except ImportError:
            logger.warning("groq package not installed")
            return self._fallback_text(signal)

    async def _ollama_advise(self, signal: dict) -> str:
        try:
            import httpx

            async with httpx.AsyncClient(timeout=60.0) as client:
                payload = {
                    "model": "qwen2.5:7b",
                    "messages": [
                        {"role": "system", "content": prompts.SYSTEM_PROMPT},
                        {"role": "user", "content": prompts.build_user_message(signal)},
                    ],
                    "temperature": 0.3,
                    "max_tokens": 512,
                    "stream": False,
                }
                resp = await client.post("http://localhost:11434/api/chat", json=payload)
                resp.raise_for_status()
                data = resp.json()
                return data.get("message", {}).get("content", self._fallback_text(signal))
        except Exception as e:
            logger.warning(f"ollama failed: {e}")
            return self._fallback_text(signal)

    def _fallback_text(self, signal: dict) -> str:
        action = signal.get("action", "NEUTRAL")
        confidence = signal.get("confidence", 0)
        ticker = signal.get("ticker", "?")
        reasons = signal.get("reasons", [])
        max_pct = signal.get("max_portfolio_pct", 10)

        text = f"📊 {ticker} — {action} (уверенность: {confidence:.0%})\n"
        for r in reasons:
            text += f"• {r}\n"
        text += f"\n💡 Рекомендуемая доля в портфеле: до {max_pct}%"
        return text


llm = LLMRouter()
