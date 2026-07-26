from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def _reset_tracing_module():
    import src.core.observability.tracing as tracing_mod

    tracing_mod._OTEL_AVAILABLE = True
    yield
    tracing_mod._OTEL_AVAILABLE = True


# ── traced decorator ────────────────────────────────────────────────────────


def test_traced_decorator_sync():
    mock_span = MagicMock()
    mock_span.__enter__ = MagicMock(return_value=mock_span)
    mock_span.__exit__ = MagicMock(return_value=None)
    mock_tracer = MagicMock()
    mock_tracer.start_as_current_span.return_value = mock_span

    with patch("src.core.observability.tracing.get_tracer", return_value=mock_tracer):
        from src.core.observability.tracing import traced

        @traced("test_op")
        def sync_fn(x: int) -> int:
            return x * 2

        result = sync_fn(21)

    assert result == 42
    args, kwargs = mock_tracer.start_as_current_span.call_args
    assert args[0] == "test_op"


def test_traced_decorator_async():
    mock_span = MagicMock()
    mock_span.__enter__ = MagicMock(return_value=mock_span)
    mock_span.__exit__ = MagicMock(return_value=None)
    mock_tracer = MagicMock()
    mock_tracer.start_as_current_span.return_value = mock_span

    with patch("src.core.observability.tracing.get_tracer", return_value=mock_tracer):
        from src.core.observability.tracing import traced

        @traced("async_op")
        async def async_fn(x: int) -> int:
            return x * 2

        result = asyncio.run(async_fn(11))

    assert result == 22
    args, _ = mock_tracer.start_as_current_span.call_args
    assert args[0] == "async_op"


def test_traced_decorator_error_sets_status():
    mock_span = MagicMock()
    mock_span.__enter__ = MagicMock(return_value=mock_span)
    mock_span.__exit__ = MagicMock(return_value=None)
    mock_tracer = MagicMock()
    mock_tracer.start_as_current_span.return_value = mock_span

    with patch("src.core.observability.tracing.get_tracer", return_value=mock_tracer):
        from src.core.observability.tracing import traced

        @traced("failing_op")
        def failing() -> None:
            msg = "boom"
            raise ValueError(msg)

        with pytest.raises(ValueError, match="boom"):
            failing()

    assert mock_span.set_status.called
    assert mock_span.record_exception.called


# ── AsyncTraceMiddleware ────────────────────────────────────────────────────


def test_middleware_captures_method_and_path():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from src.core.observability.tracing import AsyncTraceMiddleware

    mock_span = MagicMock()
    mock_span.__enter__ = MagicMock(return_value=mock_span)
    mock_span.__exit__ = MagicMock(return_value=None)
    mock_tracer = MagicMock()
    mock_tracer.start_as_current_span.return_value = mock_span

    app = FastAPI()

    @app.get("/test")
    async def test_route() -> dict:
        return {"ok": True}

    app.add_middleware(AsyncTraceMiddleware)

    with (
        patch("src.core.observability.tracing._otel_extract", return_value={}),
        patch("src.core.observability.tracing.get_tracer", return_value=mock_tracer),
    ):
        client = TestClient(app)
        resp = client.get("/test")

    assert resp.status_code == 200
    args, kwargs = mock_tracer.start_as_current_span.call_args
    assert args[0] == "GET /test"

    attrs = kwargs.get("attributes", {})
    assert attrs.get("http.method") == "GET"
    assert attrs.get("http.path") == "/test"


def test_middleware_sets_status_code():
    from fastapi import FastAPI
    from fastapi.responses import JSONResponse
    from fastapi.testclient import TestClient
    from src.core.observability.tracing import AsyncTraceMiddleware

    mock_span = MagicMock()
    mock_span.__enter__ = MagicMock(return_value=mock_span)
    mock_span.__exit__ = MagicMock(return_value=None)
    mock_tracer = MagicMock()
    mock_tracer.start_as_current_span.return_value = mock_span

    app = FastAPI()

    @app.get("/error")
    async def error_route() -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": "Not found"})

    app.add_middleware(AsyncTraceMiddleware)

    with (
        patch("src.core.observability.tracing._otel_extract", return_value={}),
        patch("src.core.observability.tracing.get_tracer", return_value=mock_tracer),
    ):
        client = TestClient(app)
        resp = client.get("/error")

    assert resp.status_code == 404
    mock_span.set_attribute.assert_any_call("http.status_code", 404)


# ── Trace context injection / extraction ────────────────────────────────────


def test_inject_extract_roundtrip():
    from src.core.observability.tracing import extract_trace_context, inject_trace_context

    headers = {"content-type": "application/json"}

    with (
        patch("src.core.observability.tracing._OTEL_AVAILABLE", True),
        patch("src.core.observability.tracing._otel_inject") as mock_inject,
    ):
        mock_inject.side_effect = lambda h: h.update({"traceparent": "00-abc-123-01"})

        result = inject_trace_context(headers)

    assert "traceparent" in result
    assert result["traceparent"] == "00-abc-123-01"

    with (
        patch("src.core.observability.tracing._OTEL_AVAILABLE", True),
        patch("src.core.observability.tracing._otel_extract", return_value={"trace_id": 123}),
    ):
        ctx = extract_trace_context({"traceparent": "00-abc-123-01"})

    assert ctx == {"trace_id": 123}


def test_inject_extract_noop_when_otel_missing():
    from src.core.observability.tracing import extract_trace_context, inject_trace_context

    with patch("src.core.observability.tracing._OTEL_AVAILABLE", False):
        result = inject_trace_context({"x-custom": "val"})
        assert result == {"x-custom": "val"}

        ctx = extract_trace_context({"traceparent": "00-abc-123-01"})
        assert ctx == {}


# ── Metrics ─────────────────────────────────────────────────────────────────


def test_track_inference():
    mock_counter = MagicMock()
    mock_histogram = MagicMock()

    with (
        patch("src.core.observability.metrics._OTEL_AVAILABLE", True),
        patch("src.core.observability.metrics._inference_counter", mock_counter),
        patch("src.core.observability.metrics._inference_histogram", mock_histogram),
    ):
        from src.core.observability.metrics import track_inference

        track_inference(model_name="xgboost", latency_ms=150.0, success=True)

    mock_counter.add.assert_called_once_with(1, {"model": "xgboost", "success": "True"})
    mock_histogram.record.assert_called_once_with(150.0, {"model": "xgboost"})


def test_track_signal():
    mock_counter = MagicMock()
    mock_histogram = MagicMock()

    with (
        patch("src.core.observability.metrics._OTEL_AVAILABLE", True),
        patch("src.core.observability.metrics._signal_counter", mock_counter),
        patch("src.core.observability.metrics._signal_histogram", mock_histogram),
    ):
        from src.core.observability.metrics import track_signal

        track_signal(ticker="SBER", signal_type="buy", confidence=0.87)

    mock_counter.add.assert_called_once_with(1, {"ticker": "SBER", "signal_type": "buy"})
    mock_histogram.record.assert_called_once_with(0.87, {"ticker": "SBER", "signal_type": "buy"})


def test_track_trade():
    mock_counter = MagicMock()

    with (
        patch("src.core.observability.metrics._OTEL_AVAILABLE", True),
        patch("src.core.observability.metrics._trade_counter", mock_counter),
    ):
        from src.core.observability.metrics import track_trade

        track_trade(ticker="GAZP", action="sell", value=50000.0)

    mock_counter.add.assert_called_once_with(1, {"ticker": "GAZP", "action": "sell"})


def test_track_error():
    mock_counter = MagicMock()

    with (
        patch("src.core.observability.metrics._OTEL_AVAILABLE", True),
        patch("src.core.observability.metrics._error_counter", mock_counter),
    ):
        from src.core.observability.metrics import track_error

        track_error(module="collector", error_type="timeout")

    mock_counter.add.assert_called_once_with(1, {"module": "collector", "error_type": "timeout"})


def test_metrics_noop_when_otel_missing():
    with patch("src.core.observability.metrics._OTEL_AVAILABLE", False):
        from src.core.observability.metrics import track_error, track_inference, track_signal, track_trade

        track_inference("m", 1.0, True)
        track_signal("T", "buy", 0.5)
        track_trade("T", "buy", 100.0)
        track_error("mod", "err")


# ── Setup functions ─────────────────────────────────────────────────────────


def test_setup_tracing_imports():
    from src.core.observability.tracing import get_tracer, setup_tracing, traced

    assert callable(setup_tracing)
    assert callable(traced)
    assert callable(get_tracer)


def test_setup_metrics_imports():
    from src.core.observability.metrics import setup_metrics, track_error, track_inference, track_signal, track_trade

    assert callable(setup_metrics)
    assert callable(track_inference)
    assert callable(track_error)
    assert callable(track_signal)
    assert callable(track_trade)


def test_module_exports():
    from src.core.observability import (
        AsyncTraceMiddleware,
        extract_trace_context,
        get_tracer,
        inject_trace_context,
        setup_metrics,
        setup_tracing,
        track_error,
        track_inference,
        track_signal,
        track_trade,
        traced,
    )

    assert callable(setup_tracing)
    assert callable(traced)
    assert callable(get_tracer)
    assert callable(inject_trace_context)
    assert callable(extract_trace_context)
    assert issubclass(AsyncTraceMiddleware, object)
    assert callable(setup_metrics)
    assert callable(track_inference)
    assert callable(track_signal)
    assert callable(track_trade)
    assert callable(track_error)
