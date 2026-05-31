"""Tests for src/core/diff.py — pure functions, no I/O."""
import math

import pytest
from src.core.diff import (
    MAX_ITEMS_PER_SECTION,
    _fmt_value,
    build_position_key,
    compute_detailed_portfolio_diff,
    compute_portfolio_diff,
    compute_quarterly_history_transitions,
    format_diff_for_telegram,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def make_holding(name, shares, value=None):
    return {"issuer_name": name, "shares": shares, "value_usd": value}


OLD = {
    "AAA": make_holding("Apple",   1_000_000, 100_000),
    "BBB": make_holding("Tesla",     500_000,  50_000),
    "CCC": make_holding("Google",    200_000,  30_000),
}

NEW = {
    "AAA": make_holding("Apple",   1_200_000, 120_000),  # +20% → increased
    "CCC": make_holding("Google",    180_000,  27_000),  # -10% → decreased (exactly at threshold)
    "DDD": make_holding("Nvidia",    100_000,  90_000),  # new
    # BBB removed → closed
}


# ---------------------------------------------------------------------------
# compute_portfolio_diff
# ---------------------------------------------------------------------------

class TestComputePortfolioDiff:

    def test_new_positions_detected(self):
        diff = compute_portfolio_diff(OLD, NEW)
        cusips = [p["cusip"] for p in diff["new_positions"]]
        assert "DDD" in cusips

    def test_closed_positions_detected(self):
        diff = compute_portfolio_diff(OLD, NEW)
        cusips = [p["cusip"] for p in diff["closed_positions"]]
        assert "BBB" in cusips

    def test_increased_detected(self):
        diff = compute_portfolio_diff(OLD, NEW)
        cusips = [p["cusip"] for p in diff["increased"]]
        assert "AAA" in cusips

    def test_decreased_detected(self):
        diff = compute_portfolio_diff(OLD, NEW)
        cusips = [p["cusip"] for p in diff["decreased"]]
        assert "CCC" in cusips

    def test_pct_change_values(self):
        diff = compute_portfolio_diff(OLD, NEW)
        apple = next(p for p in diff["increased"] if p["cusip"] == "AAA")
        assert pytest.approx(apple["pct_change"], rel=1e-3) == 20.0

        google = next(p for p in diff["decreased"] if p["cusip"] == "CCC")
        assert pytest.approx(google["pct_change"], rel=1e-3) == -10.0

    def test_below_threshold_not_reported(self):
        old = {"X": make_holding("Stock", 1000)}
        new = {"X": make_holding("Stock", 1050)}  # +5%, below 10%
        diff = compute_portfolio_diff(old, new)
        assert diff["increased"] == []
        assert diff["decreased"] == []

    def test_exactly_at_threshold_included(self):
        old = {"X": make_holding("Stock", 1000)}
        new = {"X": make_holding("Stock", 1100)}  # exactly +10%
        diff = compute_portfolio_diff(old, new)
        assert len(diff["increased"]) == 1

    def test_zero_old_shares_skipped(self):
        old = {"X": make_holding("Stock", 0)}
        new = {"X": make_holding("Stock", 500)}
        diff = compute_portfolio_diff(old, new)
        assert diff["increased"] == []
        assert diff["decreased"] == []

    def test_empty_portfolios(self):
        diff = compute_portfolio_diff({}, {})
        assert diff == {"new_positions": [], "closed_positions": [], "increased": [], "decreased": []}

    def test_identical_portfolios(self):
        diff = compute_portfolio_diff(OLD, OLD)
        assert diff["new_positions"] == []
        assert diff["closed_positions"] == []
        assert diff["increased"] == []
        assert diff["decreased"] == []

    def test_entirely_new_portfolio(self):
        diff = compute_portfolio_diff({}, NEW)
        assert len(diff["new_positions"]) == len(NEW)
        assert diff["closed_positions"] == []

    def test_entirely_closed_portfolio(self):
        diff = compute_portfolio_diff(OLD, {})
        assert diff["new_positions"] == []
        assert len(diff["closed_positions"]) == len(OLD)

    def test_increased_sorted_descending(self):
        old = {
            "A": make_holding("A", 1000),
            "B": make_holding("B", 1000),
        }
        new = {
            "A": make_holding("A", 1500),  # +50%
            "B": make_holding("B", 1200),  # +20%
        }
        diff = compute_portfolio_diff(old, new)
        pcts = [p["pct_change"] for p in diff["increased"]]
        assert pcts == sorted(pcts, reverse=True)

    def test_decreased_sorted_ascending(self):
        old = {
            "A": make_holding("A", 1000),
            "B": make_holding("B", 1000),
        }
        new = {
            "A": make_holding("A", 500),   # -50%
            "B": make_holding("B", 800),   # -20%
        }
        diff = compute_portfolio_diff(old, new)
        pcts = [p["pct_change"] for p in diff["decreased"]]
        assert pcts == sorted(pcts)

    def test_new_position_carries_issuer_name(self):
        diff = compute_portfolio_diff(OLD, NEW)
        nvidia = next(p for p in diff["new_positions"] if p["cusip"] == "DDD")
        assert nvidia["issuer_name"] == "Nvidia"

    def test_closed_position_carries_old_data(self):
        diff = compute_portfolio_diff(OLD, NEW)
        tesla = next(p for p in diff["closed_positions"] if p["cusip"] == "BBB")
        assert tesla["shares"] == 500_000


class TestDetailedPortfolioDiff:

    def test_cusip_key_keeps_equity_and_options_separate(self):
        equity_key = build_position_key("037833100", "Apple Inc", "COM", "")
        call_key = build_position_key("037833100", "Apple Inc", "COM", "CALL")
        put_key = build_position_key("037833100", "Apple Inc", "COM", "PUT")

        assert len({equity_key, call_key, put_key}) == 3

    def test_position_key_treats_nan_components_as_blank(self):
        key = build_position_key("037833100", "Apple Inc", math.nan, math.nan)

        assert key == "037833100||"

    def test_position_key_falls_back_when_cusip_is_nan(self):
        key = build_position_key(math.nan, "Apple Inc", "COM", math.nan)

        assert key == "Apple Inc|COM"

    def test_same_cusip_equity_and_call_remain_distinct_positions(self):
        equity_key = build_position_key("037833100", "Apple Inc", "COM", "")
        call_key = build_position_key("037833100", "Apple Inc", "COM", "CALL")

        old = {}
        old[equity_key] = {
            "cusip": "037833100",
            "issuer_name": "Apple Inc",
            "share_class": "COM",
            "put_call": "",
            "shares": 100,
            "value_usd": 10,
        }
        old[call_key] = {
            "cusip": "037833100",
            "issuer_name": "Apple Inc",
            "share_class": "COM",
            "put_call": "CALL",
            "shares": 40,
            "value_usd": 4,
        }

        new = {}
        new[equity_key] = {
            "cusip": "037833100",
            "issuer_name": "Apple Inc",
            "share_class": "COM",
            "put_call": "",
            "shares": 130,
            "value_usd": 13,
        }
        new[call_key] = {
            "cusip": "037833100",
            "issuer_name": "Apple Inc",
            "share_class": "COM",
            "put_call": "CALL",
            "shares": 10,
            "value_usd": 1,
        }

        assert len(old) == 2
        assert len(new) == 2

        diff = compute_detailed_portfolio_diff(old, new, min_change_pct=0)

        assert len(diff["increased"]) == 1
        assert diff["increased"][0]["put_call"] in (None, "")
        assert diff["increased"][0]["share_change"] == 30

        assert len(diff["decreased"]) == 1
        assert diff["decreased"][0]["put_call"] == "CALL"
        assert diff["decreased"][0]["share_change"] == -30

    def test_value_deltas_are_included_for_changed_positions(self):
        diff = compute_detailed_portfolio_diff(OLD, NEW)

        apple = next(p for p in diff["increased"] if p["cusip"] == "AAA")
        assert apple["share_change"] == 200_000
        assert apple["old_value_usd"] == 100_000
        assert apple["new_value_usd"] == 120_000
        assert apple["value_change"] == 20_000
        assert pytest.approx(apple["value_pct_change"], rel=1e-3) == 20.0

    def test_blank_cusip_positions_can_still_be_compared(self):
        blank_key = build_position_key("", "Example Corp", "COM", "")
        old = {
            blank_key: {
                "cusip": "",
                "issuer_name": "Example Corp",
                "share_class": "COM",
                "shares": 100,
                "value_usd": 10,
            }
        }
        new = {
            blank_key: {
                "cusip": "",
                "issuer_name": "Example Corp",
                "share_class": "COM",
                "shares": 130,
                "value_usd": 14,
            }
        }

        diff = compute_detailed_portfolio_diff(old, new)

        assert diff["new_positions"] == []
        assert diff["closed_positions"] == []
        assert len(diff["increased"]) == 1
        assert diff["increased"][0]["position_key"] == blank_key


class TestQuarterlyHistoryTransitions:

    def test_consecutive_transitions_are_sorted_by_filing_date(self):
        snapshots = [
            {
                "filing_date": "2025-12-31",
                "accession_number": "2025Q4",
                "positions": {
                    "AAA": make_holding("Apple", 100, 10),
                },
            },
            {
                "filing_date": "2025-09-30",
                "accession_number": "2025Q3",
                "positions": {
                    "AAA": make_holding("Apple", 80, 8),
                    "BBB": make_holding("Tesla", 25, 5),
                },
            },
            {
                "filing_date": "2026-03-31",
                "accession_number": "2026Q1",
                "positions": {
                    "AAA": make_holding("Apple", 120, 12),
                    "CCC": make_holding("Nvidia", 50, 9),
                },
            },
        ]

        transitions = compute_quarterly_history_transitions(snapshots)

        assert len(transitions) == 2
        assert transitions[0]["from_accession_number"] == "2025Q3"
        assert transitions[0]["to_accession_number"] == "2025Q4"
        assert transitions[1]["from_accession_number"] == "2025Q4"
        assert transitions[1]["to_accession_number"] == "2026Q1"

    def test_transition_counts_reflect_each_category(self):
        snapshots = [
            {
                "filing_date": "2025-12-31",
                "accession_number": "2025Q4",
                "positions": {
                    "AAA": make_holding("Apple", 100, 10),
                    "BBB": make_holding("Tesla", 100, 10),
                    "CCC": make_holding("Google", 100, 10),
                },
            },
            {
                "filing_date": "2026-03-31",
                "accession_number": "2026Q1",
                "positions": {
                    "AAA": make_holding("Apple", 130, 14),
                    "CCC": make_holding("Google", 80, 8),
                    "DDD": make_holding("Nvidia", 50, 9),
                },
            },
        ]

        transition = compute_quarterly_history_transitions(snapshots)[0]

        assert transition["new_count"] == 1
        assert transition["closed_count"] == 1
        assert transition["increased_count"] == 1
        assert transition["decreased_count"] == 1


# ---------------------------------------------------------------------------
# _fmt_value
# ---------------------------------------------------------------------------

class TestFmtValue:

    def test_none_returns_empty(self):
        assert _fmt_value(None) == ""

    def test_zero_returns_empty(self):
        assert _fmt_value(0) == ""

    def test_billions(self):
        assert _fmt_value(1_000_000) == "$1.0B"  # 1_000_000 * 1000 = 1B

    def test_millions(self):
        assert _fmt_value(1_000) == "$1.0M"  # 1_000 * 1000 = 1M

    def test_thousands(self):
        assert _fmt_value(5) == "$5k"  # 5 * 1000 = 5k

    def test_below_thousand_dollars(self):
        # value_usd is always integers in thousands, so 1 * 1000 = $1,000 → $1k
        # A truly sub-$1k value can't appear, but the function handles it
        assert "$" in _fmt_value(1)

    def test_multiple_billions(self):
        result = _fmt_value(2_500_000)  # 2.5B
        assert "B" in result
        assert "2.5" in result

    def test_rounding_millions(self):
        result = _fmt_value(1_500)  # 1.5M
        assert "M" in result


# ---------------------------------------------------------------------------
# format_diff_for_telegram
# ---------------------------------------------------------------------------

class TestFormatDiffForTelegram:

    def _empty_diff(self):
        return {"new_positions": [], "closed_positions": [], "increased": [], "decreased": []}

    def test_empty_diff_returns_empty_string(self):
        assert format_diff_for_telegram(self._empty_diff()) == ""

    def test_new_positions_section_present(self):
        diff = self._empty_diff()
        diff["new_positions"] = [
            {"cusip": "AAA", "issuer_name": "Apple", "shares": 100, "value_usd": 5000}
        ]
        result = format_diff_for_telegram(diff)
        assert "NUOVE POSIZIONI" in result
        assert "Apple" in result

    def test_closed_positions_section_present(self):
        diff = self._empty_diff()
        diff["closed_positions"] = [
            {"cusip": "BBB", "issuer_name": "Tesla", "shares": 200, "value_usd": 3000}
        ]
        result = format_diff_for_telegram(diff)
        assert "POSIZIONI CHIUSE" in result
        assert "Tesla" in result

    def test_changes_section_present(self):
        diff = self._empty_diff()
        diff["increased"] = [
            {"cusip": "CCC", "issuer_name": "Nvidia", "old_shares": 100, "new_shares": 150, "pct_change": 50.0}
        ]
        result = format_diff_for_telegram(diff)
        assert "VARIAZIONI" in result
        assert "Nvidia" in result
        assert "↑" in result

    def test_decreased_arrow(self):
        diff = self._empty_diff()
        diff["decreased"] = [
            {"cusip": "DDD", "issuer_name": "Meta", "old_shares": 200, "new_shares": 150, "pct_change": -25.0}
        ]
        result = format_diff_for_telegram(diff)
        assert "↓" in result

    def test_overflow_line_shown(self):
        diff = self._empty_diff()
        diff["new_positions"] = [
            {"cusip": str(i), "issuer_name": f"Stock{i}", "shares": 100, "value_usd": 1000}
            for i in range(MAX_ITEMS_PER_SECTION + 3)
        ]
        result = format_diff_for_telegram(diff)
        assert "altre" in result

    def test_no_overflow_line_when_within_limit(self):
        diff = self._empty_diff()
        diff["new_positions"] = [
            {"cusip": str(i), "issuer_name": f"Stock{i}", "shares": 100, "value_usd": 1000}
            for i in range(MAX_ITEMS_PER_SECTION)
        ]
        result = format_diff_for_telegram(diff)
        assert "altre" not in result

    def test_html_tags_present(self):
        diff = self._empty_diff()
        diff["new_positions"] = [
            {"cusip": "X", "issuer_name": "X Corp", "shares": 50, "value_usd": None}
        ]
        result = format_diff_for_telegram(diff)
        assert "<b>" in result
