"""Domain-specific exceptions.

All exceptions raised by the skill derive from `BcsError` and carry an
integer `code` that becomes the process exit code:
  2 — invalid request
  3 — auth error
  4 — network / API error
  5 — internal bug
"""
from __future__ import annotations


class BcsError(Exception):
    code: int = 5

    def __init__(self, message: str = "") -> None:
        super().__init__(message or self.__class__.__name__)


class InvalidRequest(BcsError):
    code = 2


class AuthError(BcsError):
    code = 3


class ReadOnlyBlocked(AuthError):
    """Mutating command rejected because BCS_READ_ONLY=1."""

    def __init__(self, command: str) -> None:
        super().__init__(f"'{command}' is blocked in read-only mode")


class ApiError(BcsError):
    code = 4


class ConfigError(BcsError):
    code = 2


class NotConfigured(BcsError):
    """Endpoint exists in the public docs but the BFF host prefix
    has not been discovered yet. Update bcs_trade/endpoints.py."""

    code = 2
