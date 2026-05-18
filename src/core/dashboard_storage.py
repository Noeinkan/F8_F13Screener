"""
DuckDB-backed storage for dashboard analytics data.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from pathlib import Path
from typing import Dict, List, Optional

import duckdb
import pandas as pd

logger = logging.getLogger(__name__)


class DashboardStorage:
    """DuckDB storage used by historical processing and Streamlit dashboard."""

    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self._init_database()

    @contextmanager
    def _get_connection(self):
        conn = duckdb.connect(str(self.db_path))
        try:
            yield conn
        finally:
            conn.close()

    def _init_database(self):
        with self._get_connection() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS holdings (
                    id BIGINT,
                    filing_date VARCHAR NOT NULL,
                    fund_name VARCHAR NOT NULL,
                    fund_cik VARCHAR,
                    accession_number VARCHAR,
                    filing_url VARCHAR,
                    issuer_name VARCHAR,
                    share_class VARCHAR,
                    cusip VARCHAR,
                    figi VARCHAR,
                    value_x1000 VARCHAR,
                    value_usd BIGINT,
                    shares_raw VARCHAR,
                    shares BIGINT,
                    sh_prn VARCHAR,
                    put_call VARCHAR,
                    investment_discretion VARCHAR,
                    other_manager VARCHAR,
                    other_managers_raw VARCHAR,
                    all_columns_raw VARCHAR,
                    voting_authority_sole BIGINT,
                    voting_authority_shared BIGINT,
                    voting_authority_none BIGINT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_dash_accession ON holdings(accession_number)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_dash_fund_date ON holdings(fund_name, filing_date)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_dash_cusip ON holdings(cusip)")

    def clear_holdings(self) -> int:
        with self._get_connection() as conn:
            deleted = conn.execute("SELECT COUNT(*) FROM holdings").fetchone()[0]
            conn.execute("DELETE FROM holdings")
            logger.info("Cleared %s rows from dashboard DB", deleted)
            return int(deleted)

    def save_holdings(
        self,
        holdings: List[Dict],
        fund_name: str,
        fund_cik: str,
        filing_date: str,
        accession_number: str,
        filing_url: str,
    ) -> int:
        if not holdings:
            return 0

        filing_date_clean = filing_date.split("T")[0] if "T" in filing_date else filing_date

        rows = []
        for holding in holdings:
            rows.append(
                (
                    None,
                    filing_date_clean,
                    fund_name,
                    fund_cik,
                    accession_number,
                    filing_url,
                    holding.get("issuer_name", ""),
                    holding.get("share_class", ""),
                    holding.get("cusip", ""),
                    holding.get("figi", ""),
                    holding.get("value_x1000", ""),
                    holding.get("value"),
                    holding.get("shares_raw", ""),
                    holding.get("shares"),
                    holding.get("sh_prn", ""),
                    holding.get("put_call", ""),
                    holding.get("investment_discretion", ""),
                    holding.get("other_manager", ""),
                    holding.get("other_managers_raw", ""),
                    holding.get("all_columns_raw", ""),
                    holding.get("voting_authority_sole"),
                    holding.get("voting_authority_shared"),
                    holding.get("voting_authority_none"),
                )
            )

        with self._get_connection() as conn:
            if accession_number:
                conn.execute("DELETE FROM holdings WHERE accession_number = ?", [accession_number])
            conn.executemany(
                """
                INSERT INTO holdings (
                    id, filing_date, fund_name, fund_cik, accession_number, filing_url,
                    issuer_name, share_class, cusip, figi, value_x1000, value_usd,
                    shares_raw, shares, sh_prn, put_call, investment_discretion,
                    other_manager, other_managers_raw, all_columns_raw,
                    voting_authority_sole, voting_authority_shared, voting_authority_none
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )

        logger.info("Saved %s holdings rows into dashboard DB", len(rows))
        return len(rows)

    def query_df(self, sql: str, params: tuple = ()) -> pd.DataFrame:
        with self._get_connection() as conn:
            return conn.execute(sql, list(params)).df()

    def replace_holdings_from_dataframe(self, holdings_df: pd.DataFrame) -> int:
        if holdings_df.empty:
            self.clear_holdings()
            return 0

        with self._get_connection() as conn:
            conn.register("seed_holdings_df", holdings_df)
            conn.execute("DELETE FROM holdings")
            conn.execute(
                """
                INSERT INTO holdings (
                    id, filing_date, fund_name, fund_cik, accession_number, filing_url,
                    issuer_name, share_class, cusip, figi, value_x1000, value_usd,
                    shares_raw, shares, sh_prn, put_call, investment_discretion,
                    other_manager, other_managers_raw, all_columns_raw,
                    voting_authority_sole, voting_authority_shared, voting_authority_none
                )
                SELECT
                    NULL AS id,
                    filing_date,
                    fund_name,
                    fund_cik,
                    accession_number,
                    filing_url,
                    issuer_name,
                    share_class,
                    cusip,
                    figi,
                    value_x1000,
                    value_usd,
                    shares_raw,
                    shares,
                    sh_prn,
                    put_call,
                    investment_discretion,
                    other_manager,
                    other_managers_raw,
                    all_columns_raw,
                    voting_authority_sole,
                    voting_authority_shared,
                    voting_authority_none
                FROM seed_holdings_df
                """
            )
            inserted = conn.execute("SELECT COUNT(*) FROM holdings").fetchone()[0]
            conn.unregister("seed_holdings_df")
        return int(inserted)

    def export_holdings_to_csv(self, output_path: Path) -> int:
        df = self.query_df(
            """
            SELECT
                filing_date AS "Filing Date",
                fund_name AS "Fund Name",
                fund_cik AS "Fund CIK",
                accession_number AS "Accession Number",
                filing_url AS "Filing URL",
                issuer_name AS "Name of Issuer",
                share_class AS "Title of Class",
                cusip AS "CUSIP",
                figi AS "FIGI",
                value_x1000 AS "Value Raw ($000s)",
                value_usd AS "Value ($000s)",
                shares_raw AS "Shares/Principal Amount Raw",
                shares AS "Shares/Principal Amount",
                sh_prn AS "SH/PRN",
                put_call AS "Put/Call",
                investment_discretion AS "Investment Discretion",
                other_manager AS "Other Manager",
                other_managers_raw AS "Other Managers (raw)",
                all_columns_raw AS "All Columns (raw)",
                voting_authority_sole AS "Voting Authority - Sole",
                voting_authority_shared AS "Voting Authority - Shared",
                voting_authority_none AS "Voting Authority - None"
            FROM holdings
            ORDER BY filing_date DESC, fund_name, issuer_name
            """
        )
        if df.empty:
            return 0
        output_path.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(output_path, index=False)
        return len(df)

    def export_latest_snapshot_to_csv(self, output_path: Path) -> int:
        df = self.query_df(
            """
            WITH latest_filing AS (
                SELECT fund_name, MAX(filing_date) AS filing_date
                FROM holdings
                GROUP BY fund_name
            )
            SELECT
                h.fund_name AS "Fund Name",
                h.fund_cik AS "Fund CIK",
                h.filing_date AS "Filing Date",
                h.accession_number AS "Accession Number",
                h.issuer_name AS "Name of Issuer",
                h.share_class AS "Title of Class",
                h.cusip AS "CUSIP",
                h.value_usd AS "Value ($000s)",
                h.shares AS "Shares/Principal Amount",
                h.put_call AS "Put/Call"
            FROM holdings h
            INNER JOIN latest_filing latest
                ON h.fund_name = latest.fund_name
               AND h.filing_date = latest.filing_date
            ORDER BY h.fund_name, h.value_usd DESC NULLS LAST, h.issuer_name
            """
        )
        if df.empty:
            return 0
        output_path.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(output_path, index=False)
        return len(df)

    def get_missing_value_filings(self, limit: Optional[int] = None) -> List[Dict[str, str]]:
        query = """
            SELECT
                accession_number,
                MAX(fund_name) AS fund_name,
                MAX(filing_date) AS filing_date,
                MAX(filing_url) AS filing_url,
                COUNT(*) AS row_count
            FROM holdings
            WHERE TRIM(COALESCE(accession_number, '')) <> ''
              AND TRIM(COALESCE(filing_url, '')) <> ''
            GROUP BY accession_number
            HAVING SUM(
                CASE
                    WHEN value_usd IS NOT NULL OR TRIM(COALESCE(value_x1000, '')) <> '' THEN 1
                    ELSE 0
                END
            ) = 0
            ORDER BY MAX(filing_date) DESC, MAX(fund_name)
        """
        if limit is not None:
            query += " LIMIT ?"
            df = self.query_df(query, (limit,))
        else:
            df = self.query_df(query)
        return df.to_dict("records")

    def get_health_snapshot(self) -> Dict[str, int | bool]:
        stats = self.query_df(
            """
            SELECT
                COUNT(*) AS total_rows,
                COUNT(DISTINCT fund_name) AS distinct_funds,
                COUNT(DISTINCT accession_number) AS distinct_accessions
            FROM holdings
            """
        )
        if stats.empty:
            return {
                "total_rows": 0,
                "distinct_funds": 0,
                "distinct_accessions": 0,
                "only_all_fund": False,
            }

        row = stats.iloc[0]
        non_all = self.query_df(
            """
            SELECT COUNT(*) AS non_all_rows
            FROM holdings
            WHERE TRIM(COALESCE(fund_name, '')) <> ''
              AND UPPER(TRIM(fund_name)) <> 'ALL'
            """
        )
        non_all_rows = int(non_all.iloc[0]["non_all_rows"]) if not non_all.empty else 0
        total_rows = int(row["total_rows"])
        return {
            "total_rows": total_rows,
            "distinct_funds": int(row["distinct_funds"]),
            "distinct_accessions": int(row["distinct_accessions"]),
            "only_all_fund": total_rows > 0 and non_all_rows == 0,
        }
