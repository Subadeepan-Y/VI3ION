"""Typed errors surfaced to agents without leaking internals."""

from __future__ import annotations


class Vi3ionError(Exception):
    status_code = 400

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class NotFoundError(Vi3ionError):
    status_code = 404


class ValidationError(Vi3ionError):
    status_code = 422


class AccessDeniedError(Vi3ionError):
    status_code = 403


class ProviderError(Vi3ionError):
    status_code = 502
