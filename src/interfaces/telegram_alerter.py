from __future__ import annotations

import logging
from typing import Any

from src.notifications.service import NotificationService
from src.notifications.templates.renderer import AlertTemplateRenderer

logger = logging.getLogger(__name__)

_renderer = AlertTemplateRenderer()


class AlertNotifier:
    def __init__(self, bot: Any) -> None:
        self.bot = bot
        self._notifier = NotificationService()

    async def send_alert(self, alert: dict[str, Any], chat_id: int) -> bool:
        text = _renderer.render_telegram(
            "alert.md.j2",
            **{k: alert.get(k) for k in (
                "ticker", "title", "priority", "priority_score",
                "anomaly_score", "predicted_return", "reason", "in_portfolio",
            )},
        )
        try:
            await self.bot.send_message(chat_id=chat_id, text=text, parse_mode="HTML")
            return True
        except Exception as e:
            logger.error("Failed to send alert to %s: %s", chat_id, e)
            return False

    async def send_digest(self, clusters: list[dict[str, Any]], chat_id: int) -> bool:
        if not clusters:
            return False
        lines = ["\U0001f4cb <b>Daily News Digest</b>\n"]
        for i, cluster in enumerate(clusters[:10], 1):
            topic = cluster.get("topic", "General")
            articles = cluster.get("articles", [])
            tickers = cluster.get("tickers", [])
            summary = cluster.get("summary", "") or ""
            ticker_str = ", ".join(tickers[:5]) if tickers else ""
            score = cluster.get("avg_score", 0.0)
            icon = "\U0001f534" if abs(score) > 0.5 else "\U0001f7e1" if abs(score) > 0.2 else "\U0001f7e2"
            lines.append(f"{i}. {icon} <b>{topic}</b>")
            if ticker_str:
                lines.append(f"   {ticker_str}")
            if summary:
                lines.append(f"   <i>{summary[:200]}</i>")
            lines.append(f"   Articles: {len(articles)}")
            lines.append("")
        text = "\n".join(lines)
        try:
            await self.bot.send_message(chat_id=chat_id, text=text, parse_mode="HTML")
            return True
        except Exception as e:
            logger.error("Failed to send digest to %s: %s", chat_id, e)
            return False

    async def send_scenario_result(self, result: Any, chat_id: int) -> bool:
        name = getattr(result, "name", "Scenario")
        loss_pct = getattr(result, "loss_pct", 0.0)
        loss = getattr(result, "loss", 0.0)
        total_before = getattr(result, "total_before", 0.0)
        total_after = getattr(result, "total_after", 0.0)
        var_95 = getattr(result, "var_95", 0.0)
        emoji = "\U0001f534" if loss_pct < -0.1 else "\U0001f7e1" if loss_pct < -0.05 else "\U0001f7e2"
        text = (
            f"{emoji} <b>{name}</b>\n"
            f"\u2022 Portfolio: {total_before:,.0f} \u20bd\n"
            f"\u2022 After: {total_after:,.0f} \u20bd\n"
            f"\u2022 Change: {loss:+,.0f} \u20bd ({loss_pct:+.1%})\n"
        )
        if var_95 < 0:
            text += f"\u2022 VaR(95%): {var_95:.1%}\n"
        try:
            await self.bot.send_message(chat_id=chat_id, text=text, parse_mode="HTML")
            return True
        except Exception as e:
            logger.error("Failed to send scenario to %s: %s", chat_id, e)
            return False
