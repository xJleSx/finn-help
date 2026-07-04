"""Human-readable output for the CLI."""
from __future__ import annotations

import json
from typing import Any


def to_human(data: Any) -> str:
    if isinstance(data, dict):
        if "error" in data and "message" in data:
            return f"ERROR: {data['error']}: {data['message']}"
        if data.get("ok") is True and "quota" in data:
            return _quota(data)
        return _kv(data)
    if isinstance(data, list):
        return "\n".join(_kv(d) if isinstance(d, dict) else str(d) for d in data)
    return str(data)


def _quota(data: dict[str, Any]) -> str:
    return (
        f"Token: {data.get('masked_token', '***')}\n"
        f"Daily quota left: {data.get('day_limit', '?')}\n"
        f"Subscription valid until: {data.get('valid_to', '?')}"
    )


def _kv(d: dict[str, Any]) -> str:
    out: list[str] = []
    for k, v in d.items():
        if isinstance(v, (dict, list)):
            v = json.dumps(v, ensure_ascii=False)
        out.append(f"{k}: {v}")
    return "\n".join(out)
