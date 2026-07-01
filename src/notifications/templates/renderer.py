from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import structlog
from jinja2 import Environment, FileSystemLoader, BaseLoader, select_autoescape

logger = structlog.get_logger(__name__)

PRIORITY_EMOJI = {
    "CRITICAL": "\U0001f534",
    "HIGH": "\U0001f7e1",
    "MEDIUM": "\U0001f7e0",
    "LOW": "\U0001f7e2",
}

PRIORITY_COLORS = {
    "CRITICAL": "#d32f2f",
    "HIGH": "#f57c00",
    "MEDIUM": "#fbc02d",
    "LOW": "#388e3c",
}

ACTION_EMOJI = {
    "BUY": "\U0001f7e2",
    "CAUTIOUS_BUY": "\U0001f7e1",
    "HOLD": "\u26aa",
    "SELL": "\U0001f534",
    "NEUTRAL": "\u26aa",
}

TEMPLATE_DIR = Path(__file__).resolve().parent


class AlertTemplateRenderer:
    def __init__(self, template_dir: str | Path | None = None) -> None:
        self._dir = Path(template_dir) if template_dir else TEMPLATE_DIR
        loader = FileSystemLoader(str(self._dir))
        self._email_env = Environment(
            loader=loader,
            autoescape=select_autoescape(),
            trim_blocks=True,
            lstrip_blocks=True,
        )
        self._text_env = Environment(
            loader=loader,
            autoescape=False,
            trim_blocks=True,
            lstrip_blocks=True,
        )
        self._inline_env = Environment(
            loader=BaseLoader(),
            autoescape=False,
        )

    def render_telegram(self, template_name: str, **kwargs: Any) -> str:
        template = self._text_env.get_template(f"telegram/{template_name}")
        enriched = self._enrich(kwargs)
        return template.render(**enriched)

    def render_email(self, template_name: str, **kwargs: Any) -> str:
        template = self._email_env.get_template(f"email/{template_name}")
        enriched = self._enrich(kwargs)
        return template.render(**enriched)

    def render_webpush(self, template_name: str, **kwargs: Any) -> str:
        template = self._text_env.get_template(f"webpush/{template_name}")
        enriched = self._enrich(kwargs)
        enriched.setdefault("timestamp", datetime.now(timezone.utc).isoformat())
        return template.render(**enriched)

    def render_inline(self, template_text: str, **kwargs: Any) -> str:
        template = self._inline_env.from_string(template_text)
        return template.render(**kwargs)

    def _enrich(self, ctx: dict[str, Any]) -> dict[str, Any]:
        ctx = dict(ctx)
        priority = ctx.get("priority", "LOW")
        ctx.setdefault("emoji", PRIORITY_EMOJI.get(priority, "\u26a0"))
        ctx.setdefault("severity_emoji", PRIORITY_EMOJI.get(priority, "\u26a0"))
        ctx.setdefault("severity_color", PRIORITY_COLORS.get(priority, "#666"))
        ctx.setdefault("severity", priority)
        action = ctx.get("action")
        if action:
            ctx.setdefault("emoji", ACTION_EMOJI.get(action, "\u26aa"))
        return ctx
