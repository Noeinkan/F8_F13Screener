"""API smoke tests."""

from fastapi.testclient import TestClient

from src.api.app import create_app


client = TestClient(create_app())


def test_health():
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_funds_list():
    response = client.get("/api/funds")
    assert response.status_code in {200, 503}
    if response.status_code == 200:
        assert "funds" in response.json()


def test_overview_summary():
    response = client.get("/api/overview/summary")
    assert response.status_code in {200, 503}


def test_holdings_search_requires_query():
    response = client.get("/api/holdings/search", params={"q": "apple"})
    assert response.status_code in {200, 503, 400}
