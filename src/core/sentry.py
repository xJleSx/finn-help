from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def setup_sentry() -> None:
    try:
        from src.config import settings

        dsn = settings.sentry_dsn
        if not dsn:
            logger.info("Sentry not configured (SENTRY_DSN is empty)")
            return
        import sentry_sdk
        from sentry_sdk.integrations.logging import LoggingIntegration

        sentry_sdk.init(
            dsn=dsn,
            environment=settings.sentry_environment or "production",
            traces_sample_rate=0.1,
            profiles_sample_rate=0.05,
            send_default_pii=False,
            integrations=[LoggingIntegration(level=logging.INFO, event_level=logging.ERROR)],
        )
        logger.info("Sentry initialized for environment: %s", settings.sentry_environment)
    except Exception as e:
        logger.warning("Failed to initialize Sentry: %s", e)


def sentry_set_user_context(user_id: int, username: str = "", portfolio_id: int | None = None) -> None:
    try:
        import sentry_sdk

        sentry_sdk.set_user({"id": str(user_id), "username": username})
        extra = {}
        if portfolio_id is not None:
            extra["portfolio_id"] = portfolio_id
        if extra:
            sentry_sdk.set_context("finadvisor", extra)
    except Exception:
        pass


def sentry_set_extra(key: str, value: object) -> None:
    try:
        import sentry_sdk

        sentry_sdk.set_extra(key, value)
    except Exception:
        pass
