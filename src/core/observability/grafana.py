from __future__ import annotations

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

GRAFANA_DIR = Path(__file__).resolve().parents[3] / "grafana"


DASHBOARD = {
    "title": "FinAdvisor",
    "version": 1,
    "timezone": "UTC",
    "panels": [
        {
            "title": "HTTP Requests",
            "type": "graph",
            "targets": [{"expr": 'rate(http_requests_total[5m])', "legendFormat": "{{method}} {{endpoint}}"}],
            "gridPos": {"h": 8, "w": 12, "x": 0, "y": 0},
        },
        {
            "title": "HTTP Latency (p99)",
            "type": "graph",
            "targets": [{"expr": 'histogram_quantile(0.99, rate(http_request_duration_seconds_bucket[5m]))', "legendFormat": "{{method}}"}],
            "gridPos": {"h": 8, "w": 12, "x": 12, "y": 0},
        },
        {
            "title": "Signals Generated",
            "type": "stat",
            "targets": [{"expr": 'rate(signals_generated_total[5m])', "legendFormat": "signals"}],
            "gridPos": {"h": 6, "w": 6, "x": 0, "y": 8},
        },
        {
            "title": "Trades Executed",
            "type": "stat",
            "targets": [{"expr": 'rate(trades_executed_total[5m])', "legendFormat": "trades"}],
            "gridPos": {"h": 6, "w": 6, "x": 6, "y": 8},
        },
        {
            "title": "Error Rate",
            "type": "graph",
            "targets": [{"expr": 'rate(errors_total[5m])', "legendFormat": "{{type}}"}],
            "gridPos": {"h": 6, "w": 6, "x": 12, "y": 8},
        },
        {
            "title": "ML Inference Calls",
            "type": "stat",
            "targets": [{"expr": 'rate(ml_inferences_total[5m])', "legendFormat": "inferences"}],
            "gridPos": {"h": 6, "w": 6, "x": 18, "y": 8},
        },
        {
            "title": "Scheduler Status",
            "type": "stat",
            "targets": [{"expr": "scheduler_running", "legendFormat": "running"}],
            "gridPos": {"h": 4, "w": 12, "x": 0, "y": 14},
        },
        {
            "title": "Database Connections",
            "type": "graph",
            "targets": [{"expr": "db_connections_active", "legendFormat": "active"}],
            "gridPos": {"h": 4, "w": 12, "x": 12, "y": 14},
        },
    ],
    "tags": ["finadvisor", "python"],
}


def export_dashboards() -> None:
    GRAFANA_DIR.mkdir(parents=True, exist_ok=True)
    path = GRAFANA_DIR / "dashboard.json"
    path.write_text(json.dumps(DASHBOARD, indent=2), encoding="utf-8")
    logger.info("Grafana dashboard exported to %s", path)
