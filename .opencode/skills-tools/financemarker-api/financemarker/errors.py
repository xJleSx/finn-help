"""Domain-specific exceptions.

Codes mirror the BCS skill so the agent can reason about exit codes
uniformly:
  2 — invalid request
  3 — auth error
  4 — network / API error
  5 — internal bug
"""
from __future__ import annotations


class FmcError(Exception):
    code: int = 5

    def __init__(self, message: str = "") -> None:
        super().__init__(message or self.__class__.__name__)


class InvalidRequest(FmcError):
    code = 2


class AuthError(FmcError):
    code = 3


class ApiError(FmcError):
    code = 4


class ConfigError(FmcError):
    code = 2
