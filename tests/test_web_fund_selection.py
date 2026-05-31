"""Tests for dashboard fund selection defaults."""

from src.web.fund_selection import get_default_fund, initialize_default_fund_selection


def test_default_fund_prefers_sec_berkshire_name():
    funds = [
        "AQR Capital Management",
        "Berkshire Hathaway (Warren Buffett)",
        "BERKSHIRE HATHAWAY INC",
    ]

    assert get_default_fund(funds) == "BERKSHIRE HATHAWAY INC"


def test_default_fund_uses_config_berkshire_name_when_sec_name_absent():
    funds = ["AQR Capital Management", "Berkshire Hathaway (Warren Buffett)"]

    assert get_default_fund(funds) == "Berkshire Hathaway (Warren Buffett)"


def test_initialize_default_fund_selection_keeps_valid_existing_choice():
    state = {"selected_fund": "AQR Capital Management"}
    funds = ["AQR Capital Management", "BERKSHIRE HATHAWAY INC"]

    initialize_default_fund_selection(state, "selected_fund", funds)

    assert state["selected_fund"] == "AQR Capital Management"


def test_initialize_default_fund_selection_replaces_missing_choice_with_berkshire():
    state = {"selected_fund": "Missing Fund"}
    funds = ["AQR Capital Management", "BERKSHIRE HATHAWAY INC"]

    initialize_default_fund_selection(state, "selected_fund", funds)

    assert state["selected_fund"] == "BERKSHIRE HATHAWAY INC"