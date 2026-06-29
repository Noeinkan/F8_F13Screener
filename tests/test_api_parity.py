"""Phase 5 API parity tests — response shapes for dashboard routes."""

from __future__ import annotations

from fastapi.testclient import TestClient

from src.api.app import create_app

client = TestClient(create_app())

OVERVIEW_FUNDS_KEYS = {
    "has_data",
    "has_portfolio_values",
    "summary",
    "recent_activity",
    "funds",
    "chart",
    "value_multiplier_summary",
}

HOLDINGS_SEARCH_KEYS = {
    "query",
    "total_matches",
    "funds_count",
    "issuers_count",
    "latest_filing",
    "value_multiplier_summary",
    "latest_by_fund",
    "all_rows",
    "truncated",
}

CONSENSUS_SECTION_KEYS = {"chart", "rows", "columns"}
CONSENSUS_METADATA_KEYS = {
    "funds",
    "quarters",
    "latest_quarter",
    "movement_rows",
    "value_multiplier_summary",
}

COMPARE_PAYLOAD_KEYS = {
    "fund",
    "old_accession",
    "new_accession",
    "counts",
    "diff",
    "highlights",
    "top_movers",
    "formatted_diff",
}


def _first_fund_name() -> str | None:
    response = client.get("/api/funds")
    if response.status_code != 200:
        return None
    funds = response.json().get("funds") or []
    return funds[0] if funds else None


def test_api_overview_funds_shape():
    response = client.get("/api/overview/funds")
    assert response.status_code in {200, 503}
    if response.status_code != 200:
        return

    payload = response.json()
    assert OVERVIEW_FUNDS_KEYS.issubset(payload.keys())
    assert isinstance(payload["funds"], list)
    assert isinstance(payload["chart"], dict)
    assert "title" in payload["chart"]
    assert "x" in payload["chart"]
    assert "y" in payload["chart"]


def test_api_overview_funds_filter_param():
    response = client.get("/api/overview/funds", params={"filter": "AQR"})
    assert response.status_code in {200, 503}
    if response.status_code != 200:
        return

    funds = response.json()["funds"]
    assert all("AQR" in row["Fund"] for row in funds)


def test_api_admin_statistics_shape():
    response = client.get("/api/admin/statistics")
    assert response.status_code in {200, 503}
    if response.status_code != 200:
        return

    payload = response.json()
    assert set(payload.keys()) == {"available", "row"}
    assert isinstance(payload["available"], bool)


def test_api_holdings_search_shape():
    response = client.get("/api/holdings/search", params={"q": "apple"})
    assert response.status_code in {200, 400, 503}
    if response.status_code != 200:
        return

    payload = response.json()
    assert HOLDINGS_SEARCH_KEYS.issubset(payload.keys())
    assert payload["query"] == "apple"
    assert isinstance(payload["issuers_count"], int)
    assert isinstance(payload["funds_count"], int)
    assert isinstance(payload["latest_by_fund"], list)
    assert isinstance(payload["all_rows"], list)
    assert isinstance(payload["truncated"], bool)


def test_api_holdings_search_rejects_blank_query():
    response = client.get("/api/holdings/search", params={"q": "   "})
    assert response.status_code in {400, 422, 503}


def test_api_holdings_search_export_returns_csv():
    response = client.get("/api/holdings/search/export", params={"q": "apple"})
    assert response.status_code in {200, 400, 503}
    if response.status_code != 200:
        return

    assert response.headers["content-type"].startswith("text/csv")
    assert "attachment" in response.headers.get("content-disposition", "").lower()
    assert "f8_13f_search" in response.headers.get("content-disposition", "")


def test_api_fund_compare_formatted_payload_shape():
    fund = _first_fund_name()
    if fund is None:
        response = client.get("/api/funds/UnknownFund/compare")
        assert response.status_code in {200, 400, 503}
        return

    response = client.get(f"/api/funds/{fund}/compare")
    assert response.status_code in {200, 400, 503}
    if response.status_code != 200:
        return

    payload = response.json()
    assert COMPARE_PAYLOAD_KEYS.issubset(payload.keys())
    assert set(payload["counts"].keys()) == {"new", "closed", "increased", "decreased"}
    assert len(payload["highlights"]) == 4
    assert "rows" in payload["top_movers"]
    formatted = payload["formatted_diff"]
    assert {
        "new_positions",
        "closed_positions",
        "share_changes",
        "has_any",
    }.issubset(formatted.keys())
    for section_key in ("new_positions", "closed_positions", "share_changes"):
        section = formatted[section_key]
        assert "count" in section
        assert "rows" in section


def test_api_compare_sankey_accepts_scale_params_with_real_fund():
    fund = _first_fund_name() or "UnknownFund"
    response = client.get(
        f"/api/funds/{fund}/compare/charts/sankey",
        params={
            "top_n_buys": 10,
            "top_n_sells": 10,
            "scale_mode": "sqrt",
            "min_visible_pct": 1.0,
        },
    )
    assert response.status_code in {200, 400, 503}
    if response.status_code != 200:
        return

    payload = response.json()
    assert "node" in payload
    assert "link" in payload
    assert payload.get("scale_mode") == "sqrt"
    assert payload.get("min_visible_pct") == 1.0


def test_api_consensus_trends_shape():
    response = client.get(
        "/api/consensus/trends",
        params={"lookback_quarters": 4, "min_funds": 2, "top_n": 20},
    )
    assert response.status_code in {200, 503}
    if response.status_code != 200:
        return

    payload = response.json()
    assert set(payload.keys()) == {
        "metadata",
        "accumulation",
        "distribution",
        "weight_growth",
        "latest_consensus",
    }
    assert CONSENSUS_METADATA_KEYS.issubset(payload["metadata"].keys())
    for section_key in (
        "accumulation",
        "distribution",
        "weight_growth",
        "latest_consensus",
    ):
        section = payload[section_key]
        assert CONSENSUS_SECTION_KEYS.issubset(section.keys())
        assert isinstance(section["rows"], list)
        assert isinstance(section["columns"], list)
        chart = section["chart"]
        assert {"title", "x", "y", "labels"}.issubset(chart.keys())


def test_api_consensus_trends_export_validates_section():
    response = client.get("/api/consensus/trends/export", params={"section": "not-real"})
    assert response.status_code in {400, 422, 503}


def test_api_consensus_trends_export_returns_csv():
    response = client.get(
        "/api/consensus/trends/export",
        params={"section": "accumulation", "lookback_quarters": 4},
    )
    assert response.status_code in {200, 503}
    if response.status_code != 200:
        return

    assert response.headers["content-type"].startswith("text/csv")
    assert "f8_13f_consensus_accumulation" in response.headers.get(
        "content-disposition", ""
    )
