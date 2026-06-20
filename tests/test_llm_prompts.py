import json

import pytest


class TestBuildUserMessage:
    def test_build_user_message_includes_signal_json(self):
        from src.llm.prompts import build_user_message

        signal = {"ticker": "SBER", "action": "BUY", "confidence": 0.85}
        result = build_user_message(signal)
        assert "SBER" in result
        assert "BUY" in result
        assert "0.85" in result

    def test_build_user_message_with_unicode(self):
        from src.llm.prompts import build_user_message

        signal = {"ticker": "GAZP", "reason": "рост цен на газ"}
        result = build_user_message(signal)
        assert "GAZP" in result
        assert json.dumps(signal, ensure_ascii=False, indent=2) in result

    def test_system_prompt_exists(self):
        from src.llm.prompts import SYSTEM_PROMPT

        assert len(SYSTEM_PROMPT) > 50
        assert "FinAdvisor" in SYSTEM_PROMPT

    def test_user_template_exists(self):
        from src.llm.prompts import USER_TEMPLATE

        assert "{signal_json}" in USER_TEMPLATE
