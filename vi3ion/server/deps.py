from __future__ import annotations

from fastapi import Request

from ..core.engine import Vi3ionEngine


def get_engine(request: Request) -> Vi3ionEngine:
    return request.app.state.engine
