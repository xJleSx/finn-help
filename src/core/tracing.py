import asyncio
import functools
import logging
from contextlib import contextmanager
from typing import Any, Callable

try:
    from opentelemetry import trace
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    _OTEL_AVAILABLE = True
except ImportError:
    _OTEL_AVAILABLE = False

logger = logging.getLogger(__name__)

_tracer = None


def setup_tracing(service_name: str = "finn-help", otlp_endpoint: str | None = None) -> None:
    if not _OTEL_AVAILABLE:
        logger.info("OpenTelemetry not installed, tracing disabled")
        return
    resource = Resource.create({"service.name": service_name})
    provider = TracerProvider(resource=resource)
    if otlp_endpoint:
        exporter = OTLPSpanExporter(endpoint=otlp_endpoint)
        provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    global _tracer
    _tracer = trace.get_tracer(service_name)
    logger.info("OpenTelemetry tracing initialized")


def get_tracer():
    if _tracer is not None:
        return _tracer
    if _OTEL_AVAILABLE:
        return trace.get_tracer(__name__)
    return None


def trace_call(span_name: str | None = None) -> Callable:
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            tracer = get_tracer()
            name = span_name or func.__name__
            if tracer is None:
                return await func(*args, **kwargs)
            with tracer.start_as_current_span(name):
                return await func(*args, **kwargs)

        @functools.wraps(func)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            tracer = get_tracer()
            name = span_name or func.__name__
            if tracer is None:
                return func(*args, **kwargs)
            with tracer.start_as_current_span(name):
                return func(*args, **kwargs)

        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper

    return decorator


@contextmanager
def span(name: str, attributes: dict[str, Any] | None = None):
    tracer = get_tracer()
    if tracer is None:
        yield
        return
    with tracer.start_as_current_span(name, attributes=attributes) if attributes else tracer.start_as_current_span(name):
        yield


def record_exception(otel_span, exception: Exception) -> None:
    if _OTEL_AVAILABLE:
        otel_span.record_exception(exception)
