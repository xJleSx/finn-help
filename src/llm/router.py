from __future__ import annotations

import hashlib
import json
import logging
import re
from typing import Any, cast

from src.config import settings
from src.core.resilience import CircuitBreakerOpenError, get_circuit_breaker
from src.llm import prompts
from src.llm.cost_tracker import get_cost_tracker
from src.llm.rate_limiter import throttled_groq_call
from src.llm.tools.wolfram import WolframAlphaClient

logger = logging.getLogger(__name__)

LLM_TEMPERATURE = 0.15
PROMPT_CACHE_MAX = 128


class LLMRouter:
    def __init__(self) -> None:
        self._use_groq = bool(settings.groq_api_key)
        self._groq_model = settings.groq_model
        self._use_ollama = bool(settings.ollama_url)
        self._ollama_model = settings.ollama_model
        self._cost_tracker = get_cost_tracker()
        self._groq_cb = get_circuit_breaker("llm_groq")
        self._ollama_cb = get_circuit_breaker("llm_ollama")
        self._prompt_cache: dict[str, str] = {}
        self._prompt_cache_order: list[str] = []
        self._wolfram: WolframAlphaClient | None = (
            WolframAlphaClient(settings.wolfram_app_id) if settings.wolfram_enabled and settings.wolfram_app_id else None
        )
        if self._use_groq and not settings.groq_api_key:
            logger.warning("GROQ_API_KEY is empty — Groq LLM calls will fail")
        if self._use_groq:
            try:
                from groq import AsyncGroq
                _test_client = AsyncGroq(api_key=settings.groq_api_key)
                logger.info("Groq API key configured for model %s", self._groq_model)
            except Exception as e:
                logger.warning("Groq client init failed: %s", e)

    async def advise(self, signal: dict[str, object], user_id: str | int | None = None) -> str:
        self._enrich_with_risk_profile(signal, user_id=user_id)
        await self._enrich_with_wolfram(signal)
        self._enrich_with_enriched_context(signal)
        raw = await self._groq_advise(signal)
        return self._process_output(raw, signal)

    async def report(self, signal: dict[str, object], user_id: str | int | None = None) -> str:
        self._enrich_with_risk_profile(signal, user_id=user_id)
        await self._enrich_with_wolfram(signal)
        self._enrich_with_enriched_context(signal)
        raw = await self._groq_report(signal)
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
        except Exception as e:
            logger.debug("Risk profile load failed: %s", e)

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
        except Exception as e:
            logger.debug("Enriched context build failed: %s", e)

    def _profile_label(self, user_id: str | int | None = None) -> str:
        try:
            from src.user_profile import profile_manager

            if user_id is not None:
                return profile_manager.get(str(user_id)).risk_profile
        except Exception as e:
            logger.debug("Profile label failed: %s", e)
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

            from datetime import date, timedelta

            from sqlalchemy import func

            from src.db.models import AltDataPoint

            alt_rows = db.query(AltDataPoint).filter(AltDataPoint.date >= date.today() - timedelta(days=7)).order_by(AltDataPoint.date.desc()).all()
            if alt_rows:
                seen: set[str] = set()
                alt_lines: list[str] = []
                for r in alt_rows:
                    key = f"{r.source_name}/{r.indicator_name}"
                    if key not in seen:
                        alt_lines.append(f"{r.indicator_name}={r.value:.2f}")
                        seen.add(key)
                if alt_lines:
                    lines.append(f"Альт. данные: {', '.join(alt_lines)}")

            from src.db.models import Instrument, Price
            from src.db.models import Signal as SignalModel

            today_signals = (
                db.query(SignalModel).filter(func.date(SignalModel.date) == date.today()).order_by(SignalModel.confidence.desc()).limit(10).all()
            )
            if today_signals:
                top = []
                for s in today_signals:
                    inst = db.query(Instrument).filter_by(id=s.instrument_id).first()
                    ticker = inst.ticker if inst else "?"
                    top.append(f"{ticker}: {s.action} ({s.confidence:.0%})")
                lines.append(f"Топ-сигналы сегодня: {'; '.join(top)}")

            bmk = db.query(Price).join(Instrument).filter(Instrument.ticker == "IMOEX").order_by(Price.date.desc()).first()
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

        return await self._call(system_prompt, user_prompt, temperature=0.3, max_tokens=1024)

    @staticmethod
    def _detect_ticker(db: Any, text: str) -> str | None:
        from src.db.models import Instrument

        candidates = re.findall(r"\b[A-Z]{4,5}\b", text.upper())
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
    ) -> str:
        import httpx

        url = f"{settings.ollama_url.rstrip('/')}/api/chat"
        payload = {
            "model": model,
            "messages": messages,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            },
            "stream": False,
        }
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            data = resp.json()
            return data.get("message", {}).get("content", "")

    async def _call(
        self,
        system: str,
        user: str,
        temperature: float = LLM_TEMPERATURE,
        max_tokens: int = 768,
        model: str | None = None,
    ) -> str:
        cache_key = hashlib.sha256((system + user + str(temperature)).encode()).hexdigest()
        cached = self._prompt_cache.get(cache_key)
        if cached is not None:
            logger.debug("Prompt cache hit (%s)", cache_key[:8])
            return cached

        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
        model = model or self._groq_model
        last_error: Exception | None = None

        if self._use_groq:
            try:
                result = await self._groq_cb.call(
                    self._groq_call,
                    messages=messages,
                    model=model,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
                if result:
                    self._cost_tracker.record(model, "groq", system + user, result)
                    self._cache_prompt(cache_key, result)
                    return result
            except CircuitBreakerOpenError:
                logger.warning("Groq circuit breaker OPEN — skipping to fallback")
                last_error = CircuitBreakerOpenError("groq")
            except Exception as e:
                logger.warning("Groq call failed, will try fallback: %s", e)
                last_error = e

        if self._use_ollama:
            try:
                result = await self._ollama_cb.call(
                    self._ollama_call,
                    messages=messages,
                    model=settings.ollama_model,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
                if result:
                    self._cost_tracker.record(settings.ollama_model, "ollama", system + user, result)
                    self._cache_prompt(cache_key, result)
                    return result
            except CircuitBreakerOpenError:
                logger.warning("Ollama circuit breaker OPEN")
                last_error = last_error or CircuitBreakerOpenError("ollama")
            except Exception as e:
                logger.warning("Ollama fallback also failed: %s", e)
                last_error = e

        if last_error:
            logger.error("All LLM providers failed: %s", last_error)
        return ""

    def _cache_prompt(self, key: str, value: str) -> None:
        if len(self._prompt_cache) >= PROMPT_CACHE_MAX:
            oldest = self._prompt_cache_order.pop(0)
            self._prompt_cache.pop(oldest, None)
        self._prompt_cache[key] = value
        self._prompt_cache_order.append(key)

    async def _groq_question(self, system: str, user: str) -> str:
        return await self._call(system, user, temperature=0.3, max_tokens=1024)

    async def _groq_advise(self, signal: dict[str, object]) -> str:
        try:
            result = await self._call(
                prompts.SYSTEM_PROMPT,
                prompts.build_user_message(signal),
                temperature=LLM_TEMPERATURE,
                max_tokens=768,
            )
            return result or self._fallback_text(signal)
        except ImportError:
            logger.warning("groq package not installed")
            return self._fallback_text(signal)

    async def _groq_report(self, signal: dict[str, object]) -> str:
        try:
            result = await self._call(
                prompts.REPORT_SYSTEM_PROMPT,
                prompts.build_report_message(signal),
                temperature=0.2,
                max_tokens=1024,
            )
            return result or self._fallback_report(signal)
        except ImportError:
            logger.warning("groq package not installed")
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
            lines.append("## Слабые стороны")
            for w in weaknesses:
                lines.append(f"  - {w}")
            lines.append("")

        if verdict:
            lines.append("## Вердикт")
            lines.append(verdict)
            lines.append("")

        if rating:
            lines.append(f"**Рейтинг:** {rating}")
        if rating_explain:
            lines.append(f"*{rating_explain}*")
            lines.append("")

        if action:
            lines.append(f"**Действие:** {action}")
        if portfolio_advice:
            lines.append(f"*Совет по портфелю:* {portfolio_advice}")

        return "\n".join(lines)

    def _fallback_text(self, signal: dict[str, object]) -> str:
        ticker = signal.get("ticker", "N/A")
        action = signal.get("action", "HOLD")
        confidence = signal.get("confidence", 0)
        max_pct = signal.get("max_portfolio_pct")
        reasons = signal.get("reasons", [])
        parts = [f"Тикер: {ticker}", f"Рекомендация: {action} (уверенность {confidence:.0%})"]
        if max_pct:
            parts.append(f"Макс. доля портфеля: {max_pct}%")
        if isinstance(reasons, list) and reasons:
            parts.append(f"Обоснование: {'; '.join(str(r) for r in reasons[:5])}")
        return ".\n".join(parts) + "."

    def _fallback_report(self, signal: dict[str, object]) -> str:
        ticker = signal.get("ticker", "N/A")
        action = signal.get("action", "HOLD")
        confidence = signal.get("confidence", 0)
        return f"## {ticker}\n**Рекомендация:** {action} (уверенность {confidence:.0%})."

    def _process_output(self, raw: str, signal: dict[str, object]) -> str:
        cleaned = raw.strip()
        if not cleaned:
            return self._fallback_text(signal)
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
            cleaned = re.sub(r"\s*```$", "", cleaned)
        return cleaned

    async def ask(self, prompt: str, system_prompt: str = "You are a helpful assistant.") -> str:
        return await self._call(system_prompt, prompt, temperature=0.1, max_tokens=64)

    async def analyze_social(self, prompt: str) -> str:
        return await self._groq_social(prompt)

    async def _groq_social(self, prompt: str) -> str:
        result = await self._call(
            "Отвечай JSON-массивом. Компактно.",
            prompt,
            model=settings.social_groq_model,
            temperature=0.05,
            max_tokens=2048,
        )
        return result or "[]"


llm: LLMRouter = LLMRouter()
