from src.compliance import DISCLAIMER, with_disclaimer


class TestWithDisclaimer:
    def test_adds_disclaimer(self):
        text = "BUY SBER 100 shares"
        result = with_disclaimer(text)
        assert DISCLAIMER in result
        assert text in result

    def test_does_not_duplicate_disclaimer(self):
        text = f"BUY SBER{chr(10)}{chr(10)}{DISCLAIMER}"
        result = with_disclaimer(text)
        assert result.count(DISCLAIMER) == 1

    def test_empty_text(self):
        result = with_disclaimer("")
        assert DISCLAIMER in result

    def test_disclaimer_length_and_structure(self):
        assert len(DISCLAIMER) > 50
        assert DISCLAIMER.startswith("\u26a0")
