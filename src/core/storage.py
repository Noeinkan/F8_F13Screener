"""
Storage layer using SQLite for holdings and metadata
"""
import sqlite3
import json
import logging
from pathlib import Path
from typing import List, Dict, Set, Optional
from datetime import datetime, timedelta
from contextlib import contextmanager

logger = logging.getLogger(__name__)


class Storage:
    """SQLite-based storage for 13F filings and holdings"""

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._init_database()

    def _init_database(self):
        """Initialize database schema"""
        with self._get_connection() as conn:
            cursor = conn.cursor()

            # Table for tracking seen filings
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS seen_filings (
                    entry_id TEXT PRIMARY KEY,
                    filer_name TEXT NOT NULL,
                    cik TEXT,
                    filing_date TEXT,
                    acceptance_datetime TEXT,
                    processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    matched BOOLEAN DEFAULT 0
                )
            """)

            # Table for holdings data
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS holdings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    filing_date TEXT NOT NULL,
                    fund_name TEXT NOT NULL,
                    fund_cik TEXT,
                    accession_number TEXT,
                    filing_url TEXT,
                    acceptance_datetime TEXT,
                    issuer_name TEXT,
                    share_class TEXT,
                    cusip TEXT,
                    figi TEXT,
                    value_x1000 TEXT,
                    value_usd INTEGER,
                    shares_raw TEXT,
                    shares INTEGER,
                    sh_prn TEXT,
                    put_call TEXT,
                    investment_discretion TEXT,
                    other_manager TEXT,
                    other_managers_raw TEXT,
                    all_columns_raw TEXT,
                    voting_authority_sole INTEGER,
                    voting_authority_shared INTEGER,
                    voting_authority_none INTEGER,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            self._ensure_table_columns(cursor, 'holdings', {
                'value_x1000': 'TEXT',
                'shares_raw': 'TEXT',
                'other_managers_raw': 'TEXT',
                'all_columns_raw': 'TEXT',
                'acceptance_datetime': 'TEXT',
            })

            self._ensure_table_columns(cursor, 'seen_filings', {
                'acceptance_datetime': 'TEXT',
            })

            # Create indexes for performance
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_holdings_fund_cik
                ON holdings(fund_cik, filing_date)
            """)

            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_holdings_cusip
                ON holdings(cusip, filing_date)
            """)

            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_holdings_accession
                ON holdings(accession_number)
            """)

            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_holdings_fund_name_date
                ON holdings(fund_name, filing_date)
            """)

            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_seen_filings_date
                ON seen_filings(filing_date)
            """)

            # Table for statistics
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS statistics (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    total_checked INTEGER DEFAULT 0,
                    matched INTEGER DEFAULT 0,
                    filtered INTEGER DEFAULT 0,
                    last_match_date TEXT,
                    last_update TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Insert default statistics row if not exists
            cursor.execute("""
                INSERT OR IGNORE INTO statistics (id, total_checked, matched, filtered)
                VALUES (1, 0, 0, 0)
            """)

            conn.commit()
            logger.info("Database initialized successfully")

    def _ensure_table_columns(self, cursor, table_name: str, columns: Dict[str, str]):
        """Add newly required columns to existing SQLite tables."""
        cursor.execute(f"PRAGMA table_info({table_name})")
        existing_columns = {row['name'] for row in cursor.fetchall()}

        for column_name, column_type in columns.items():
            if column_name not in existing_columns:
                cursor.execute(
                    f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}"
                )

    @contextmanager
    def _get_connection(self):
        """Context manager for database connections"""
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def get_seen_filings(self, limit: int = 500) -> Set[str]:
        """
        Get set of recently seen filing IDs

        Args:
            limit: Maximum number of IDs to return

        Returns:
            Set of filing entry IDs
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT entry_id FROM seen_filings
                ORDER BY processed_at DESC
                LIMIT ?
            """, (limit,))

            return {row['entry_id'] for row in cursor.fetchall()}

    def mark_filing_seen(
        self,
        entry_id: str,
        filer_name: str,
        cik: str,
        filing_date: str,
        acceptance_datetime: Optional[str] = None,
        matched: bool = False
    ):
        """
        Mark a filing as seen

        Args:
            entry_id: Unique filing entry ID
            filer_name: Name of the filer
            cik: CIK number
            filing_date: Filing date
            matched: Whether this filing matched our filters
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO seen_filings
                (entry_id, filer_name, cik, filing_date, acceptance_datetime, matched, processed_at)
                VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            """, (entry_id, filer_name, cik, filing_date, acceptance_datetime, matched))
            conn.commit()

    def save_holdings(
        self,
        holdings: List[Dict],
        fund_name: str,
        fund_cik: str,
        filing_date: str,
        accession_number: str,
        filing_url: str,
        acceptance_datetime: Optional[str] = None,
    ) -> int:
        """
        Save holdings to database

        Args:
            holdings: List of holdings dictionaries
            fund_name: Name of the fund
            fund_cik: CIK of the fund
            filing_date: Filing date
            accession_number: Filing accession number
            filing_url: URL to the filing

        Returns:
            Number of holdings saved
        """
        if not holdings:
            return 0

        # Clean filing date (remove timestamp if present)
        filing_date_clean = filing_date.split('T')[0] if 'T' in filing_date else filing_date

        with self._get_connection() as conn:
            cursor = conn.cursor()

            if accession_number:
                cursor.execute("DELETE FROM holdings WHERE accession_number = ?", (accession_number,))

            for holding in holdings:
                cursor.execute("""
                    INSERT INTO holdings (
                        filing_date, fund_name, fund_cik, accession_number, filing_url,
                        acceptance_datetime,
                        issuer_name, share_class, cusip, figi, value_x1000, value_usd,
                        shares_raw, shares, sh_prn, put_call, investment_discretion,
                        other_manager, other_managers_raw, all_columns_raw,
                        voting_authority_sole, voting_authority_shared, voting_authority_none
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    filing_date_clean,
                    fund_name,
                    fund_cik,
                    accession_number,
                    filing_url,
                    acceptance_datetime,
                    holding.get('issuer_name', ''),
                    holding.get('share_class', ''),
                    holding.get('cusip', ''),
                    holding.get('figi', ''),
                    holding.get('value_x1000', ''),
                    holding.get('value'),
                    holding.get('shares_raw', ''),
                    holding.get('shares'),
                    holding.get('sh_prn', ''),
                    holding.get('put_call', ''),
                    holding.get('investment_discretion', ''),
                    holding.get('other_manager', ''),
                    holding.get('other_managers_raw', ''),
                    holding.get('all_columns_raw', ''),
                    holding.get('voting_authority_sole'),
                    holding.get('voting_authority_shared'),
                    holding.get('voting_authority_none')
                ))

            conn.commit()
            logger.info(f"Salvate {len(holdings)} holdings nel database")
            return len(holdings)

    def update_statistics(
        self,
        total_checked: int = 0,
        matched: int = 0,
        filtered: int = 0
    ):
        """
        Update processing statistics

        Args:
            total_checked: Number of filings checked
            matched: Number of filings matched
            filtered: Number of filings filtered out
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()

            # Update statistics
            cursor.execute("""
                UPDATE statistics SET
                    total_checked = total_checked + ?,
                    matched = matched + ?,
                    filtered = filtered + ?,
                    last_match_date = CASE WHEN ? > 0 THEN CURRENT_TIMESTAMP ELSE last_match_date END,
                    last_update = CURRENT_TIMESTAMP
                WHERE id = 1
            """, (total_checked, matched, filtered, matched))

            conn.commit()

    def get_statistics(self) -> Dict:
        """
        Get processing statistics

        Returns:
            Dictionary with statistics
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM statistics WHERE id = 1")
            row = cursor.fetchone()

            if row:
                return dict(row)
            else:
                return {
                    'total_checked': 0,
                    'matched': 0,
                    'filtered': 0,
                    'last_match_date': None
                }

    def get_filtered_filings_by_date(self, date: str) -> List[Dict]:
        """
        Get filtered filings for a specific date

        Args:
            date: Date in YYYY-MM-DD format

        Returns:
            List of filtered filing dictionaries
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT entry_id, filer_name, cik, filing_date
                FROM seen_filings
                WHERE matched = 0
                AND DATE(filing_date) = ?
                ORDER BY filing_date DESC
            """, (date,))

            return [dict(row) for row in cursor.fetchall()]

    def get_daily_summary_dates(self) -> List[str]:
        """
        Get dates that need daily summaries sent

        Returns:
            List of dates (YYYY-MM-DD format)
        """
        yesterday = (datetime.now().date() - timedelta(days=1)).isoformat()

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT DISTINCT DATE(filing_date) as date
                FROM seen_filings
                WHERE matched = 0
                AND DATE(filing_date) <= ?
                ORDER BY date
            """, (yesterday,))

            return [row['date'] for row in cursor.fetchall()]

    def export_holdings_to_csv(self, output_path: Path):
        """
        Export all holdings to CSV file (for backward compatibility)

        Args:
            output_path: Path to CSV output file
        """
        return self._export_query_to_csv(
            output_path,
            """
                SELECT
                    filing_date as "Filing Date",
                    fund_name as "Fund Name",
                    fund_cik as "Fund CIK",
                    accession_number as "Accession Number",
                    filing_url as "Filing URL",
                    issuer_name as "Name of Issuer",
                    share_class as "Title of Class",
                    cusip as "CUSIP",
                    figi as "FIGI",
                    value_x1000 as "Value Raw ($000s)",
                    value_usd as "Value ($000s)",
                    shares_raw as "Shares/Principal Amount Raw",
                    shares as "Shares/Principal Amount",
                    sh_prn as "SH/PRN",
                    put_call as "Put/Call",
                    investment_discretion as "Investment Discretion",
                    other_manager as "Other Manager",
                    other_managers_raw as "Other Managers (raw)",
                    all_columns_raw as "All Columns (raw)",
                    voting_authority_sole as "Voting Authority - Sole",
                    voting_authority_shared as "Voting Authority - Shared",
                    voting_authority_none as "Voting Authority - None"
                FROM holdings
                ORDER BY filing_date DESC, fund_name, issuer_name
            """
        )

    def export_latest_snapshot_to_csv(self, output_path: Path) -> int:
        """Export the latest filing snapshot for each fund to CSV."""
        return self._export_query_to_csv(
            output_path,
            """
                WITH latest_filing AS (
                    SELECT fund_name, MAX(filing_date) AS filing_date
                    FROM holdings
                    GROUP BY fund_name
                )
                SELECT
                    h.fund_name as "Fund Name",
                    h.fund_cik as "Fund CIK",
                    h.filing_date as "Filing Date",
                    h.accession_number as "Accession Number",
                    h.issuer_name as "Name of Issuer",
                    h.share_class as "Title of Class",
                    h.cusip as "CUSIP",
                    h.value_usd as "Value ($000s)",
                    h.shares as "Shares/Principal Amount",
                    h.put_call as "Put/Call"
                FROM holdings h
                INNER JOIN latest_filing latest
                    ON h.fund_name = latest.fund_name
                   AND h.filing_date = latest.filing_date
                ORDER BY h.fund_name, h.value_usd DESC NULLS LAST, h.issuer_name
            """
        )

    def _export_query_to_csv(self, output_path: Path, sql: str, params: tuple = ()) -> int:
        import csv

        output_path.parent.mkdir(parents=True, exist_ok=True)

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(sql, params)
            rows = cursor.fetchall()

            if not rows:
                return 0

            with open(output_path, 'w', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=rows[0].keys())
                writer.writeheader()
                for row in rows:
                    writer.writerow(dict(row))

        logger.info(f"Exported {len(rows)} rows to {output_path}")
        return len(rows)

    def cleanup_old_filings(self, days: int = 90):
        """
        Clean up old seen filings to keep database size manageable

        Args:
            days: Number of days to retain
        """
        cutoff_date = (datetime.now() - timedelta(days=days)).isoformat()

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                DELETE FROM seen_filings
                WHERE processed_at < ?
            """, (cutoff_date,))

            deleted = cursor.rowcount
            conn.commit()

            if deleted > 0:
                logger.info(f"Cleaned up {deleted} old filing records")

    def clear_holdings(self) -> int:
        """Delete all holdings rows and return the number removed."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM holdings")
            deleted = cursor.rowcount
            conn.commit()
            logger.info(f"Cleared {deleted} holdings rows from database")
            return deleted

    def get_latest_accessions_for_fund(self, fund_cik: str, limit: int = 2) -> List[Dict]:
        """Return the most recent accession numbers for a fund, newest first."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT DISTINCT accession_number, filing_date
                FROM holdings
                WHERE fund_cik = ?
                ORDER BY filing_date DESC
                LIMIT ?
            """, (fund_cik, limit))
            return [dict(row) for row in cursor.fetchall()]

    def get_holdings_by_accession(self, accession_number: str) -> Dict[str, Dict]:
        """Return holdings as dict keyed by CUSIP for a given accession number."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT cusip, issuer_name, shares, value_usd, share_class
                FROM holdings
                WHERE accession_number = ?
            """, (accession_number,))
            result = {}
            for row in cursor.fetchall():
                cusip = row['cusip']
                if cusip:
                    result[cusip] = {
                        'issuer_name': row['issuer_name'],
                        'shares': row['shares'],
                        'value_usd': row['value_usd'],
                        'share_class': row['share_class'],
                    }
            return result

    def has_holdings_for_accession(self, accession_number: str) -> bool:
        """Return True when at least one holdings row exists for the accession."""
        if not accession_number:
            return False

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT 1
                FROM holdings
                WHERE accession_number = ?
                LIMIT 1
                """,
                (accession_number,),
            )
            return cursor.fetchone() is not None
