from __future__ import annotations

import logging
from typing import Any, Callable

logger = logging.getLogger(__name__)


class AlertPushService:
    def __init__(self) -> None:
        self._subscribers: dict[str, Callable[[dict[str, Any]], None]] = {}

    def subscribe(self, client_id: str) -> None:
        def _noop(alert: dict[str, Any]) -> None:
            pass

        self._subscribers[client_id] = _noop
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
                logger.exception(
                    "AlertPushService: handler for %s failed", client_id
                )

    def broadcast(self, alerts: list[dict[str, Any]]) -> None:
        for alert in alerts:
            self.publish(alert)
