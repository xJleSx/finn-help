from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.social.sentiment.analyzer import SocialSentimentAnalyzer, _get_source_weight, _is_finance_post


def test_is_finance_post_with_tickers():
    assert _is_finance_post("some text", ["SBER"])


def test_is_finance_post_with_keyword():
    assert _is_finance_post("акции растут", [])


def test_is_finance_post_no_match():
    assert not _is_finance_post("погода сегодня", [])


def test_source_weight_default():
    w = _get_source_weight("unknown_source")
    assert w == 0.5


def test_source_weight_custom():
    with patch("src.social.sentiment.analyzer.personal", {"social_sources": {"vk": {"weight": 0.8}}}):
        w = _get_source_weight("vk")
        assert w == 0.8


def test_process_batch_empty(analyzer):
    assert analyzer._process_batch(MagicMock(), []) == 0


@pytest.mark.asyncio
async def test_process_batch_llm_empty(analyzer):
    assert await analyzer._process_batch_llm(MagicMock(), []) == 0


@pytest.fixture
def analyzer():
    with patch("src.social.sentiment.analyzer.settings") as ms:
        ms.llm_social_enabled = False
        ms.groq_api_key = ""
        yield SocialSentimentAnalyzer()


def test_init_no_llm():
    with patch("src.social.sentiment.analyzer.settings") as ms:
        ms.llm_social_enabled = False
        ms.groq_api_key = ""
        a = SocialSentimentAnalyzer()
        assert a._use_llm is False


def test_init_with_llm():
    with patch("src.social.sentiment.analyzer.settings") as ms:
        ms.llm_social_enabled = True
        ms.groq_api_key = "sk-xxx"
        a = SocialSentimentAnalyzer()
        assert a._use_llm is True


@patch("src.social.sentiment.analyzer.get_session")
def test_process_new_posts_no_relevant(mock_get_session, analyzer):
    mock_db = MagicMock()
    mock_db.query.return_value.filter.return_value.order_by.return_value.all.return_value = []
    mock_get_session.return_value = mock_db
    import asyncio
    result = asyncio.run(analyzer.process_new_posts())
    assert result == 0
