from __future__ import annotations

import uuid
from contextvars import ContextVar
from typing import Optional

_request_id: ContextVar[str] = ContextVar("request_id", default="")
_trace_id: ContextVar[str] = ContextVar("trace_id", default="")
_operation: ContextVar[str] = ContextVar("operation", default="")


def generate_id(prefix: str = "", length: int = 12) -> str:
    raw = uuid.uuid4().hex[:length]
    return f"{prefix}_{raw}" if prefix else raw


def get_request_id() -> str:
    return _request_id.get()


def set_request_id(rid: Optional[str] = None) -> str:
    if rid is None:
        rid = generate_id("req", 12)
    _request_id.set(rid)
    return rid


def reset_request_id() -> None:
    _request_id.set("")


def get_trace_id() -> str:
    return _trace_id.get()


def set_trace_id(tid: Optional[str] = None) -> str:
    if tid is None:
        tid = generate_id("trace", 16)
    _trace_id.set(tid)
    return tid


def get_operation() -> str:
    return _operation.get()


def set_operation(op: str) -> str:
    _operation.set(op)
    return op


class RequestContextScope:
    def __init__(self, request_id: Optional[str] = None, trace_id: Optional[str] = None, operation: str = ""):
        self._request_id = request_id
        self._trace_id = trace_id
        self._operation = operation
        self._prev_request_id: Optional[str] = None
        self._prev_trace_id: Optional[str] = None
        self._prev_operation: Optional[str] = None

    async def __aenter__(self) -> RequestContextScope:
        self._prev_request_id = get_request_id()
        self._prev_trace_id = get_trace_id()
        self._prev_operation = get_operation()
        set_request_id(self._request_id or generate_id("req", 12))
        set_trace_id(self._trace_id or generate_id("trace", 16))
        if self._operation:
            set_operation(self._operation)
        return self

    async def __aexit__(self, *args: object) -> None:
        if self._prev_request_id:
            _request_id.set(self._prev_request_id)
        else:
            reset_request_id()
        if self._prev_trace_id:
            _trace_id.set(self._prev_trace_id)
        if self._prev_operation:
            _operation.set(self._prev_operation)


def context_extra() -> dict[str, str]:
    extras: dict[str, str] = {}
    rid = get_request_id()
    if rid:
        extras["request_id"] = rid
    tid = get_trace_id()
    if tid:
        extras["trace_id"] = tid
    op = get_operation()
    if op:
        extras["operation"] = op
    return extras
