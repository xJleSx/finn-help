from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any, Optional

from rich.console import Console
from rich.table import Table

console = Console()

_OUTPUT_FORMAT: str = "text"


def set_output_format(fmt: str) -> None:
    global _OUTPUT_FORMAT
    _OUTPUT_FORMAT = fmt if fmt in ("text", "json") else "text"


def get_output_format() -> str:
    return _OUTPUT_FORMAT


def _serialize(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: _serialize(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_serialize(v) for v in value]
    return value


def print_data(
    data: Any,
    title: str = "",
    columns: Optional[list[str]] = None,
    json_fallback: bool = True,
) -> None:
    if _OUTPUT_FORMAT == "json":
        output = _serialize(data)
        console.print(json.dumps(output, ensure_ascii=False, indent=2))
        return
    if isinstance(data, list) and data and columns:
        table = Table(title=title, title_style="bold cyan")
        for col in columns:
            table.add_column(col, style="cyan", no_wrap=True)
        for row in data:
            table.add_row(*[str(row.get(c, "")) for c in columns])
        console.print(table)
    elif isinstance(data, list) and data and isinstance(data[0], dict):
        cols = columns or list(data[0].keys())
        table = Table(title=title, title_style="bold cyan")
        for col in cols:
            table.add_column(col, style="cyan", no_wrap=True)
        for row in data:
            table.add_row(*[str(row.get(c, "")) for c in cols])
        console.print(table)
    elif isinstance(data, dict):
        table = Table(title=title, title_style="bold cyan")
        table.add_column("Key", style="cyan")
        table.add_column("Value", style="white")
        for k, v in data.items():
            table.add_row(str(k), str(v))
        console.print(table)
    else:
        console.print(str(data))


def print_json(data: Any) -> None:
    output = _serialize(data)
    console.print(json.dumps(output, ensure_ascii=False, indent=2))
