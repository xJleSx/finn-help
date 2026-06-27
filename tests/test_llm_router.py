from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

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


class TestOllamaAdvise:
    @pytest.mark.asyncio
    async def test_ollama_success(self):
        router = LLMRouter()
        signal = {"action": "SELL", "confidence": 0.7, "ticker": "GAZP", "reasons": [], "max_portfolio_pct": 5}

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"message": {"content": "Ollama answer"}}

        inner_client = AsyncMock()
        inner_client.post.return_value = mock_response
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = inner_client

        with (
            patch("httpx.AsyncClient", return_value=mock_client),
            patch("src.llm.router.prompts") as mock_prompts,
        ):
            mock_prompts.SYSTEM_PROMPT = ""
            mock_prompts.build_user_message.return_value = ""
            result = await router._ollama_advise(signal)
            assert result == "Ollama answer"

    @pytest.mark.asyncio
    async def test_ollama_failure_returns_fallback(self):
        router = LLMRouter()
        signal = {"action": "BUY", "confidence": 0.6, "ticker": "SBER", "reasons": ["test"], "max_portfolio_pct": 10}

        inner_client = AsyncMock()
        inner_client.post.side_effect = Exception("HTTP error")
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = inner_client

        with (
            patch("httpx.AsyncClient", return_value=mock_client),
            patch("src.llm.router.prompts") as mock_prompts,
        ):
            mock_prompts.SYSTEM_PROMPT = ""
            mock_prompts.build_user_message.return_value = ""
            result = await router._ollama_advise(signal)
            assert "SBER" in result or "BUY" in result
