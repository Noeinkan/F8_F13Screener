"""Tests for dashboard chart data preparation."""

import math

from src.web.charts import BUY_NODE, SELL_NODE, build_shares_flow_sankey_data


def _link_rows(sankey_data):
    labels = sankey_data["node"]["label"]
    links = sankey_data["link"]
    return [
        {
            "source": labels[source],
            "target": labels[target],
            "value": value,
            "movement": customdata[0],
            "identifier": customdata[1],
            "delta": customdata[4],
            "value_delta": customdata[5],
        }
        for source, target, value, customdata in zip(
            links["source"],
            links["target"],
            links["value"],
            links["customdata"],
        )
    ]


def test_shares_flow_sankey_maps_buys_and_sells_by_share_delta():
    diff = {
        "new_positions": [
            {"issuer_name": "Nvidia", "cusip": "DDD", "shares": 100_000},
        ],
        "closed_positions": [
            {"issuer_name": "Tesla", "cusip": "BBB", "shares": 40_000},
        ],
        "increased": [
            {
                "issuer_name": "Apple",
                "cusip": "AAA",
                "old_shares": 100_000,
                "new_shares": 150_000,
                "share_change": 50_000,
                "value_change": 250,
            },
        ],
        "decreased": [
            {
                "issuer_name": "Microsoft",
                "cusip": "MSFT",
                "old_shares": 210_000,
                "new_shares": 200_000,
                "share_change": -10_000,
            },
        ],
    }

    rows = _link_rows(build_shares_flow_sankey_data(diff))

    assert {
        "source": BUY_NODE,
        "target": "Apple",
        "value": 50_000.0,
        "movement": "Increased",
        "identifier": "AAA",
        "delta": "+50,000",
        "value_delta": "+$250k",
    } in rows
    assert {
        "source": "Microsoft",
        "target": SELL_NODE,
        "value": 10_000.0,
        "movement": "Decreased",
        "identifier": "MSFT",
        "delta": "-10,000",
        "value_delta": "-",
    } in rows
    assert {
        "source": BUY_NODE,
        "target": "Nvidia",
        "value": 100_000.0,
        "movement": "New position",
        "identifier": "DDD",
        "delta": "+100,000",
        "value_delta": "-",
    } in rows
    assert {
        "source": "Tesla",
        "target": SELL_NODE,
        "value": 40_000.0,
        "movement": "Closed position",
        "identifier": "BBB",
        "delta": "-40,000",
        "value_delta": "-",
    } in rows


def test_shares_flow_sankey_limits_to_top_n_by_absolute_delta():
    diff = {
        "new_positions": [],
        "closed_positions": [],
        "increased": [
            {
                "issuer_name": f"Stock {index}",
                "cusip": f"CUSIP{index}",
                "old_shares": 1_000,
                "new_shares": 1_000 + index,
                "share_change": index,
            }
            for index in range(1, 26)
        ],
        "decreased": [],
    }

    sankey_data = build_shares_flow_sankey_data(diff, top_n=20)

    assert len(sankey_data["movements"]) == 20
    assert sankey_data["movements"][0]["delta_shares"] == 25.0
    assert sankey_data["movements"][-1]["delta_shares"] == 6.0
    assert "Stock 5" not in sankey_data["node"]["label"]
    assert "Stock 6" in sankey_data["node"]["label"]


def test_shares_flow_sankey_ignores_nan_label_components():
    diff = {
        "new_positions": [],
        "closed_positions": [],
        "increased": [
            {
                "issuer_name": "Apple",
                "cusip": "AAA",
                "share_class": "COM",
                "put_call": math.nan,
                "old_shares": 100,
                "new_shares": 150,
                "share_change": 50,
            },
        ],
        "decreased": [],
    }

    sankey_data = build_shares_flow_sankey_data(diff)

    assert "Apple (COM)" in sankey_data["node"]["label"]