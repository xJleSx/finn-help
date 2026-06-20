import logging
from typing import Any, cast

from src.config import settings
from src.llm import prompts

logger = logging.getLogger(__name__)


class LLMRouter:
    def __init__(self) -> None:
        self._groq_client: object | None = None
        self._use_groq = bool(settings.groq_api_key)
        self._groq_model = settings.groq_model
        self._ollama_model = settings.ollama_model
        self._ollama_url = settings.ollama_url

    async def advise(self, signal: dict[str, object]) -> str:
        if self._use_groq:
            try:
                return await self._groq_advise(signal)
            except Exception as e:
                logger.warning(f"Groq failed: {e}, trying local...")

        return await self._ollama_advise(signal)

    async def _groq_advise(self, signal: dict[str, object]) -> str:
        try:
            from groq import AsyncGroq

            client = AsyncGroq(api_key=settings.groq_api_key)
            response = await client.chat.completions.create(
                model=self._groq_model,
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

    async def _ollama_advise(self, signal: dict[str, object]) -> str:
        try:
            import httpx

            async with httpx.AsyncClient(timeout=60.0) as client:
                payload = {
                    "model": self._ollama_model,
                    "messages": [
                        {"role": "system", "content": prompts.SYSTEM_PROMPT},
                        {"role": "user", "content": prompts.build_user_message(signal)},
                    ],
                    "temperature": 0.3,
                    "max_tokens": 512,
                    "stream": False,
                }
                resp = await client.post(f"{self._ollama_url}/api/chat", json=payload)
                resp.raise_for_status()
                data: Any = resp.json()
                result: Any = data.get("message", {}).get("content", self._fallback_text(signal))
                return cast(str, result)
        except Exception as e:
            logger.warning(f"ollama failed: {e}")
            return self._fallback_text(signal)

    async def analyze_social(self, prompt: str) -> str:
        if self._use_groq:
            try:
                return await self._groq_social(prompt)
            except Exception as e:
                logger.warning("Groq social failed: %s, trying local", e)
        return await self._ollama_social(prompt)

    async def _groq_social(self, prompt: str) -> str:
        from groq import AsyncGroq

        client = AsyncGroq(api_key=settings.groq_api_key)
        output_limit = 2048
        response = await client.chat.completions.create(
            model=settings.social_groq_model,
            messages=[
                {"role": "system", "content": "Отвечай JSON-массивом. Компактно."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.05,
            max_tokens=output_limit,
        )
        return response.choices[0].message.content or "[]"

    async def _ollama_social(self, prompt: str) -> str:
        import httpx

        async with httpx.AsyncClient(timeout=300.0) as client:
            payload = {
                "model": self._ollama_model,
                "messages": [
                    {"role": "system", "content": "Отвечай JSON-массивом. Компактно."},
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0.05,
                "max_tokens": 2048,
                "stream": False,
            }
            resp = await client.post(f"{self._ollama_url}/api/chat", json=payload)
            resp.raise_for_status()
            data = resp.json()
            result: str = data.get("message", {}).get("content", "[]")
            return result

    def _fallback_text(self, signal: dict[str, object]) -> str:
        action: Any = signal.get("action", "NEUTRAL")
        confidence: Any = signal.get("confidence", 0)
        ticker: Any = signal.get("ticker", "?")
        reasons: Any = signal.get("reasons", [])
        max_pct: Any = signal.get("max_portfolio_pct", 10)

        text = f"📊 {ticker} — {action} (уверенность: {confidence:.0%})\n"
        for r in reasons:
            text += f"• {r}\n"
        text += f"\n💡 Рекомендуемая доля в портфеле: до {max_pct}%"
        return text


llm: LLMRouter = LLMRouter()
