from __future__ import annotations

import logging
from typing import Any, Callable

logger = logging.getLogger(__name__)


class AlertPushService:
    def __init__(self) -> None:
        self._subscribers: dict[str, Callable[[dict[str, Any]], None]] = {}

    def subscribe(self, client_id: str, handler: Callable[[dict[str, Any]], None] | None = None) -> None:
        if handler is None:
            logger.warning(
                "AlertPushService: client %s subscribed with no handler — push will be a no-op. "
                "Pass a callable handler to enable real push delivery.",
                client_id,
            )
        self._subscribers[client_id] = handler or (lambda alert: None)
        logger.info("AlertPushService: client %s subscribed", client_id)

    def unsubscribe(self, client_id: str) -> None:
        self._subscribers.pop(client_id, None)
        logger.info("AlertPushService: client %s unsubscribed", client_id)

    def publish(self, alert: dict[str, Any]) -> None:
        logger.info(
            "AlertPushService: publishing alert for %s — %s",
            alert.get("ticker", "N/A"),
            alert.get("reason", alert.get("message", "")),
        )
        for client_id, handler in self._subscribers.items():
            try:
                handler(alert)
            except Exception:
                logger.exception("Unhandled exception")
                logger.exception("AlertPushService: handler for %s failed", client_id)

    def broadcast(self, alerts: list[dict[str, Any]]) -> None:
        for alert in alerts:
            self.publish(alert)
