"""Tests for src/api/static_site.py — serving the built UI and its cache headers."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api import static_site

IMMUTABLE = "public, max-age=31536000, immutable"


@pytest.fixture
def dist(tmp_path, monkeypatch):
    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text(
        '<!doctype html><script type="module" src="/assets/index-abc123.js"></script>',
        encoding="utf-8",
    )
    (tmp_path / "assets" / "index-abc123.js").write_text("console.log('app')", encoding="utf-8")
    (tmp_path / "favicon.svg").write_text("<svg/>", encoding="utf-8")
    monkeypatch.setenv("F8_STATIC_DIR", str(tmp_path))
    return tmp_path


@pytest.fixture
def client(dist):
    app = FastAPI()

    @app.get("/api/health")
    def health():
        return {"status": "ok"}

    assert static_site.mount_frontend(app) is not None
    return TestClient(app)


def test_not_mounted_without_static_dir(monkeypatch):
    monkeypatch.delenv("F8_STATIC_DIR", raising=False)
    assert static_site.mount_frontend(FastAPI()) is None


def test_hashed_assets_are_immutable(client):
    response = client.get("/assets/index-abc123.js")
    assert response.status_code == 200
    assert response.headers["cache-control"] == IMMUTABLE


def test_index_revalidates(client):
    response = client.get("/")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-cache"
    assert "index-abc123.js" in response.text


def test_spa_fallback_serves_index_and_revalidates(client):
    response = client.get("/fund-analysis?cik=0001234567")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-cache"
    assert "index-abc123.js" in response.text


def test_missing_asset_falls_back_without_year_long_cache(client):
    response = client.get("/assets/index-OLDHASH.js")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-cache"


def test_other_root_files_keep_default_caching(client):
    response = client.get("/favicon.svg")
    assert response.status_code == 200
    assert "cache-control" not in response.headers


def test_not_modified_keeps_cache_policy(client):
    first = client.get("/assets/index-abc123.js")
    again = client.get("/assets/index-abc123.js", headers={"If-None-Match": first.headers["etag"]})
    assert again.status_code == 304
    assert again.headers["cache-control"] == IMMUTABLE

    index = client.get("/")
    again = client.get("/", headers={"If-None-Match": index.headers["etag"]})
    assert again.status_code == 304
    assert again.headers["cache-control"] == "no-cache"


def test_api_paths_are_not_answered_with_the_shell(client):
    assert client.get("/api/health").json() == {"status": "ok"}
    assert client.get("/api/does-not-exist").status_code == 404
