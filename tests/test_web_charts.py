"""Tests for dashboard chart data preparation."""

import math

from src.web.charts import (
    BUY_NODE,
    SELL_NODE,
    build_shares_change_lane_data,
    build_shares_flow_sankey_data,
    scale_shares_flow_values,
)


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


def test_shares_flow_sankey_limits_buys_and_sells_independently():
    diff = {
        "new_positions": [],
        "closed_positions": [],
        "increased": [
            {
                "issuer_name": f"Buy {index}",
                "cusip": f"BUY{index}",
                "old_shares": 1_000,
                "new_shares": 1_000 + index,
                "share_change": index,
            }
            for index in range(1, 6)
        ],
        "decreased": [
            {
                "issuer_name": f"Sell {index}",
                "cusip": f"SELL{index}",
                "old_shares": 1_000,
                "new_shares": 1_000 - index,
                "share_change": -index,
            }
            for index in range(1, 6)
        ],
    }

    sankey_data = build_shares_flow_sankey_data(diff, top_n_buys=2, top_n_sells=3)

    assert len(sankey_data["movements"]) == 5
    assert [movement["label"] for movement in sankey_data["movements"]] == [
        "Buy 5",
        "Buy 4",
        "Sell 5",
        "Sell 4",
        "Sell 3",
    ]
    assert "Buy 3" not in sankey_data["node"]["label"]
    assert "Sell 3" in sankey_data["node"]["label"]


def test_shares_flow_scale_modes_are_display_only():
    values = [100.0, 10_000.0]

    assert scale_shares_flow_values(values, scale_mode="linear") == values
    assert scale_shares_flow_values(values, scale_mode="sqrt") == [10.0, 100.0]
    assert scale_shares_flow_values(values, scale_mode="log") == [math.log1p(100.0), math.log1p(10_000.0)]
    assert scale_shares_flow_values(values, scale_mode="sqrt", min_visible_pct=20) == [20.0, 100.0]


def test_shares_change_lanes_show_new_and_closed_position_endpoints():
    diff = {
        "new_positions": [
            {"issuer_name": "Newco", "cusip": "NEW", "shares": 25_000},
        ],
        "closed_positions": [
            {"issuer_name": "Oldco", "cusip": "OLD", "shares": 10_000},
        ],
        "increased": [],
        "decreased": [],
    }

    lanes_df = build_shares_change_lane_data(diff)
    rows = lanes_df.set_index("Position").to_dict("index")

    assert rows["Newco"]["Previous Shares"] == 0.0
    assert rows["Newco"]["New Shares"] == 25_000.0
    assert rows["Oldco"]["Previous Shares"] == 10_000.0
    assert rows["Oldco"]["New Shares"] == 0.0


def test_shares_change_lanes_encode_each_movement_distinctly():
    diff = {
        "new_positions": [
            {"issuer_name": "Newco", "cusip": "NEW", "shares": 25_000},
        ],
        "closed_positions": [
            {"issuer_name": "Oldco", "cusip": "OLD", "shares": 10_000},
        ],
        "increased": [
            {
                "issuer_name": "Upco",
                "cusip": "UP",
                "old_shares": 4_000,
                "new_shares": 8_000,
                "share_change": 4_000,
            },
        ],
        "decreased": [
            {
                "issuer_name": "Downco",
                "cusip": "DOWN",
                "old_shares": 9_000,
                "new_shares": 6_000,
                "share_change": -3_000,
            },
        ],
    }

    lanes_df = build_shares_change_lane_data(diff)
    styles = lanes_df.set_index("Movement")[["Marker Color", "Marker Symbol", "Line Dash"]].to_dict("index")

    assert set(styles) == {"New position", "Closed position", "Increased", "Decreased"}
    assert len({style["Marker Color"] for style in styles.values()}) == 4
    assert len({style["Marker Symbol"] for style in styles.values()}) == 4


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


def test_shares_flow_sankey_excludes_options_by_default():
    diff = {
        "new_positions": [
            {
                "issuer_name": "Apple",
                "cusip": "AAA",
                "share_class": "COM",
                "put_call": "CALL",
                "shares": 50,
            },
            {
                "issuer_name": "Nvidia",
                "cusip": "DDD",
                "shares": 100_000,
            },
        ],
        "closed_positions": [
            {
                "issuer_name": "Tesla",
                "cusip": "BBB",
                "put_call": "PUT",
                "shares": 40_000,
            },
        ],
        "increased": [
            {
                "issuer_name": "Microsoft",
                "cusip": "MSFT",
                "put_call": "CALL",
                "old_shares": 1_000,
                "new_shares": 2_000,
                "share_change": 1_000,
            },
            {
                "issuer_name": "Amazon",
                "cusip": "AMZN",
                "old_shares": 100_000,
                "new_shares": 150_000,
                "share_change": 50_000,
            },
        ],
        "decreased": [
            {
                "issuer_name": "Meta",
                "cusip": "META",
                "put_call": "PUT",
                "old_shares": 10_000,
                "new_shares": 9_000,
                "share_change": -1_000,
            },
        ],
    }

    sankey_data = build_shares_flow_sankey_data(diff)

    labels = sankey_data["node"]["label"]
    assert "Apple (COM CALL)" not in labels
    assert "Tesla (PUT)" not in labels
    assert "Microsoft (CALL)" not in labels
    assert "Meta (PUT)" not in labels
    assert "Nvidia" in labels
    assert "Amazon" in labels
    movement_labels = [movement["label"] for movement in sankey_data["movements"]]
    assert set(movement_labels) == {"Nvidia", "Amazon"}


def test_shares_flow_sankey_includes_options_when_requested():
    diff = {
        "new_positions": [
            {
                "issuer_name": "Apple",
                "cusip": "AAA",
                "share_class": "COM",
                "put_call": "CALL",
                "shares": 50,
            },
        ],
        "closed_positions": [],
        "increased": [],
        "decreased": [],
    }

    sankey_data = build_shares_flow_sankey_data(diff, include_options=True)

    movement_labels = [movement["label"] for movement in sankey_data["movements"]]
    assert "Apple (COM CALL)" in movement_labels