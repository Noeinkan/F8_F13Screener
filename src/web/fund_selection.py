"""Shared dashboard fund selection helpers."""

DEFAULT_FUND_CANDIDATES = (
    "BERKSHIRE HATHAWAY INC",
    "Berkshire Hathaway (Warren Buffett)",
)


def get_default_fund(funds: list[str]) -> str:
    for fund in DEFAULT_FUND_CANDIDATES:
        if fund in funds:
            return fund
    return funds[0]


def initialize_default_fund_selection(session_state, key: str, funds: list[str]) -> None:
    if session_state.get(key) not in funds:
        session_state[key] = get_default_fund(funds)