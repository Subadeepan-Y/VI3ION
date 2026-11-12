"""FastAPI application. Routes coordinate the engine; they never process pixels."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from ..config import PROJECT_ROOT, get_settings
from ..core.engine import Vi3ionEngine
from ..core.ingestion import IngestError
from ..errors import Vi3ionError
from .routes import images, system, tools

logger = logging.getLogger("vi3ion.server")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    settings.ensure_dirs()
    app.state.engine = Vi3ionEngine(settings)
    logger.info("Vi3ion ready. data_dir=%s", settings.data_dir)
    yield


app = FastAPI(
    title="Vi3ion",
    version="0.1.0",
    description=(
        "Visual intelligence for AI agents. Local-first perception with structured evidence. "
        "HTTP API for the development dashboard; agents normally connect over MCP."
    ),
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:5173",
        "http://localhost:5173",
        "http://127.0.0.1:8765",
        "http://localhost:8765",
    ],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(system.router)
app.include_router(images.router)
app.include_router(tools.router)


@app.exception_handler(Vi3ionError)
async def vi3ion_error_handler(request: Request, exc: Vi3ionError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"ok": False, "error": exc.message, "type": type(exc).__name__},
    )


@app.exception_handler(IngestError)
async def ingest_error_handler(request: Request, exc: IngestError) -> JSONResponse:
    return JSONResponse(
        status_code=422, content={"ok": False, "error": str(exc), "type": "IngestError"}
    )


dist = PROJECT_ROOT / "dashboard" / "dist"
if dist.exists():
    app.mount("/", StaticFiles(directory=dist, html=True), name="dashboard")
else:

    @app.get("/")
    def root() -> dict:
        return {
            "service": "Vi3ion",
            "version": "0.1.0",
            "dashboard": "not built - run `npm install && npm run build` in dashboard/",
            "api_docs": "/docs",
            "health": "/api/health",
        }
