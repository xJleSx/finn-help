#!/usr/bin/env python3
"""Fetch real MOEX data for validation."""
import httpx, json

url = "https://iss.moex.com/iss/engines/stock/markets/shares/securities/SBER/candles.json?from=2023-01-01&interval=24"
try:
    r = httpx.get(url, timeout=15)
    print(f"Status: {r.status_code}")
    if r.status_code == 200:
        data = r.json()
        print(f"Columns: {data['candles']['columns']}")
        print(f"Rows: {len(data['candles']['data'])}")
        print(f"Last row: {data['candles']['data'][-1]}")
    else:
        print(r.text[:500])
except Exception as e:
    print(f"Error: {e}")
