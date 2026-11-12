"""HTTP API smoke tests via FastAPI TestClient."""

from __future__ import annotations

from fastapi.testclient import TestClient

from vi3ion.server.app import app


def _client():
    # Lifespan builds the engine from test settings (env set in conftest).
    with TestClient(app) as client:
        yield client


def test_health():
    for client in _client():
        response = client.get("/api/health")
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ok"
        assert body["coordinate_space"] == "original_pixels"
        assert "ocr" in body


def test_config():
    with TestClient(app) as client:
        response = client.get("/api/config")
        assert response.status_code == 200
        body = response.json()
        assert body["host"] == "127.0.0.1"
        assert "allowed_roots" in body


def _unique_png_bytes() -> bytes:
    import io

    import numpy as np
    from PIL import Image

    array = np.zeros((40, 60, 3), dtype=np.uint8)
    array[:, :] = (90, 130, 180)
    buffer = io.BytesIO()
    Image.fromarray(array).save(buffer, format="PNG")
    return buffer.getvalue()


def test_upload_and_list(sample_ui_bytes):
    with TestClient(app) as client:
        response = client.post(
            "/api/images?analyze=false",
            files={"file": ("unique.png", _unique_png_bytes(), "image/png")},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["image"]["width"] == 60
        assert body["image"]["height"] == 40
        image_id = body["image"]["image_id"]

        listed = client.get("/api/images?limit=10")
        assert listed.status_code == 200
        ids = [item["image_id"] for item in listed.json()["images"]]
        assert image_id in ids

        fetched = client.get(f"/api/images/{image_id}")
        assert fetched.status_code == 200
        assert fetched.json()["image"]["image_id"] == image_id

        got = client.get(f"/api/images/{image_id}/file")
        assert got.status_code == 200
        assert got.headers["content-type"].startswith("image/")

        thumb = client.get(f"/api/images/{image_id}/thumbnail")
        assert thumb.status_code == 200

        deleted = client.delete(f"/api/images/{image_id}")
        assert deleted.status_code == 200
        assert deleted.json()["ok"] is True

        gone = client.get(f"/api/images/{image_id}")
        assert gone.status_code == 404


def test_upload_rejects_non_image():
    with TestClient(app) as client:
        response = client.post(
            "/api/images",
            files={"file": ("fake.txt", b"hello", "text/plain")},
        )
        assert response.status_code == 422


def test_tool_endpoints(sample_ui_bytes):
    with TestClient(app) as client:
        upload = client.post(
            "/api/images?analyze=false",
            files={"file": ("sample.png", sample_ui_bytes, "image/png")},
        )
        image_id = upload.json()["image"]["image_id"]

        catalog = client.get("/api/tools")
        assert catalog.status_code == 200
        names = [t["name"] for t in catalog.json()["tools"]]
        assert set(["inspect_image", "inspect_region", "query_evidence", "verify_claim", "compare_regions"]) <= set(names)

        analy = client.post("/api/tools/inspect_image", json={"image_id": image_id, "detail": "compact"})
        assert analy.status_code == 200
        body = analy.json()
        assert body["ok"] is True
        assert body["tool"] == "inspect_image"
        assert body["image_id"] == image_id

        verify = client.post(
            "/api/tools/verify_claim",
            json={"image_id": image_id, "claim": "The image is 1280x800"},
        )
        assert verify.status_code == 200
        assert verify.json()["verification"]["status"] == "verified"

        query = client.post("/api/tools/query_evidence", json={"image_id": image_id, "kind": "text"})
        assert query.status_code == 200
        assert all(item["kind"] == "text" for item in query.json()["evidence"])


def test_dashboard_mounted():
    with TestClient(app) as client:
        response = client.get("/")
        assert response.status_code == 200
        assert "vi3ion" in response.text.lower() or "root" in response.text.lower()
