from __future__ import annotations

try:
    from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
    from opentelemetry.metrics import get_meter_provider, set_meter_provider
    from opentelemetry.sdk.metrics import MeterProvider
    from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
    from opentelemetry.sdk.resources import Resource

    _OTEL_AVAILABLE = True
except ImportError:
    _OTEL_AVAILABLE = False

# Configurable via settings.otlp_endpoint (default in config.py)
OTLP_METRICS_ENDPOINT = "http://localhost:4318/v1/metrics"

_setup_done = False
_meter = None
_inference_counter = None
_inference_histogram = None
_signal_counter = None
_signal_histogram = None
_trade_counter = None
_trade_histogram = None
_error_counter = None


def setup_metrics(service_name: str = "finn-api", exporter_endpoint: str | None = None) -> None:
    global _meter, _setup_done
    if _setup_done:
        return
    if not _OTEL_AVAILABLE:
        import logging

        logging.getLogger(__name__).info("OpenTelemetry not installed, metrics disabled")
        _setup_done = True
        return
    resource = Resource.create({"service.name": service_name})
    from src.config import settings
    endpoint = exporter_endpoint or settings.otlp_endpoint or "http://localhost:4317"
    reader = PeriodicExportingMetricReader(OTLPMetricExporter(endpoint=endpoint))
    provider = MeterProvider(resource=resource, metric_readers=[reader])
    set_meter_provider(provider)
    _meter = get_meter_provider().get_meter(service_name)
    _init_instruments()
    _setup_done = True


def _init_instruments() -> None:
    global _inference_counter, _inference_histogram, _signal_counter, _signal_histogram
    global _trade_counter, _trade_histogram, _error_counter
    if _meter is None:
        return
    _inference_counter = _meter.create_counter("inference.total", description="Total ML inference calls")
    _inference_histogram = _meter.create_histogram(
        "inference.latency.ms", description="ML inference latency in milliseconds", unit="ms"
    )
    _signal_counter = _meter.create_counter("signal.total", description="Total signals generated")
    _signal_histogram = _meter.create_histogram(
        "signal.confidence", description="Signal confidence distribution"
    )
    _trade_counter = _meter.create_counter("trade.total", description="Total trades executed")
    _trade_histogram = _meter.create_histogram(
        "trade.value", description="Trade value distribution"
    )
    _error_counter = _meter.create_counter("error.total", description="Total errors by module and type")


def track_inference(model_name: str, latency_ms: float, success: bool) -> None:
    if not _OTEL_AVAILABLE:
        return
    if _inference_counter is not None:
        _inference_counter.add(1, {"model": model_name, "success": str(success)})
    if _inference_histogram is not None:
        _inference_histogram.record(latency_ms, {"model": model_name})


def track_signal(ticker: str, signal_type: str, confidence: float) -> None:
    if not _OTEL_AVAILABLE:
        return
    if _signal_counter is not None:
        _signal_counter.add(1, {"ticker": ticker, "signal_type": signal_type})
    if _signal_histogram is not None:
        _signal_histogram.record(confidence, {"ticker": ticker, "signal_type": signal_type})


def track_trade(ticker: str, action: str, value: float) -> None:
    if not _OTEL_AVAILABLE:
        return
    if _trade_counter is not None:
        _trade_counter.add(1, {"ticker": ticker, "action": action})
    if _trade_histogram is not None:
        _trade_histogram.record(value, {"ticker": ticker, "action": action})


def track_error(module: str, error_type: str) -> None:
    if not _OTEL_AVAILABLE:
        return
    if _error_counter is not None:
        _error_counter.add(1, {"module": module, "error_type": error_type})
