"""Tests for src/core/filing_rollup.py -- value units and amendment folding (pure rules)."""

import math

import pytest

from src.core.filing_rollup import (
    KIND_NEW_HOLDINGS,
    KIND_ORIGINAL,
    KIND_RESTATEMENT,
    choose_value_multiplier,
    compute_effective_filings,
    normalize_amendment_type,
)

PERIOD = "2026-03-31"


def _filing(
    accession,
    filing_date,
    *,
    form_type="13F-HR",
    period=PERIOD,
    amendment_type=None,
    row_count=100,
    acceptance_datetime=None,
):
    return {
        "accession_number": accession,
        "filing_date": filing_date,
        "acceptance_datetime": acceptance_datetime,
        "form_type": form_type,
        "period_of_report": period,
        "amendment_type": amendment_type,
        "row_count": row_count,
    }


def _effective(result):
    return sorted(accession for accession, rollup in result.items() if rollup.is_effective)


# ---------------------------------------------------------------------------
# choose_value_multiplier
# ---------------------------------------------------------------------------


class TestChooseValueMultiplier:

    def test_thousands_when_implied_price_is_tiny(self):
        # $0.05 "per share" is $50 once read as thousands.
        assert choose_value_multiplier(0.05, "2020-05-15") == 1000

    def test_dollars_when_implied_price_is_plausible(self):
        assert choose_value_multiplier(15.0, "2020-05-15") == 1

    def test_median_wins_over_the_date(self):
        # A filer still sending thousands after the SEC switched to dollars.
        assert choose_value_multiplier(0.04, "2024-02-14") == 1000

    def test_date_decides_without_a_median(self):
        assert choose_value_multiplier(None, "2022-11-14") == 1000
        assert choose_value_multiplier(None, "2023-01-03") == 1
        assert choose_value_multiplier(math.nan, "2023-02-14T00:00:00") == 1
        assert choose_value_multiplier(None, None) == 1000

    def test_tie_in_log_space_goes_to_dollars(self):
        assert choose_value_multiplier(math.sqrt(10), "2020-01-01") == 1


# ---------------------------------------------------------------------------
# compute_effective_filings
# ---------------------------------------------------------------------------


class TestComputeEffectiveFilings:

    def test_null_periods_keep_every_filing_as_its_own_portfolio(self):
        result = compute_effective_filings([
            _filing("A1", "2026-05-15", period=None),
            _filing("A2", "2026-05-20", period=None, form_type="13F-HR/A", row_count=3),
            _filing("A3", "2026-05-21", period=None, form_type="13F-HR/A", amendment_type="RESTATEMENT"),
        ])

        assert _effective(result) == ["A1", "A2", "A3"]
        assert {rollup.anchor_accession for rollup in result.values()} == {"A1", "A2", "A3"}
        assert result["A2"].anchor_filing_date == "2026-05-20"

    def test_null_form_type_counts_as_original(self):
        result = compute_effective_filings([_filing("A1", "2026-05-15", form_type=None)])

        assert result["A1"].kind == KIND_ORIGINAL
        assert result["A1"].is_effective

    def test_new_holdings_amendment_joins_the_original(self):
        result = compute_effective_filings([
            _filing("NH", "2026-05-20", form_type="13F-HR/A", amendment_type="NEW HOLDINGS", row_count=2),
            _filing("O", "2026-05-15"),
        ])

        assert _effective(result) == ["NH", "O"]
        assert result["NH"].kind == KIND_NEW_HOLDINGS
        assert result["NH"].anchor_accession == "O"
        assert result["NH"].anchor_filing_date == "2026-05-15"

    def test_restatement_replaces_the_original(self):
        result = compute_effective_filings([
            _filing("O", "2026-05-15"),
            _filing("R", "2026-06-01", form_type="13F-HR/A", amendment_type="RESTATEMENT"),
        ])

        assert _effective(result) == ["R"]
        assert result["O"].anchor_accession == "R"
        assert result["R"].anchor_filing_date == "2026-06-01"

    def test_restatement_after_new_holdings_supersedes_both(self):
        result = compute_effective_filings([
            _filing("O", "2026-05-15"),
            _filing("NH1", "2026-05-20", form_type="13F-HR/A", amendment_type="NEW HOLDINGS", row_count=2),
            _filing("R", "2026-06-01", form_type="13F-HR/A", amendment_type="RESTATEMENT"),
            _filing("NH2", "2026-06-10", form_type="13F-HR/A", amendment_type="NEW HOLDINGS", row_count=1),
        ])

        assert _effective(result) == ["NH2", "R"]
        assert result["NH2"].anchor_accession == "R"
        assert not result["NH1"].is_effective

    def test_amendment_without_original(self):
        new_holdings_only = compute_effective_filings([
            _filing("NH1", "2026-05-20", form_type="13F-HR/A", amendment_type="NEW HOLDINGS", row_count=2),
            _filing("NH2", "2026-05-21", form_type="13F-HR/A", amendment_type="NEW HOLDINGS", row_count=3),
        ])
        assert _effective(new_holdings_only) == ["NH1", "NH2"]
        assert new_holdings_only["NH1"].anchor_accession == "NH1"
        assert new_holdings_only["NH2"].anchor_accession == "NH2"

        restatement_only = compute_effective_filings([
            _filing("R", "2026-06-01", form_type="13F-HR/A", amendment_type="RESTATEMENT"),
            _filing("NH", "2026-06-02", form_type="13F-HR/A", amendment_type="NEW HOLDINGS", row_count=1),
        ])
        assert _effective(restatement_only) == ["NH", "R"]
        assert restatement_only["NH"].anchor_accession == "R"

    def test_unknown_amendment_type_small_filing_is_new_holdings(self):
        result = compute_effective_filings([
            _filing("O", "2026-05-15", row_count=100),
            _filing("A", "2026-05-20", form_type="13F-HR/A", row_count=49),
        ])

        assert result["A"].kind == KIND_NEW_HOLDINGS
        assert _effective(result) == ["A", "O"]
        assert result["A"].anchor_accession == "O"

    def test_unknown_amendment_type_large_filing_is_restatement(self):
        # Exactly half is not "less than half".
        result = compute_effective_filings([
            _filing("O", "2026-05-15", row_count=100),
            _filing("A", "2026-05-20", form_type="13F-HR/A", row_count=50),
        ])

        assert result["A"].kind == KIND_RESTATEMENT
        assert _effective(result) == ["A"]

    def test_unknown_amendment_compares_with_largest_earlier_base(self):
        result = compute_effective_filings([
            _filing("O", "2026-05-15", row_count=200),
            _filing("R", "2026-05-20", form_type="13F-HR/A", amendment_type="RESTATEMENT", row_count=40),
            # 60 rows: more than half of R (40) but less than half of O (200).
            _filing("A", "2026-05-25", form_type="13F-HR/A", row_count=60),
        ])

        assert result["A"].kind == KIND_NEW_HOLDINGS
        assert _effective(result) == ["A", "R"]

    def test_unknown_amendment_without_base_is_restatement(self):
        result = compute_effective_filings([
            _filing("A", "2026-05-20", form_type="13F-HR/A", row_count=1),
        ])

        assert result["A"].kind == KIND_RESTATEMENT
        assert _effective(result) == ["A"]

    def test_order_uses_acceptance_datetime_then_accession(self):
        result = compute_effective_filings([
            # Same filing date; acceptance time says R came after O.
            _filing("Z-O", "2026-05-15", acceptance_datetime="2026-05-15T09:00:00"),
            _filing("A-R", "2026-05-15", form_type="13F-HR/A", amendment_type="RESTATEMENT",
                    acceptance_datetime="2026-05-15T17:00:00"),
        ])
        assert _effective(result) == ["A-R"]

        tie = compute_effective_filings([
            _filing("0002", "2026-05-15"),
            _filing("0001", "2026-05-15"),
        ])
        # Two originals for one period: the later accession is the anchor.
        assert _effective(tie) == ["0002"]

    def test_periods_are_grouped_separately(self):
        result = compute_effective_filings([
            _filing("Q4", "2026-02-14", period="2025-12-31"),
            _filing("Q1", "2026-05-15", period="2026-03-31"),
        ])

        assert _effective(result) == ["Q1", "Q4"]

    def test_filing_with_no_stored_rows_never_anchors(self):
        result = compute_effective_filings([
            _filing("O", "2026-05-15", row_count=100),
            _filing("R", "2026-06-01", form_type="13F-HR/A", amendment_type="RESTATEMENT", row_count=0),
        ])

        assert _effective(result) == ["O"]
        assert result["R"].anchor_accession == "R"

    def test_amendment_type_spellings(self):
        assert normalize_amendment_type(" new holdings ") == "NEW HOLDINGS"
        assert normalize_amendment_type("NEW_HOLDINGS") == "NEW HOLDINGS"
        assert normalize_amendment_type("Restatement") == "RESTATEMENT"
        assert normalize_amendment_type("") is None
        assert normalize_amendment_type(None) is None

    @pytest.mark.parametrize("missing", [None, ""])
    def test_rows_without_accession_are_ignored(self, missing):
        assert compute_effective_filings([_filing(missing, "2026-05-15")]) == {}
