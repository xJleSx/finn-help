from __future__ import annotations

import logging
from typing import Any

from src.notifications.service import NotificationService

logger = logging.getLogger(__name__)

PRIORITY_EMOJI = {
    "CRITICAL": "\U0001f534",
    "HIGH": "\U0001f7e1",
    "MEDIUM": "\U0001f7e0",
    "LOW": "\U0001f7e2",
}


class AlertNotifier:
    def __init__(self, bot: Any) -> None:
        self.bot = bot
        self._notifier = NotificationService()

    async def send_alert(self, alert: dict[str, Any], chat_id: int) -> bool:
        emoji = PRIORITY_EMOJI.get(alert.get("priority", "LOW"), "\u26a0")
        ticker = alert.get("ticker", "?")
        title = alert.get("title", "No title")
        anomaly = alert.get("anomaly_score", 0.0)
        pred_ret = alert.get("predicted_return", 0.0)
        reason = alert.get("reason", "")
        in_portfolio = alert.get("in_portfolio", False)

        portfolio_mark = "\U0001f4b0" if in_portfolio else ""
        text = (
            f"{emoji} *{ticker}* {portfolio_mark}\n"
            f"{title}\n"
            f"\u2022 Priority: {alert.get('priority', 'LOW')} ({alert.get('priority_score', 0.0):.2f})\n"
            f"\u2022 Anomaly: {anomaly:.2f}\n"
            f"\u2022 Prediction: {pred_ret:+.2%}\n"
        )
        if reason:
            text += f"\u2022 {reason}\n"

        try:
            await self.bot.send_message(chat_id=chat_id, text=text, parse_mode="Markdown")
            return True
        except Exception as e:
            logger.error("Failed to send alert to %s: %s", chat_id, e)
            return False

    async def send_digest(self, clusters: list[dict[str, Any]], chat_id: int) -> bool:
        if not clusters:
            return False
        lines = ["\U0001f4cb *Daily News Digest*\n"]
        for i, cluster in enumerate(clusters[:10], 1):
            topic = cluster.get("topic", "General")
            articles = cluster.get("articles", [])
            tickers = cluster.get("tickers", [])
            summary = cluster.get("summary", "") or ""

            ticker_str = ", ".join(tickers[:5]) if tickers else ""
            score = cluster.get("avg_score", 0.0)
            icon = "\U0001f534" if abs(score) > 0.5 else "\U0001f7e1" if abs(score) > 0.2 else "\U0001f7e2"

            lines.append(f"{i}. {icon} *{topic}*")
            if ticker_str:
                lines.append(f"   {ticker_str}")
            if summary:
                lines.append(f"   _{summary[:200]}_")
            lines.append(f"   Articles: {len(articles)}")
            lines.append("")

        text = "\n".join(lines)
        try:
            await self.bot.send_message(chat_id=chat_id, text=text, parse_mode="Markdown")
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
            f"{emoji} *{name}*\n"
            f"\u2022 Portfolio: {total_before:,.0f} \u20bd\n"
            f"\u2022 After: {total_after:,.0f} \u20bd\n"
            f"\u2022 Change: {loss:+,.0f} \u20bd ({loss_pct:+.1%})\n"
        )
        if var_95 < 0:
            text += f"\u2022 VaR(95%): {var_95:.1%}\n"

        try:
            await self.bot.send_message(chat_id=chat_id, text=text, parse_mode="Markdown")
            return True
        except Exception as e:
            logger.error("Failed to send scenario to %s: %s", chat_id, e)
            return False
