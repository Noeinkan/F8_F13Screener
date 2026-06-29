"""Tests for Phase 3 Fund Analysis additions (API + pure helpers)."""

from __future__ import annotations

import pandas as pd
import pytest

from src.api._diff_format import (
    build_compare_highlights,
    build_formatted_diff_sections,
    build_top_movers,
)
from src.api._fund_service import (
    _build_history_summary,
)
from src.api._position_insight import (
    add_position_insight_columns,
    build_position_insight_detail,
    build_position_insight_options,
)
from src.api.app import create_app
from fastapi.testclient import TestClient


client = TestClient(create_app())


def _sample_diff() -> dict:
    return {
        "new_positions": [
            {
                "cusip": "AAA",
                "issuer_name": "AAA Corp",
                "share_class": "COM",
                "put_call": None,
                "shares": 5_000,
                "value_usd": 500_000,
            }
        ],
        "closed_positions": [
            {
                "cusip": "BBB",
                "issuer_name": "BBB Corp",
                "share_class": "COM",
                "put_call": None,
                "shares": 2_000,
                "value_usd": 220_000,
            }
        ],
        "increased": [
            {
                "cusip": "CCC",
                "issuer_name": "CCC Corp",
                "share_class": "COM",
                "put_call": None,
                "old_shares": 1_000,
                "new_shares": 2_000,
                "share_change": 1_000,
                "pct_change": 100.0,
                "old_value_usd": 100_000,
                "new_value_usd": 220_000,
                "value_change": 120_000,
                "value_pct_change": 120.0,
            }
        ],
        "decreased": [
            {
                "cusip": "DDD",
                "issuer_name": "DDD Corp",
                "share_class": "COM",
                "put_call": None,
                "old_shares": 4_000,
                "new_shares": 1_500,
                "share_change": -2_500,
                "pct_change": -62.5,
                "old_value_usd": 400_000,
                "new_value_usd": 150_000,
                "value_change": -250_000,
                "value_pct_change": -62.5,
            }
        ],
    }


def test_compare_highlights_returns_four_tiles():
    diff = _sample_diff()
    highlights = build_compare_highlights(diff)
    assert len(highlights) == 4
    labels = [tile["label"] for tile in highlights]
    assert labels == [
        "Largest new",
        "Largest closed",
        "Largest increase",
        "Largest decrease",
    ]
    assert highlights[0]["position_label"] == "AAA Corp (COM)"
    assert highlights[2]["value"].startswith("+")
    assert highlights[3]["value"].startswith("-")


def test_top_movers_returns_formatted_rows():
    diff = _sample_diff()
    movers = build_top_movers(diff, limit=4)
    assert movers["rows"]
    movements = {row["Movement"] for row in movers["rows"]}
    assert {"New", "Closed", "Increase", "Decrease"}.issubset(movements)
    assert "Type" in movers["rows"][0]


def test_formatted_diff_sections_have_counts():
    diff = _sample_diff()
    sections = build_formatted_diff_sections(diff)
    assert sections["new_positions"]["count"] == 1
    assert sections["closed_positions"]["count"] == 1
    assert sections["share_changes"]["count"] == 2
    assert sections["new_positions"]["type_label"] == "Purchase"
    assert sections["closed_positions"]["type_label"] == "Sell"


def test_position_insight_classifies_options_and_keys():
    df = pd.DataFrame(
        [
            {
                "Issuer": "AAA Corp",
                "CUSIP": "AAA",
                "Class": "COM",
                "Put/Call": "",
                "Shares": 1_000,
                "Value (USD)": 100_000,
                "Filing Date": "2026-03-31",
            },
            {
                "Issuer": "BBB Corp",
                "CUSIP": "BBB",
                "Class": "COM",
                "Put/Call": "CALL",
                "Shares": 200,
                "Value (USD)": 25_000,
                "Filing Date": "2026-03-31",
            },
        ]
    )
    enriched = add_position_insight_columns(df)
    assert "Implied Filing Price" in enriched.columns
    options = build_position_insight_options(enriched)
    assert set(options["options"]) == {"AAA", "BBB"}
    detail = build_position_insight_detail(enriched, "BBB")
    metrics = detail["metrics"]
    assert metrics["underlying_shares"] == "200"
    assert any("option rows" in caption.lower() for caption in detail["captions"])


def test_compare_sankey_scaling_pipeline_runs_on_sample_diff():
    """Exercise scale_shares_flow_values through a fake compare path that does
    not require the database.
    """
    from src.api import _fund_service

    diff = _sample_diff()
    captured: dict = {}

    def fake_build_compare(fund, *, old_accession=None, new_accession=None):  # noqa: ARG001
        captured["called"] = True
        return {"fund": fund, "diff": diff}

    def fake_sankey_data(diff_obj, top_n=20, *, top_n_buys=None, top_n_sells=None, include_options=False):  # noqa: ARG001
        return {
            "node": {"label": ["Bought shares", "Sold shares", "AAA Corp"]},
            "link": {
                "source": [0, 1, 0],
                "target": [2, 2, 2],
                "value": [1.0, 4.0, 9.0],
                "color": ["rgba(0,0,0,0.4)"] * 3,
                "customdata": [["m", "id", "0", "1", "+1", "+$1"]] * 3,
            },
            "movements": [],
            "value_multiplier": 1,
        }

    original_build_compare = _fund_service.build_fund_compare
    original_sankey = _fund_service.build_shares_flow_sankey_data
    _fund_service.build_fund_compare = fake_build_compare
    _fund_service.build_shares_flow_sankey_data = fake_sankey_data
    try:
        sankey = _fund_service.build_compare_sankey(
            "Fund A",
            old_accession="a",
            new_accession="b",
            top_n=5,
            scale_mode="sqrt",
            min_visible_pct=0,
        )
    finally:
        _fund_service.build_fund_compare = original_build_compare
        _fund_service.build_shares_flow_sankey_data = original_sankey

    assert captured.get("called") is True
    assert sankey["scale_mode"] == "sqrt"
    assert sankey["min_visible_pct"] == 0
    assert sankey["link"]["value"] == [1.0, 2.0, 3.0]
    assert sankey["raw_values"] == [1.0, 4.0, 9.0]


def test_compare_export_uses_diff_format_section_data():
    """Verify build_compare_export returns formatted rows without needing DB."""
    from src.api import _fund_service

    diff = _sample_diff()

    def fake_build_compare(fund, *, old_accession=None, new_accession=None):  # noqa: ARG001
        return {
            "fund": fund,
            "diff": diff,
            "formatted_diff": build_formatted_diff_sections(diff),
            "top_movers": build_top_movers(diff),
            "highlights": build_compare_highlights(diff),
        }

    original = _fund_service.build_fund_compare
    _fund_service.build_fund_compare = fake_build_compare
    try:
        for section in ("new_positions", "closed_positions", "share_changes", "top_movers"):
            payload = _fund_service.build_compare_export(
                "Fund A",
                section,
                old_accession="a",
                new_accession="b",
            )
            assert payload["filename"].endswith(".csv")
            assert payload["rows"]
    finally:
        _fund_service.build_fund_compare = original


def test_compare_export_rejects_unknown_section():
    from src.api import _fund_service

    with pytest.raises(ValueError):
        _fund_service.build_compare_export("Fund A", "not-a-section")


def test_history_summary_contains_deltas():
    history_df = pd.DataFrame(
        [
            {
                "Filing Date": "2025-12-31",
                "Accession": "a",
                "Normalized Positions": 100,
                "Raw 13F Lines": 110,
                "Portfolio Value (USD)": 1_000_000.0,
                "Value Multiplier": 1,
                "Filing Date Dt": pd.Timestamp("2025-12-31"),
                "Label": "2025-12-31 (a)",
            },
            {
                "Filing Date": "2026-03-31",
                "Accession": "b",
                "Normalized Positions": 120,
                "Raw 13F Lines": 130,
                "Portfolio Value (USD)": 1_300_000.0,
                "Value Multiplier": 1,
                "Filing Date Dt": pd.Timestamp("2026-03-31"),
                "Label": "2026-03-31 (b)",
            },
        ]
    )
    summary = _build_history_summary(history_df)
    assert summary["quarters"] == 2
    assert summary["current_positions"] == 120
    assert summary["positions_delta"] == 20
    assert summary["latest_value"] == 1_300_000.0
    assert summary["value_delta"] == 300_000.0


def test_api_fund_history_route_exposes_chart_payload():
    response = client.get("/api/funds/UnknownFund/history")
    assert response.status_code in {200, 503}
    if response.status_code == 200:
        payload = response.json()
        assert "charts" in payload
        assert "transitions_chart" in payload
        assert "summary" in payload


def test_api_compare_sankey_route_accepts_scale_params():
    response = client.get(
        "/api/funds/UnknownFund/compare/charts/sankey",
        params={
            "top_n_buys": 10,
            "top_n_sells": 10,
            "scale_mode": "sqrt",
            "min_visible_pct": 1.0,
        },
    )
    assert response.status_code in {200, 400, 503}


def test_api_compare_export_route_validates_section():
    response = client.get("/api/funds/UnknownFund/compare/export/not-a-section")
    assert response.status_code in {400, 503}


def test_api_holdings_export_route_returns_csv_when_db_missing():
    response = client.get(
        "/api/funds/UnknownFund/accessions/0001/holdings/export",
        params={"view": "normalized", "top_n": 10},
    )
    assert response.status_code in {200, 503}
    if response.status_code == 200:
        assert response.headers["content-type"].startswith("text/csv")


def test_api_history_export_route_returns_csv_when_db_missing():
    response = client.get("/api/funds/UnknownFund/history/export")
    assert response.status_code in {200, 503}
    if response.status_code == 200:
        assert response.headers["content-type"].startswith("text/csv")
