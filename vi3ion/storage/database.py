"""SQLite persistence. Coordination only; no image processing lives here."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

SCHEMA = """
CREATE TABLE IF NOT EXISTS images (
    image_id       TEXT PRIMARY KEY,
    sha256         TEXT NOT NULL,
    original_path  TEXT NOT NULL,
    thumbnail_path TEXT,
    width          INTEGER NOT NULL,
    height         INTEGER NOT NULL,
    format         TEXT NOT NULL,
    size_bytes     INTEGER NOT NULL,
    created_at     TEXT NOT NULL,
    source         TEXT NOT NULL DEFAULT 'upload',
    meta           TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_images_sha ON images(sha256);
CREATE INDEX IF NOT EXISTS idx_images_created ON images(created_at DESC);

CREATE TABLE IF NOT EXISTS sessions (
    session_id  TEXT PRIMARY KEY,
    image_id    TEXT,
    agent       TEXT NOT NULL DEFAULT 'unknown',
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    meta        TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS jobs (
    job_id      TEXT PRIMARY KEY,
    image_id    TEXT NOT NULL,
    tool        TEXT NOT NULL,
    tasks       TEXT NOT NULL DEFAULT '[]',
    status      TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    started_at  TEXT,
    finished_at TEXT,
    duration_ms REAL,
    error       TEXT
);
CREATE INDEX IF NOT EXISTS idx_jobs_image ON jobs(image_id, created_at DESC);

CREATE TABLE IF NOT EXISTS evidence (
    evidence_id TEXT PRIMARY KEY,
    image_id    TEXT NOT NULL,
    job_id      TEXT,
    kind        TEXT NOT NULL,
    label       TEXT NOT NULL,
    x0          REAL, y0 REAL, x1 REAL, y1 REAL,
    confidence  REAL,
    attributes  TEXT NOT NULL DEFAULT '{}',
    module      TEXT NOT NULL,
    method      TEXT NOT NULL,
    version     TEXT NOT NULL,
    observed    INTEGER NOT NULL DEFAULT 1,
    scope       TEXT NOT NULL DEFAULT 'image',
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_evidence_image ON evidence(image_id, kind);
CREATE INDEX IF NOT EXISTS idx_evidence_label ON evidence(image_id, label);

CREATE TABLE IF NOT EXISTS analyses (
    cache_key   TEXT PRIMARY KEY,
    image_id    TEXT NOT NULL,
    tool        TEXT NOT NULL,
    payload     TEXT NOT NULL,
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_analyses_image ON analyses(image_id);

CREATE TABLE IF NOT EXISTS image_registry (
    image_id    TEXT PRIMARY KEY,
    label       TEXT NOT NULL DEFAULT '',
    signature   TEXT NOT NULL DEFAULT '{}',
    layout_key  TEXT NOT NULL DEFAULT '',
    text_key    TEXT NOT NULL DEFAULT '',
    text_count  INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_registry_layout ON image_registry(layout_key);

CREATE TABLE IF NOT EXISTS inspections (
    inspection_id TEXT PRIMARY KEY,
    session_id    TEXT,
    image_id      TEXT NOT NULL,
    tool          TEXT NOT NULL,
    request       TEXT NOT NULL DEFAULT '{}',
    summary       TEXT NOT NULL DEFAULT '',
    evidence_count INTEGER NOT NULL DEFAULT 0,
    created_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_inspections_image ON inspections(image_id, created_at DESC);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Database:
    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def init(self) -> None:
        with self.connect() as conn:
            conn.execute("PRAGMA journal_mode = WAL")
            conn.executescript(SCHEMA)

    # ---------------------------------------------------------------- images
    def add_image(self, record: dict[str, Any]) -> None:
        with self.connect() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO images
                   (image_id, sha256, original_path, thumbnail_path, width, height,
                    format, size_bytes, created_at, source, meta)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    record["image_id"], record["sha256"], record["original_path"],
                    record.get("thumbnail_path"), record["width"], record["height"],
                    record["format"], record["size_bytes"], record["created_at"],
                    record.get("source", "upload"), json.dumps(record.get("meta", {})),
                ),
            )

    def get_image(self, image_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM images WHERE image_id = ?", (image_id,)).fetchone()
        return self._image_row(row) if row else None

    def find_image_by_sha(self, sha256: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM images WHERE sha256 = ? ORDER BY created_at LIMIT 1", (sha256,)
            ).fetchone()
        return self._image_row(row) if row else None

    def list_images(self, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM images ORDER BY created_at DESC LIMIT ? OFFSET ?", (limit, offset)
            ).fetchall()
        return [self._image_row(r) for r in rows]

    def count_images(self) -> int:
        with self.connect() as conn:
            return int(conn.execute("SELECT COUNT(*) FROM images").fetchone()[0])

    def delete_image(self, image_id: str) -> None:
        with self.connect() as conn:
            for table in (
                "evidence",
                "analyses",
                "inspections",
                "jobs",
                "sessions",
                "image_registry",
                "images",
            ):
                conn.execute(f"DELETE FROM {table} WHERE image_id = ?", (image_id,))

    def evidence_count(self, image_id: str) -> int:
        with self.connect() as conn:
            return int(
                conn.execute("SELECT COUNT(*) FROM evidence WHERE image_id = ?", (image_id,)).fetchone()[0]
            )

    def total_evidence(self) -> int:
        with self.connect() as conn:
            return int(conn.execute("SELECT COUNT(*) FROM evidence").fetchone()[0])

    @staticmethod
    def _image_row(row: sqlite3.Row) -> dict[str, Any]:
        data = dict(row)
        data["meta"] = json.loads(data.get("meta") or "{}")
        return data

    # -------------------------------------------------------------- registry
    def upsert_image_registry(
        self,
        image_id: str,
        signature: dict[str, Any],
        label: str | None = None,
    ) -> None:
        """Record an image's identity signature; preserve an existing label."""
        payload = json.dumps(signature, separators=(",", ":"), default=list)
        with self.connect() as conn:
            existing = conn.execute(
                "SELECT label, created_at FROM image_registry WHERE image_id = ?",
                (image_id,),
            ).fetchone()
            if existing is None:
                label_value = label or ""
                created_at = _now()
            else:
                label_value = existing["label"] if label is None else label
                created_at = existing["created_at"]
            conn.execute(
                """INSERT INTO image_registry
                   (image_id, label, signature, layout_key, text_key, text_count, created_at)
                   VALUES (?,?,?,?,?,?,?)
                   ON CONFLICT(image_id) DO UPDATE SET
                     label = excluded.label,
                     signature = excluded.signature,
                     layout_key = excluded.layout_key,
                     text_key = excluded.text_key,
                     text_count = excluded.text_count""",
                (
                    image_id,
                    label_value,
                    payload,
                    str(signature.get("layout_key", "")),
                    str(signature.get("text_key", "")),
                    int(signature.get("text_count", 0)),
                    created_at,
                ),
            )

    def set_image_label(self, image_id: str, label: str) -> bool:
        with self.connect() as conn:
            cursor = conn.execute(
                "UPDATE image_registry SET label = ? WHERE image_id = ?",
                (label, image_id),
            )
            return cursor.rowcount > 0

    def get_image_registry(self, image_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM image_registry WHERE image_id = ?", (image_id,)
            ).fetchone()
        return self._registry_row(row) if row else None

    def list_image_registry(
        self, limit: int = 100, offset: int = 0
    ) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM image_registry ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()
        return [self._registry_row(r) for r in rows]

    @staticmethod
    def _registry_row(row: sqlite3.Row) -> dict[str, Any]:
        data = dict(row)
        try:
            data["signature"] = json.loads(data.get("signature") or "{}")
        except json.JSONDecodeError:
            data["signature"] = {}
        return data

    # -------------------------------------------------------------- evidence
    def upsert_evidence(self, evidence: list[Any], job_id: str | None = None) -> None:
        if not evidence:
            return
        rows = []
        now = _now()
        for item in evidence:
            bbox = item.bbox
            rows.append(
                (
                    item.evidence_id, item.image_id, job_id, item.kind.value, item.label,
                    bbox.x0 if bbox else None, bbox.y0 if bbox else None,
                    bbox.x1 if bbox else None, bbox.y1 if bbox else None,
                    item.confidence, json.dumps(item.attributes, default=str),
                    item.provenance.module, item.provenance.method,
                    item.provenance.version, int(item.observed), item.scope, now,
                )
            )
        with self.connect() as conn:
            conn.executemany(
                """INSERT OR REPLACE INTO evidence
                   (evidence_id, image_id, job_id, kind, label, x0, y0, x1, y1,
                    confidence, attributes, module, method, version, observed, scope, created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                rows,
            )

    def query_evidence(
        self,
        image_id: str,
        kind: str | None = None,
        text_contains: str | None = None,
        region: list[float] | None = None,
        min_confidence: float | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[dict[str, Any]], int]:
        where = ["image_id = ?"]
        params: list[Any] = [image_id]
        if kind:
            where.append("kind = ?")
            params.append(kind)
        if min_confidence is not None:
            where.append("(confidence IS NULL OR confidence >= ?)")
            params.append(min_confidence)
        if text_contains:
            where.append("(LOWER(label) LIKE ? OR LOWER(attributes) LIKE ?)")
            needle = f"%{text_contains.lower()}%"
            params.extend([needle, needle])
        if region:
            x0, y0, x1, y1 = region
            where.append("(x0 IS NOT NULL AND x1 >= ? AND x0 <= ? AND y1 >= ? AND y0 <= ?)")
            params.extend([x0, x1, y0, y1])
        clause = " AND ".join(where)
        with self.connect() as conn:
            total = int(conn.execute(f"SELECT COUNT(*) FROM evidence WHERE {clause}", params).fetchone()[0])
            rows = conn.execute(
                f"SELECT * FROM evidence WHERE {clause} ORDER BY "
                "CASE kind WHEN 'text' THEN 0 WHEN 'shape' THEN 1 WHEN 'object' THEN 2 "
                "WHEN 'relationship' THEN 3 ELSE 4 END, "
                "COALESCE(y0, 1e12), COALESCE(x0, 1e12) LIMIT ? OFFSET ?",
                [*params, limit, offset],
            ).fetchall()
        return [self._evidence_row(r) for r in rows], total

    def get_evidence(self, evidence_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM evidence WHERE evidence_id = ?", (evidence_id,)).fetchone()
        return self._evidence_row(row) if row else None

    def all_evidence(self, image_id: str) -> list[dict[str, Any]]:
        items, _ = self.query_evidence(image_id, limit=5000)
        return items

    def delete_evidence(
        self, image_id: str, modules: list[str] | None = None, scope: str | None = None
    ) -> None:
        clauses = ["image_id = ?"]
        params: list[Any] = [image_id]
        if modules:
            clauses.append("module IN (" + ",".join("?" for _ in modules) + ")")
            params.extend(modules)
        if scope:
            clauses.append("scope = ?")
            params.append(scope)
        with self.connect() as conn:
            conn.execute("DELETE FROM evidence WHERE " + " AND ".join(clauses), params)

    @staticmethod
    def _evidence_row(row: sqlite3.Row) -> dict[str, Any]:
        data = dict(row)
        data["attributes"] = json.loads(data.get("attributes") or "{}")
        data["observed"] = bool(data.get("observed", 1))
        if data.get("x0") is not None:
            data["bbox"] = [data["x0"], data["y0"], data["x1"], data["y1"]]
        else:
            data["bbox"] = None
        for key in ("x0", "y0", "x1", "y1"):
            data.pop(key, None)
        return data

    # --------------------------------------------------------------- caching
    def get_cache(self, cache_key: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT payload FROM analyses WHERE cache_key = ?", (cache_key,)
            ).fetchone()
        return json.loads(row[0]) if row else None

    def put_cache(self, cache_key: str, image_id: str, tool: str, payload: dict[str, Any]) -> None:
        with self.connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO analyses (cache_key, image_id, tool, payload, created_at) VALUES (?,?,?,?,?)",
                (cache_key, image_id, tool, json.dumps(payload, default=str), _now()),
            )

    def invalidate_cache(self, image_id: str) -> None:
        with self.connect() as conn:
            conn.execute("DELETE FROM analyses WHERE image_id = ?", (image_id,))

    # --------------------------------------------------------------- sessions
    def create_session(self, image_id: str | None, agent: str = "unknown", meta: dict | None = None) -> str:
        session_id = "ses_" + __import__("secrets").token_hex(8)
        now = _now()
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO sessions (session_id, image_id, agent, created_at, updated_at, meta) VALUES (?,?,?,?,?,?)",
                (session_id, image_id, agent, now, now, json.dumps(meta or {})),
            )
        return session_id

    def touch_session(self, session_id: str, image_id: str | None = None) -> None:
        with self.connect() as conn:
            if image_id:
                conn.execute(
                    "UPDATE sessions SET updated_at = ?, image_id = COALESCE(image_id, ?) WHERE session_id = ?",
                    (_now(), image_id, session_id),
                )
            else:
                conn.execute("UPDATE sessions SET updated_at = ? WHERE session_id = ?", (_now(), session_id))

    def find_session_for_image(self, image_id: str, agent: str = "unknown") -> str | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT session_id FROM sessions WHERE image_id = ? ORDER BY created_at DESC LIMIT 1",
                (image_id,),
            ).fetchone()
        return row[0] if row else None

    def list_sessions(self, image_id: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        with self.connect() as conn:
            if image_id:
                rows = conn.execute(
                    "SELECT * FROM sessions WHERE image_id = ? ORDER BY updated_at DESC LIMIT ?",
                    (image_id, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM sessions ORDER BY updated_at DESC LIMIT ?", (limit,)
                ).fetchall()
        result = []
        for row in rows:
            data = dict(row)
            data["meta"] = json.loads(data.get("meta") or "{}")
            result.append(data)
        return result

    def get_session(self, session_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM sessions WHERE session_id = ?", (session_id,)).fetchone()
        if not row:
            return None
        data = dict(row)
        data["meta"] = json.loads(data.get("meta") or "{}")
        return data

    # ------------------------------------------------------------------- jobs
    def create_job(self, image_id: str, tool: str, tasks: list[str]) -> str:
        job_id = "job_" + __import__("secrets").token_hex(8)
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO jobs (job_id, image_id, tool, tasks, status, created_at, started_at) VALUES (?,?,?,?,?,?,?)",
                (job_id, image_id, tool, json.dumps(tasks), "running", _now(), _now()),
            )
        return job_id

    def finish_job(self, job_id: str, status: str, duration_ms: float, error: str | None = None) -> None:
        with self.connect() as conn:
            conn.execute(
                "UPDATE jobs SET status = ?, finished_at = ?, duration_ms = ?, error = ? WHERE job_id = ?",
                (status, _now(), duration_ms, error, job_id),
            )

    def list_jobs(self, image_id: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        with self.connect() as conn:
            if image_id:
                rows = conn.execute(
                    "SELECT * FROM jobs WHERE image_id = ? ORDER BY created_at DESC LIMIT ?",
                    (image_id, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?", (limit,)
                ).fetchall()
        result = []
        for row in rows:
            data = dict(row)
            data["tasks"] = json.loads(data.get("tasks") or "[]")
            result.append(data)
        return result

    # ------------------------------------------------------------ inspections
    def record_inspection(
        self,
        image_id: str,
        tool: str,
        request: dict[str, Any],
        summary: str,
        evidence_count: int,
        session_id: str | None = None,
    ) -> str:
        inspection_id = "insp_" + __import__("secrets").token_hex(8)
        with self.connect() as conn:
            conn.execute(
                """INSERT INTO inspections
                   (inspection_id, session_id, image_id, tool, request, summary, evidence_count, created_at)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (
                    inspection_id, session_id, image_id, tool,
                    json.dumps(request, default=str), summary, evidence_count, _now(),
                ),
            )
        return inspection_id

    def list_inspections(self, image_id: str, limit: int = 50) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM inspections WHERE image_id = ? ORDER BY created_at DESC LIMIT ?",
                (image_id, limit),
            ).fetchall()
        result = []
        for row in rows:
            data = dict(row)
            data["request"] = json.loads(data.get("request") or "{}")
            result.append(data)
        return result
