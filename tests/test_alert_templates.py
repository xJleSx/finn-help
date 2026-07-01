from __future__ import annotations

from pathlib import Path

import pytest

from src.notifications.templates.renderer import (
    AlertTemplateRenderer,
    PRIORITY_EMOJI,
    PRIORITY_COLORS,
    ACTION_EMOJI,
)


@pytest.fixture
def renderer() -> AlertTemplateRenderer:
    return AlertTemplateRenderer()


class TestRenderTelegram:
    def test_render_alert(self, renderer: AlertTemplateRenderer):
        html = renderer.render_telegram(
            "alert.md.j2",
            ticker="SBER", title="Test", priority="HIGH",
            priority_score=0.75, anomaly_score=0.6,
            predicted_return=0.01, reason="anomaly detected",
            in_portfolio=True,
        )
        assert "SBER" in html
        assert "Test" in html
        assert "HIGH" in html
        assert "0.75" in html
        assert "anomaly detected" in html
        assert PRIORITY_EMOJI["HIGH"] in html

    def test_render_alert_low_priority(self, renderer: AlertTemplateRenderer):
        html = renderer.render_telegram(
            "alert.md.j2",
            ticker="GAZP", title="Low",
            priority="LOW", priority_score=0.1,
            anomaly_score=0.0, predicted_return=0.0,
        )
        assert PRIORITY_EMOJI["LOW"] in html

    def test_render_signal(self, renderer: AlertTemplateRenderer):
        html = renderer.render_telegram(
            "signal.md.j2",
            ticker="SBER", action="BUY", confidence=0.85,
            reasons=["strong momentum", "low valuation"],
            max_portfolio_pct=10,
        )
        assert "SBER" in html
        assert "BUY" in html
        assert "strong momentum" in html
        assert "0.85" in html or "85%" in html

    def test_render_signal_with_prev_action(self, renderer: AlertTemplateRenderer):
        html = renderer.render_telegram(
            "signal.md.j2",
            ticker="SBER", action="SELL", confidence=0.7,
            prev_action="BUY", reasons=["trend reversal"],
            max_portfolio_pct=5,
        )
        assert "SELL" in html
        assert "BUY" in html
        assert "trend reversal" in html

    def test_render_daily(self, renderer: AlertTemplateRenderer):
        html = renderer.render_telegram(
            "daily.md.j2",
            date="2026-07-01", total_signals=42,
            buy_signals=8, sell_signals=3,
            geo_risk=4.5, portfolio_value=1_500_000,
            top_picks=["SBER", "GAZP"],
        )
        assert "2026-07-01" in html
        assert "42" in html
        assert "8" in html
        assert "3" in html
        assert "SBER" in html
        assert "GAZP" in html


class TestRenderEmail:
    def test_render_alert(self, renderer: AlertTemplateRenderer):
        html = renderer.render_email(
            "alert.html.j2",
            title="Alert", body="Something happened",
            ticker="SBER", priority="HIGH",
            anomaly_score=0.6, predicted_return=0.01,
            priority_score=0.75,
        )
        assert "Alert" in html
        assert "Something happened" in html
        assert "SBER" in html
        assert PRIORITY_COLORS["HIGH"] in html

    def test_render_signal(self, renderer: AlertTemplateRenderer):
        html = renderer.render_email(
            "signal.html.j2",
            ticker="SBER", action="BUY", confidence=0.85,
            prev_action="HOLD", reasons=["good quarter"],
            max_portfolio_pct=10,
        )
        assert "SBER" in html
        assert "BUY" in html
        assert "85%" in html or "0.85" in html
        assert "good quarter" in html

    def test_render_daily(self, renderer: AlertTemplateRenderer):
        html = renderer.render_email(
            "daily.html.j2",
            date="2026-07-01", total_signals=42,
            buy_signals=8, sell_signals=3,
            geo_risk=4.5, portfolio_value=1_500_000,
            top_picks=["SBER", "GAZP"],
        )
        assert "2026-07-01" in html
        assert "42" in html
        assert "8" in html
        assert "3" in html


class TestRenderWebpush:
    def test_render_alert(self, renderer: AlertTemplateRenderer):
        text = renderer.render_webpush(
            "alert.json.j2",
            title="Alert", body="Test", ticker="SBER",
            priority="HIGH", severity="HIGH",
        )
        assert '"Alert"' in text
        assert '"Test"' in text
        assert '"SBER"' in text
        assert '"HIGH"' in text

    def test_render_signal(self, renderer: AlertTemplateRenderer):
        text = renderer.render_webpush(
            "signal.json.j2",
            ticker="SBER", action="BUY", confidence=0.85,
            reasons=["good"], timestamp="2026-07-01T00:00:00",
        )
        assert '"SBER"' in text
        assert '"BUY"' in text


class TestRenderInline:
    def test_render_inline(self, renderer: AlertTemplateRenderer):
        text = renderer.render_inline("Hello {{ name }}!", name="World")
        assert text == "Hello World!"


class TestEnrich:
    def test_adds_emoji_by_priority(self, renderer: AlertTemplateRenderer):
        ctx = renderer._enrich({"priority": "CRITICAL"})
        assert ctx["emoji"] == PRIORITY_EMOJI["CRITICAL"]
        assert ctx["severity_color"] == PRIORITY_COLORS["CRITICAL"]

    def test_adds_emoji_by_action(self, renderer: AlertTemplateRenderer):
        ctx = renderer._enrich({"action": "BUY"})
        assert ctx["emoji"] == ACTION_EMOJI["BUY"]

    def test_default_priority_low(self, renderer: AlertTemplateRenderer):
        ctx = renderer._enrich({})
        assert ctx["emoji"] == PRIORITY_EMOJI["LOW"]
