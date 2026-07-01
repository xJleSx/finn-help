import json
import logging
import re
from typing import Any, cast

from src.config import settings
from src.llm import prompts
from src.llm.rate_limiter import throttled_groq_call
from src.llm.tools.wolfram import WolframAlphaClient

logger = logging.getLogger(__name__)

LLM_TEMPERATURE = 0.15


class LLMRouter:
    def __init__(self) -> None:
        self._use_groq = bool(settings.groq_api_key)
        self._groq_model = settings.groq_model
        self._ollama_model = settings.ollama_model
        self._ollama_url = settings.ollama_url
        self._wolfram: WolframAlphaClient | None = (
            WolframAlphaClient(settings.wolfram_app_id)
            if settings.wolfram_enabled and settings.wolfram_app_id
            else None
        )

    async def advise(self, signal: dict[str, object], user_id: str | int | None = None) -> str:
        self._enrich_with_risk_profile(signal, user_id=user_id)
        await self._enrich_with_wolfram(signal)
        self._enrich_with_enriched_context(signal)

        if self._use_groq:
            try:
                raw = await self._groq_advise(signal)
                return self._process_output(raw, signal)
            except Exception as e:
                logger.warning(f"Groq failed: {e}, trying local...")

        raw = await self._ollama_advise(signal)
        return self._process_output(raw, signal)

    async def report(self, signal: dict[str, object], user_id: str | int | None = None) -> str:
        self._enrich_with_risk_profile(signal, user_id=user_id)
        await self._enrich_with_wolfram(signal)
        self._enrich_with_enriched_context(signal)

        if self._use_groq:
            try:
                raw = await self._groq_report(signal)
                return self._process_report(raw, signal)
            except Exception as e:
                logger.warning(f"Groq report failed: {e}, trying local...")

        raw = await self._ollama_report(signal)
        return self._process_report(raw, signal)

    def _enrich_with_risk_profile(self, signal: dict[str, object], user_id: str | int | None = None) -> None:
        try:
            from src.user_profile import profile_manager

            if user_id is not None:
                profile = profile_manager.get(str(user_id))
                signal["risk_profile"] = profile.risk_profile
                return

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

    def _enrich_with_enriched_context(self, signal: dict[str, object]) -> None:
        ticker = signal.get("ticker")
        if not ticker or not isinstance(ticker, str):
            return
        try:
            from src.db.connection import get_session
            from src.db.models import Instrument
            from src.interfaces.response_formatter import build_enriched_context_block

            db = get_session()
            try:
                inst = db.query(Instrument).filter_by(ticker=ticker.upper()).first()
                if inst:
                    ctx = build_enriched_context_block(db, inst)
                    if ctx:
                        signal["enriched_context"] = ctx
            finally:
                db.close()
        except Exception:
            pass

    def _profile_label(self, user_id: str | int | None = None) -> str:
        try:
            from src.user_profile import profile_manager

            if user_id is not None:
                return profile_manager.get(str(user_id)).risk_profile
        except Exception:
            pass
        return "balanced"

    def _market_context_block(self, db: Any = None) -> str:
        try:
            if db is None:
                from src.db.connection import get_session

                db = get_session()
                should_close = True
            else:
                should_close = False

            lines = []
            from src.collectors.macro import MacroCollector

            macro = MacroCollector.latest_values(db)
            if macro:
                parts = []
                for k, v in macro.items():
                    if v is not None:
                        parts.append(f"{k}={v}")
                lines.append(f"Макро: {', '.join(parts)}")

            # Alt data context block
            alt_lines = []
            from datetime import date, timedelta

            from sqlalchemy import func

            from src.db.models import AltDataPoint

            alt_rows = (
                db.query(AltDataPoint)
                .filter(AltDataPoint.date >= date.today() - timedelta(days=7))
                .order_by(AltDataPoint.date.desc())
                .all()
            )
            if alt_rows:
                seen: set[str] = set()
                for r in alt_rows:
                    key = f"{r.source_name}/{r.indicator_name}"
                    if key not in seen:
                        alt_lines.append(f"{r.indicator_name}={r.value:.2f}")
                        seen.add(key)
                if alt_lines:
                    lines.append(f"Альт. данные: {', '.join(alt_lines)}")

            from datetime import date

            from src.db.models import Instrument, Price
            from src.db.models import Signal as SignalModel

            today_signals = (
                db.query(SignalModel)
                .filter(func.date(SignalModel.date) == date.today())
                .order_by(SignalModel.confidence.desc())
                .limit(10)
                .all()
            )
            if today_signals:
                top = []
                for s in today_signals:
                    inst = db.query(Instrument).filter_by(id=s.instrument_id).first()
                    ticker = inst.ticker if inst else "?"
                    top.append(f"{ticker}: {s.action} ({s.confidence:.0%})")
                lines.append(f"Топ-сигналы сегодня: {'; '.join(top)}")

            bmk = (
                db.query(Price)
                .join(Instrument)
                .filter(Instrument.ticker == "IMOEX")
                .order_by(Price.date.desc())
                .first()
            )
            if bmk:
                lines.append(f"IMOEX: {bmk.close:.0f}")

            result = "\n".join(lines)
            if should_close:
                db.close()
            return result
        except Exception as e:
            logger.debug("market_context_block failed: %s", e)
            return ""

    async def answer_question(
        self,
        question: str,
        user_id: str | int | None = None,
        ticker_context: str = "",
    ) -> str:
        profile = self._profile_label(user_id)

        from src.db.connection import get_session

        db = get_session()
        try:
            # Auto-detect ticker in question if no ticker_context provided
            if not ticker_context:
                found_ticker = self._detect_ticker(db, question)
                if found_ticker:
                    from src.analysis.service import analysis_service

                    ticker_context = analysis_service.load_ticker_context(db, found_ticker)

            market_ctx = self._market_context_block(db)
        finally:
            db.close()

        system_prompt = prompts.QUESTION_SYSTEM_PROMPT.format(profile=profile)
        user_prompt = prompts.build_question_message(
            question=question,
            profile=profile,
            market_context=market_ctx,
            ticker_context=ticker_context,
        )

        if self._use_groq:
            try:
                return await self._groq_question(system_prompt, user_prompt)
            except Exception as e:
                logger.warning(f"Groq question failed: {e}, trying local...")

        return await self._ollama_question(system_prompt, user_prompt)

    @staticmethod
    def _detect_ticker(db: Any, text: str) -> str | None:
        """Extract likely MOEX ticker from question text."""
        from src.db.models import Instrument

        candidates = re.findall(r"\b[A-Z]{4,5}\b", text.upper())
        # Filter against known instruments in DB
        known = set()
        for row in db.query(Instrument.ticker).all():
            known.add(row[0].upper() if row[0] else "")
        for c in candidates:
            if c in known:
                return cast(str, c)
        return None

    async def _groq_call(
        self,
        messages: list[dict[str, str]],
        model: str,
        temperature: float,
        max_tokens: int,
    ) -> str:
        from groq import AsyncGroq

        async def _do_call() -> str:
            client = AsyncGroq(api_key=settings.groq_api_key)
            response = await client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            return response.choices[0].message.content or ""

        return await throttled_groq_call(_do_call)

    async def _ollama_call(
        self,
        messages: list[dict[str, str]],
        model: str,
        temperature: float,
        max_tokens: int,
        timeout: float = 120.0,
    ) -> str:
        import httpx

        async with httpx.AsyncClient(timeout=timeout) as client:
            payload = {
                "model": model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "stream": False,
            }
            resp = await client.post(f"{self._ollama_url}/api/chat", json=payload)
            resp.raise_for_status()
            data: Any = resp.json()
            return cast(str, data.get("message", {}).get("content", ""))

    async def _call(
        self,
        system: str,
        user: str,
        backend: str,
        temperature: float = LLM_TEMPERATURE,
        max_tokens: int = 768,
        timeout: float = 60.0,
        model: str | None = None,
    ) -> str:
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
        if backend == "groq":
            return await self._groq_call(
                messages=messages,
                model=model or self._groq_model,
                temperature=temperature,
                max_tokens=max_tokens,
            )
        return await self._ollama_call(
            messages=messages,
            model=model or self._ollama_model,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=timeout,
        )

    async def _groq_question(self, system: str, user: str) -> str:
        return await self._call(system, user, backend="groq", temperature=0.3, max_tokens=1024)

    async def _ollama_question(self, system: str, user: str) -> str:
        return await self._call(system, user, backend="ollama", temperature=0.3, max_tokens=1024)

    async def _groq_advise(self, signal: dict[str, object]) -> str:
        try:
            result = await self._call(
                prompts.SYSTEM_PROMPT, prompts.build_user_message(signal),
                backend="groq", temperature=LLM_TEMPERATURE, max_tokens=768,
            )
            return result or self._fallback_text(signal)
        except ImportError:
            logger.warning("groq package not installed")
            return self._fallback_text(signal)

    async def _ollama_advise(self, signal: dict[str, object]) -> str:
        try:
            result = await self._call(
                prompts.SYSTEM_PROMPT, prompts.build_user_message(signal),
                backend="ollama", temperature=LLM_TEMPERATURE, max_tokens=768, timeout=60.0,
            )
            return result or self._fallback_text(signal)
        except Exception as e:
            logger.warning(f"ollama failed: {e}")
            return self._fallback_text(signal)

    async def _groq_report(self, signal: dict[str, object]) -> str:
        try:
            result = await self._call(
                prompts.REPORT_SYSTEM_PROMPT, prompts.build_report_message(signal),
                backend="groq", temperature=0.2, max_tokens=1024,
            )
            return result or self._fallback_report(signal)
        except ImportError:
            logger.warning("groq package not installed")
            return self._fallback_report(signal)

    async def _ollama_report(self, signal: dict[str, object]) -> str:
        try:
            result = await self._call(
                prompts.REPORT_SYSTEM_PROMPT, prompts.build_report_message(signal),
                backend="ollama", temperature=0.2, max_tokens=1024, timeout=60.0,
            )
            return result or self._fallback_report(signal)
        except Exception as e:
            logger.warning(f"ollama report failed: {e}")
            return self._fallback_report(signal)

    def _process_report(self, raw: str, signal: dict[str, object]) -> str:
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
            cleaned = re.sub(r"\s*```$", "", cleaned)
        try:
            parsed = json.loads(cleaned)
            return self._render_report(parsed)
        except (json.JSONDecodeError, ValueError):
            logger.debug("LLM report output not valid JSON, using fallback: %.100s", raw)
            return self._fallback_report(signal)

    def _render_report(self, parsed: dict[str, Any]) -> str:
        lines: list[str] = []
        company_profile = parsed.get("company_profile", "")
        financial_highlights = parsed.get("financial_highlights", [])
        offering = parsed.get("offering_analysis", {})
        strengths = parsed.get("strengths", [])
        weaknesses = parsed.get("weaknesses", [])
        verdict = parsed.get("verdict", "")
        rating = parsed.get("rating")
        rating_explain = parsed.get("rating_explain", "")
        action = parsed.get("action", "")
        portfolio_advice = parsed.get("portfolio_advice", "")

        if company_profile:
            lines.append("## Компания")
            lines.append(company_profile)
            lines.append("")

        if financial_highlights:
            lines.append("## Финансовые показатели")
            for h in financial_highlights:
                lines.append(f"  {h}")
            lines.append("")

        if offering:
            desc = offering.get("description", "")
            params = offering.get("parameters", [])
            pros = offering.get("pros", [])
            cons = offering.get("cons", [])
            if desc:
                lines.append("## Анализ предложения")
                lines.append(desc)
                lines.append("")
            if params:
                for p in params:
                    lines.append(f"  {p}")
                lines.append("")
            if pros:
                lines.append("  Преимущества:")
                for p in pros:
                    lines.append(f"    + {p}")
                lines.append("")
            if cons:
                lines.append("  Недостатки:")
                for c in cons:
                    lines.append(f"    - {c}")
                lines.append("")

        if strengths:
            lines.append("## Сильные стороны")
            for s in strengths:
                lines.append(f"  + {s}")
            lines.append("")

        if weaknesses:
            lines.append("## Слабые стороны / Риски")
            for w in weaknesses:
                lines.append(f"  - {w}")
            lines.append("")

        if verdict:
            lines.append("## Вердикт")
            lines.append(verdict)
            lines.append("")

        if rating is not None:
            stars = "★" * rating + "☆" * (5 - rating)
            lines.append(f"Оценка: {stars} ({rating}/5)")
            if rating_explain:
                lines.append(f"  {rating_explain}")
            lines.append("")

        if portfolio_advice or action:
            if action:
                action_labels = {
                    "BUY": "К покупке",
                    "SELL": "К продаже",
                    "HOLD": "Держать",
                    "CAUTIOUS_BUY": "Осторожная покупка",
                    "WATCH": "Наблюдение",
                }
                label = action_labels.get(action, action)
                lines.append(f"Рекомендация: {label}")
            if portfolio_advice:
                lines.append(f"  {portfolio_advice}")

        return "\n".join(lines) if lines else (verdict or "Нет данных для формирования отчёта")

    def _fallback_report(self, signal: dict[str, object]) -> str:
        ticker: Any = signal.get("ticker", "?")
        action: Any = signal.get("action", "NEUTRAL")
        confidence: Any = signal.get("confidence", 0)
        reasons: Any = signal.get("reasons", [])

        lines = [f"Отчёт по {ticker}"]
        lines.append("")
        lines.append("Данных для полноценного обзора недостаточно. Основные выводы по сигналу:")
        lines.append(f"Действие: {action} (уверенность {confidence:.0%})")
        for r in reasons[:5]:
            lines.append(f"  {r}")
        return "\n".join(lines)

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

    def _render_json(self, parsed: dict[str, Any]) -> str:
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

        components = signal.get("components", {})
        ml = components.get("ml", {}) if isinstance(components, dict) else {}
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
        result = await self._call(
            "Отвечай JSON-массивом. Компактно.", prompt,
            backend="groq", model=settings.social_groq_model,
            temperature=0.05, max_tokens=2048,
        )
        return result or "[]"

    async def _ollama_social(self, prompt: str) -> str:
        result = await self._call(
            "Отвечай JSON-массивом. Компактно.", prompt,
            backend="ollama", temperature=0.05, max_tokens=2048, timeout=300.0,
        )
        return result or "[]"


llm: LLMRouter = LLMRouter()
