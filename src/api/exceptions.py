"""API-layer exceptions."""


class DashboardDbError(Exception):
    """Raised when the dashboard DuckDB cannot be opened or queried."""

    def __init__(self, message: str, *, recovery_hint: str | None = None):
        super().__init__(message)
        self.recovery_hint = recovery_hint or (
            "Verify DB integrity, rebuild with "
            "`python -m src.cli.process_historical_13f full --yes`, then restart the API."
        )
