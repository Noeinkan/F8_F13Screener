"""Tests for src/core/diff.py — pure functions, no I/O."""
import pytest
from src.core.diff import compute_portfolio_diff, _fmt_value, format_diff_for_telegram, MAX_ITEMS_PER_SECTION


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
