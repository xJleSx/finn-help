from __future__ import annotations

from unittest.mock import patch

import pytest

from src.llm.router import LLMRouter


class TestFallbackText:
    def setup_method(self):
        self.router = LLMRouter()

    def test_basic_fallback(self):
        signal = {
            "action": "BUY",
            "confidence": 0.85,
            "ticker": "SBER",
            "reasons": ["Strong fundamentals", "Technical breakout"],
            "max_portfolio_pct": 15,
        }
        text = self.router._fallback_text(signal)
        assert "BUY" in text
        assert "SBER" in text
        assert "15%" in text


class TestGroqAdvise:
    @pytest.mark.asyncio
    async def test_import_error_returns_fallback(self):
        router = LLMRouter()
        signal = {"action": "HOLD", "confidence": 0.5, "ticker": "T", "reasons": [], "max_portfolio_pct": 10}

        with (
            patch.dict("sys.modules", {"groq": None}),
            patch("src.llm.router.prompts") as mock_prompts,
        ):
            mock_prompts.SYSTEM_PROMPT = ""
            mock_prompts.build_user_message.return_value = ""

            result = await router._groq_advise(signal)
            assert "HOLD" in result or "T" in result
