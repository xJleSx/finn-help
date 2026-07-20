from __future__ import annotations

import asyncio
import functools
from typing import Any, Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

try:
    from opentelemetry import trace
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.propagate import extract as _otel_extract
    from opentelemetry.propagate import inject as _otel_inject
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor
    from opentelemetry.trace import SpanKind, Status, StatusCode

    _OTEL_AVAILABLE = True
except ImportError:
    _OTEL_AVAILABLE = False
    trace = None
    OTLPSpanExporter = None
    TracerProvider = None
    BatchSpanProcessor = None
    Resource = None

    class SpanKind:
        INTERNAL = 1
        SERVER = 2
        CLIENT = 3
        PRODUCER = 4
        CONSUMER = 5

    class StatusCode:
        UNSET = 0
        OK = 1
        ERROR = 2

    class Status:
        def __init__(self, code: StatusCode, description: str = "") -> None:
            self.code = code
            self.description = description

    def _otel_extract(headers: dict) -> dict:
        return {}

    def _otel_inject(headers: dict) -> None:
        pass

    class _FakeTracer:
        def start_as_current_span(self, name: str, **kwargs: Any) -> Any:
            return _FakeSpan()

    class _FakeSpan:
        def __enter__(self) -> _FakeSpan:
            return self

        def __exit__(self, *args: Any) -> None:
            pass

        def set_attribute(self, key: str, value: Any) -> None:
            pass

        def set_status(self, status: Any) -> None:
            pass

        def record_exception(self, exc: Exception) -> None:
            pass


def get_tracer(module_name: str = __name__) -> Any:
    if not _OTEL_AVAILABLE:
        return _FakeTracer()
    return trace.get_tracer(module_name)


def setup_tracing(service_name: str = "finn-api", exporter_endpoint: str = "http://localhost:4318") -> None:
    if not _OTEL_AVAILABLE:
        import logging

        logging.getLogger(__name__).info("OpenTelemetry not installed, tracing disabled")
        return
    resource = Resource.create({"service.name": service_name})
    provider = TracerProvider(resource=resource)
    exporter = OTLPSpanExporter(endpoint=exporter_endpoint)
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)


def traced(name: str | None = None, attributes: dict[str, Any] | None = None) -> Callable:
    def decorator(func: Callable) -> Callable:
        span_name = name or func.__qualname__

        @functools.wraps(func)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            tracer = get_tracer(func.__module__)
            with tracer.start_as_current_span(span_name, attributes=attributes, kind=SpanKind.INTERNAL) as span:
                try:
                    return await func(*args, **kwargs)
                except Exception as exc:
                    span.set_status(Status(StatusCode.ERROR, str(exc)))
                    span.record_exception(exc)
                    raise

        @functools.wraps(func)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            tracer = get_tracer(func.__module__)
            with tracer.start_as_current_span(span_name, attributes=attributes, kind=SpanKind.INTERNAL) as span:
                try:
                    return func(*args, **kwargs)
                except Exception as exc:
                    span.set_status(Status(StatusCode.ERROR, str(exc)))
                    span.record_exception(exc)
                    raise

        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper

    return decorator


class AsyncTraceMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if not _OTEL_AVAILABLE:
            return await call_next(request)

        tracer = get_tracer("fastapi")
        span_name = f"{request.method} {request.url.path}"
        ctx = _otel_extract(request.headers)
        with tracer.start_as_current_span(
            span_name,
            context=ctx,
            kind=SpanKind.SERVER,
            attributes={
                "http.method": request.method,
                "http.url": str(request.url),
                "http.path": request.url.path,
            },
        ) as span:
            response = await call_next(request)
            span.set_attribute("http.status_code", response.status_code)
            if response.status_code >= 400:
                span.set_status(Status(StatusCode.ERROR))
        return response


def inject_trace_context(headers: dict[str, str]) -> dict[str, str]:
    if not _OTEL_AVAILABLE:
        return headers
    _otel_inject(headers)
    return headers


def extract_trace_context(headers: dict[str, str]) -> Any:
    if not _OTEL_AVAILABLE:
        return {}
    return _otel_extract(headers)
