"""Human-readable output for the CLI.

Kept tiny and dependency-free. Format is a stable, line-oriented
key/value view; the agent should always prefer --format json.
"""
from __future__ import annotations

from typing import Any


def to_human(data: Any) -> str:
    if isinstance(data, dict):
        if "error" in data and "message" in data:
            return f"ERROR: {data['error']}: {data['message']}"
        if "records" in data and isinstance(data["records"], list):
            records = data["records"]
            if records and "tradeQuantity" in records[0]:
                return _trades_table(data)
            if records and "executedQuantity" in records[0]:
                return _orders_table(data)
            if records and "last" in records[0]:
                return _quotes_table(data)
        if "securities" in data and "marketdata" in data:
            return _moex_market_table(data)
        if "description" in data and "boards" in data:
            return _moex_desc_table(data)
        if "splits" in data:
            return _moex_splits_table(data)
        if "candles" in data:
            return _moex_candles_table(data)
        return _kv(data)
    if isinstance(data, list):
        return "\n".join(_kv(d) if isinstance(d, dict) else str(d) for d in data)
    return str(data)


def _kv(d: dict[str, Any]) -> str:
    out = []
    for k, v in d.items():
        if isinstance(v, (dict, list)):
            import json

            v = json.dumps(v, ensure_ascii=False)
        out.append(f"{k}: {v}")
    return "\n".join(out)


_SIDE = {1: "BUY", 2: "SELL", "1": "BUY", "2": "SELL"}
_STATUS = {1: "NEW", 2: "EXECUTED", 3: "PARTIAL", 4: "CANCELLED", 5: "REJECTED"}


def _orders_table(data: dict[str, Any]) -> str:
    records = data.get("records", [])
    if not records:
        return "No orders found."
    # Detect trades vs orders by field names
    is_trades = "tradeQuantity" in records[0] if records else False
    if is_trades:
        return _trades_table(data)
    lines = [
        f"{'Date':<11} {'Side':<5} {'Ticker':<7} {'Qty':>10} {'Price':>12} {'Value':>12} {'Status':<10}"
    ]
    lines.append("-" * 75)
    for o in records:
        date = o.get("tradeDate", "")
        side = _SIDE.get(o.get("side"), "?")
        ticker = o.get("ticker", "")
        qty = o.get("executedQuantity", 0)
        price = o.get("averagePrice", 0)
        value = o.get("executedValue", 0)
        status = _STATUS.get(o.get("orderStatus"), "?")
        lines.append(f"{date:<11} {side:<5} {ticker:<7} {qty:>10.0f} {price:>12.3f} {value:>12.2f} {status:<10}")
    lines.append(f"\nTotal: {len(records)} order(s)")
    return "\n".join(lines)


def _trades_table(data: dict[str, Any]) -> str:
    records = data.get("records", [])
    if not records:
        return "No trades found."
    lines = [
        f"{'Date':<11} {'Side':<5} {'Ticker':<7} {'Qty':>10} {'Price':>12} {'Value':>12} {'Settle':<12}"
    ]
    lines.append("-" * 75)
    for t in records:
        dt = t.get("tradeDateTime", "")[:10]
        side = _SIDE.get(t.get("side"), "?")
        ticker = t.get("ticker", "")
        qty = t.get("tradeQuantity", 0)
        price = t.get("price", 0)
        value = t.get("volume", 0)
        settle = t.get("settleDate", "")
        lines.append(f"{dt:<11} {side:<5} {ticker:<7} {qty:>10.0f} {price:>12.3f} {value:>12.2f} {settle:<12}")
    lines.append(f"\nTotal: {len(records)} trade(s)")
    return "\n".join(lines)


def _quotes_table(data: dict[str, Any]) -> str:
    records = data.get("records", [])
    if not records:
        return "No quotes found."
    lines = [
        f"{'Ticker':<7} {'Last':>10} {'Bid':>10} {'Ask':>10} {'Change':>8} {'Chg%':>7} {'High':>10} {'Low':>10}"
    ]
    lines.append("-" * 80)
    for q in records:
        ticker = q.get("ticker", "")
        last = q.get("last", 0)
        bid = q.get("bid", 0)
        ask = q.get("offer", 0)
        chg = q.get("change", 0)
        chg_pct = q.get("changeRate", 0)
        high = q.get("high", 0)
        low = q.get("low", 0)
        lines.append(f"{ticker:<7} {last:>10.2f} {bid:>10.2f} {ask:>10.2f} {chg:>+8.2f} {chg_pct:>+6.2f}% {high:>10.2f} {low:>10.2f}")
    return "\n".join(lines)


def _iss_table(data: dict[str, Any], key: str) -> tuple[list[str], list[list]]:
    """Extract columns and rows from ISS format."""
    block = data.get(key, {})
    return block.get("columns", []), block.get("data", [])


def _moex_desc_table(data: dict[str, Any]) -> str:
    """Format /iss/securities/{ticker}.json response (description + boards)."""
    desc_cols, desc_rows = _iss_table(data, "description")
    if not desc_rows:
        return "No data."

    # Build field map from description
    field_map: dict[str, Any] = {}
    for row in desc_rows:
        if len(row) >= 3:
            field_map[row[0]] = row[2]

    lines = [
        f"Ticker:      {field_map.get('SECID', '-')}",
        f"Name:        {field_map.get('SHORTNAME', '-')}",
        f"Full name:   {field_map.get('NAME', '-')}",
        f"ISIN:        {field_map.get('ISIN', '-')}",
        f"Type:        {field_map.get('TYPENAME', '-')}",
        f"Reg number:  {field_map.get('REGNUMBER', '-')}",
        f"Issue size:  {field_map.get('ISSUESIZE', '-')}",
        f"Face value:  {field_map.get('FACEVALUE', '-')} {field_map.get('FACEUNIT', '')}",
        f"Issue date:  {field_map.get('ISSUEDATE', '-')}",
        f"List level:  {field_map.get('LISTLEVEL', '-')}",
        f"Qualified:   {'Yes' if field_map.get('ISQUALIFIEDINVESTORS') == '1' else 'No'}",
        f"Morning ses: {'Yes' if field_map.get('MORNINGSESSION') == '1' else 'No'}",
        f"Evening ses: {'Yes' if field_map.get('EVENINGSESSION') == '1' else 'No'}",
    ]

    # Show primary board
    boards_cols, boards_rows = _iss_table(data, "boards")
    if boards_rows:
        board_map = {c: i for i, c in enumerate(boards_cols)}
        primary = [r for r in boards_rows if board_map.get("is_primary") and r[board_map["is_primary"]] == 1]
        if primary:
            b = primary[0]
            bi = board_map.get("boardid", 0)
            ti = board_map.get("title", 1)
            lines.extend([
                "",
                f"Primary board: {b[bi]}",
                f"  {b[ti] if ti < len(b) else ''}",
            ])

    return "\n".join(lines)


def _moex_market_table(data: dict[str, Any]) -> str:
    """Format /engines/stock/.../securities/{ticker}.json (securities + marketdata)."""
    sec_cols, sec_rows = _iss_table(data, "securities")
    if not sec_rows:
        return "No data."
    row = sec_rows[0]
    col_map = {c: i for i, c in enumerate(sec_cols)}

    def _g(name: str, default: Any = "-") -> Any:
        idx = col_map.get(name)
        return row[idx] if idx is not None and idx < len(row) else default

    lines = [
        f"Ticker:      {_g('SECID')}",
        f"Name:        {_g('SECNAME')}",
        f"ISIN:        {_g('ISIN', '-')}",
        f"Board:       {_g('BOARDID')} ({_g('BOARDNAME')})",
        f"Lot size:    {_g('LOTSIZE')}",
        f"Face value:  {_g('FACEVALUE')} {_g('FACEUNIT', '')}",
        f"Min step:    {_g('MINSTEP')}",
        f"Decimals:    {_g('DECIMALS')}",
        f"Prev price:  {_g('PREVPRICE')}",
        f"Issue size:  {_g('ISSUESIZE')}",
        f"Settle date: {_g('SETTLEDATE')}",
        f"Status:      {_g('STATUS')}",
    ]

    # Market data
    md_cols, md_rows = _iss_table(data, "marketdata")
    if md_rows:
        md = md_rows[0]
        md_map = {c: i for i, c in enumerate(md_cols)}

        def _mg(name: str, default: Any = "-") -> Any:
            idx = md_map.get(name)
            return md[idx] if idx is not None and idx < len(md) else default

        lines.extend([
            "",
            f"Last:        {_mg('LAST')}",
            f"Bid:         {_mg('BID')}",
            f"Ask:         {_mg('OFFER')}",
            f"Open:        {_mg('OPEN')}",
            f"High:        {_mg('HIGH')}",
            f"Low:         {_mg('LOW')}",
            f"Change:      {_mg('CHANGE')}",
            f"Volume:      {_mg('VOLTODAY')}",
            f"Value:       {_mg('VALTODAY')}",
            f"Trades:      {_mg('NUMTRADES')}",
            f"Status:      {_mg('TRADINGSTATUS')}",
            f"Updated:     {_mg('UPDATETIME')}",
        ])
    return "\n".join(lines)


def _moex_splits_table(data: dict[str, Any]) -> str:
    cols, rows = _iss_table(data, "splits")
    if not rows:
        return "No splits found."
    col_map = {c: i for i, c in enumerate(cols)}
    di = col_map.get("tradedate", 0)
    si = col_map.get("secid", 1)
    bi = col_map.get("before", 2)
    ai = col_map.get("after", 3)

    lines = [f"{'Date':<12} {'Ticker':<12} {'Before':>8} {'After':>8} {'Ratio':>10}"]
    lines.append("-" * 55)
    for r in rows:
        date = r[di] if di < len(r) else ""
        secid = r[si] if si < len(r) else ""
        before = r[bi] if bi < len(r) else 0
        after = r[ai] if ai < len(r) else 0
        ratio = f"{after}/{before}" if before else "-"
        lines.append(f"{date:<12} {secid:<12} {before:>8} {after:>8} {ratio:>10}")
    lines.append(f"\nTotal: {len(rows)} split(s)")
    return "\n".join(lines)


def _moex_candles_table(data: dict[str, Any]) -> str:
    cols, rows = _iss_table(data, "candles")
    if not rows:
        return "No candles found."
    col_map = {c: i for i, c in enumerate(cols)}

    def _g(row: list, name: str, default: Any = 0) -> Any:
        idx = col_map.get(name)
        return row[idx] if idx is not None and idx < len(row) else default

    lines = [f"{'Date':<12} {'Open':>10} {'High':>10} {'Low':>10} {'Close':>10} {'Volume':>12} {'Value':>16}"]
    lines.append("-" * 90)
    for r in rows:
        begin = str(_g(r, "begin", ""))[:10]
        o = _g(r, "open")
        h = _g(r, "high")
        l = _g(r, "low")
        c = _g(r, "close")
        vol = _g(r, "volume")
        val = _g(r, "value")
        lines.append(f"{begin:<12} {o:>10.2f} {h:>10.2f} {l:>10.2f} {c:>10.2f} {vol:>12} {val:>16,.0f}")
    lines.append(f"\nTotal: {len(rows)} candle(s)")
    return "\n".join(lines)
