import json
import logging
import re
from typing import Any, cast

from src.config import settings
from src.llm import prompts
from src.llm.tools.wolfram import WolframAlphaClient

logger = logging.getLogger(__name__)

LLM_TEMPERATURE = 0.15


class LLMRouter:
    def __init__(self) -> None:
        self._groq_client: object | None = None
        self._use_groq = bool(settings.groq_api_key)
        self._groq_model = settings.groq_model
        self._ollama_model = settings.ollama_model
        self._ollama_url = settings.ollama_url
        self._wolfram: WolframAlphaClient | None = (
            WolframAlphaClient(settings.wolfram_app_id)
            if settings.wolfram_enabled and settings.wolfram_app_id
            else None
        )

    async def advise(self, signal: dict[str, object]) -> str:
        self._enrich_with_risk_profile(signal)
        await self._enrich_with_wolfram(signal)

        if self._use_groq:
            try:
                raw = await self._groq_advise(signal)
                return self._process_output(raw, signal)
            except Exception as e:
                logger.warning(f"Groq failed: {e}, trying local...")

        raw = await self._ollama_advise(signal)
        return self._process_output(raw, signal)

    def _enrich_with_risk_profile(self, signal: dict[str, object]) -> None:
        try:
            from src.db.connection import get_session
            from src.db.models import UserSetting

            db = get_session()
            try:
                row = db.query(UserSetting).filter_by(key="risk_profile").first()
                if row and row.value in ("conservative", "balanced", "aggressive"):
                    signal["risk_profile"] = row.value
            finally:
                db.close()
        except Exception:
            pass

    async def _enrich_with_wolfram(self, signal: dict[str, object]) -> None:
        if not self._wolfram:
            return
        ticker = signal.get("ticker")
        if not ticker or not isinstance(ticker, str):
            return
        try:
            data = await self._wolfram.enrich_stock(ticker)
            if data:
                signal["wolfram_data"] = data
                logger.debug("WolframAlpha enriched %s: %d facts", ticker, len(data))
        except Exception as e:
            logger.warning("WolframAlpha enrichment failed for %s: %s", ticker, e)

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
                temperature=LLM_TEMPERATURE,
                max_tokens=768,
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
                    "temperature": LLM_TEMPERATURE,
                    "max_tokens": 768,
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

    def _process_output(self, raw: str, signal: dict[str, object]) -> str:
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
            cleaned = re.sub(r"\s*```$", "", cleaned)
        try:
            parsed = json.loads(cleaned)
            return self._render_json(parsed)
        except (json.JSONDecodeError, ValueError):
            logger.debug("LLM output not valid JSON, using as-is: %.100s", raw)
            return self._validate_text(raw, signal)

    def _render_json(self, parsed: dict) -> str:
        summary = parsed.get("summary", "")
        key_facts = parsed.get("key_facts", [])
        risks = parsed.get("risks", [])
        action = parsed.get("action", "")
        confidence_explain = parsed.get("confidence_explain", "")
        portfolio_advice = parsed.get("portfolio_advice", "")

        lines: list[str] = []
        action_emojis = {"BUY": "🟢", "CAUTIOUS_BUY": "🟡", "HOLD": "⚪", "SELL": "🔴", "NEUTRAL": "⚪"}
        emoji = action_emojis.get(action, "⚪")

        if action:
            lines.append(f"{emoji} *Действие:* {action}")
        if confidence_explain:
            lines.append(f"💬 {confidence_explain}")
        if summary:
            lines.append("")
            lines.append(summary)
        if key_facts:
            lines.append("")
            lines.append("📌 *Ключевые факты:*")
            for f in key_facts:
                lines.append(f"• {f}")
        if risks:
            lines.append("")
            lines.append("⚠️ *Риски:*")
            for r in risks:
                lines.append(f"• {r}")
        if portfolio_advice:
            lines.append("")
            lines.append(f"💡 *Совет:* {portfolio_advice}")

        price_markers = parsed.get("price_markers")
        if price_markers and isinstance(price_markers, dict):
            lines.append("")
            lines.append("🎯 *Ценовые маркеры:*")
            cur = price_markers.get("current_price")
            if cur:
                lines.append(f"💰 Текущая цена: {cur:.2f} ₽")
            entry = price_markers.get("entry_zone")
            if entry:
                lines.append(f"📥 Зона входа: {entry if isinstance(entry, str) else entry:.2f} ₽")
            targets = price_markers.get("targets")
            if targets and isinstance(targets, list):
                for i, t in enumerate(targets, 1):
                    lines.append(f"🎯 Цель {i}: {t:.2f} ₽")
            sl = price_markers.get("stop_loss")
            if sl:
                lines.append(f"🛑 Стоп-лосс: {sl:.2f} ₽")
            trigger = price_markers.get("trigger", "")
            if trigger == "entry":
                lines.append("🚨 *Триггер: ПОРА ВХОДИТЬ!*")
            elif trigger == "take_profit":
                lines.append("💰 *Триггер: ФИКСИРУЙ ПРИБЫЛЬ!*")
            elif trigger == "stop_loss":
                lines.append("🔴 *Триггер: ВЫХОДИ ИЗ ПОЗИЦИИ!*")

        return "\n".join(lines) if lines else summary

    def _validate_text(self, text: str, signal: dict[str, object]) -> str:
        action: Any = signal.get("action", "NEUTRAL")
        confidence: Any = signal.get("confidence", 0)
        ticker: Any = signal.get("ticker", "?")
        max_pct: Any = signal.get("max_portfolio_pct", 10)

        text_lower = text.lower()

        if ticker and isinstance(ticker, str) and ticker.lower() not in text_lower:
            logger.debug("LLM response missing ticker mention, wrapping")
            header = f"📊 *{ticker}* — {action} (уверенность: {confidence:.0%})\n\n"
            footer = f"\n\n💡 Рекомендуемая доля в портфеле: до {max_pct}%"
            text = header + text + footer

        return text

    def _fallback_text(self, signal: dict[str, object]) -> str:
        action: Any = signal.get("action", "NEUTRAL")
        confidence: Any = signal.get("confidence", 0)
        ticker: Any = signal.get("ticker", "?")
        reasons: Any = signal.get("reasons", [])
        max_pct: Any = signal.get("max_portfolio_pct", 10)

        action_emoji_map = {"BUY": "🟢", "CAUTIOUS_BUY": "🟡", "HOLD": "⚪", "SELL": "🔴", "NEUTRAL": "⚪"}
        emoji = action_emoji_map.get(action, "⚪")

        text = f"{emoji} *{ticker}* — {action} (уверенность: {confidence:.0%})\n"
        for r in reasons:
            text += f"• {r}\n"
        text += f"\n💡 Рекомендуемая доля в портфеле: до {max_pct}%"

        ml = signal.get("components", {}).get("ml", {}) if isinstance(signal.get("components"), dict) else {}
        if ml and isinstance(ml, dict):
            ml_change = ml.get("change_pct")
            ml_tp = ml.get("target_price")
            if ml_change is not None:
                text += f"\n\n🤖 *ML-прогноз:* {'+' if ml_change and ml_change > 0 else ''}{ml_change:.1f}%"
                if ml_tp:
                    text += f" (цель {ml_tp:.0f} ₽)"

        return text

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


llm: LLMRouter = LLMRouter()
