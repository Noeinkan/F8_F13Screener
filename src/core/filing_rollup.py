"""Per-filing bookkeeping for the dashboard DuckDB: value units and amendments.

The ``holdings`` table stores every Information Table row exactly as the filer
wrote it. Two facts about those rows cannot be read off a single row, and
guessing them at read time gave wrong answers, so they are decided here once
per accession and stored in the ``filings`` table:

* **Value unit.** 13F values were in thousands of dollars until the SEC switched
  to whole dollars in January 2023, and some filers kept sending thousands
  after that. The unit is inferred per filing from the median implied price of
  its plain share rows (``value_multiplier``, 1 or 1000). Bonds (``PRN``, priced
  near $1 per unit of principal) and options are left out of that median: they
  are what made a bond-heavy fund's dollars look like thousands.
* **Amendments.** A ``13F-HR/A`` either restates the whole quarter
  (RESTATEMENT, which replaces the original) or adds a few rows to it
  (NEW HOLDINGS, which is read together with the original). Each filing is
  folded into the portfolio it belongs to: ``anchor_accession`` names that
  portfolio and ``is_effective`` says whether the filing's rows still count.

The ``holdings_effective`` view applies both, so analytics read one row per
effective position line, grouped under the anchor accession, in dollars.

The amendment rules live in :func:`compute_effective_filings`, a pure function;
the rest of this module is the SQL that loads its inputs and stores its output.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

import pandas as pd

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CANDIDATE_VALUE_MULTIPLIERS = (1, 1000)
VALUE_UNIT_TARGET_PRICE = 100.0
# First business day on which the SEC required 13F values in whole dollars.
DOLLAR_VALUES_SINCE = "2023-01-03"

KIND_ORIGINAL = "ORIGINAL"
KIND_RESTATEMENT = "RESTATEMENT"
KIND_NEW_HOLDINGS = "NEW_HOLDINGS"

AMENDMENT_RESTATEMENT = "RESTATEMENT"
AMENDMENT_NEW_HOLDINGS = "NEW HOLDINGS"

# An amendment whose type is unknown is read as NEW HOLDINGS when it is this
# much smaller than the portfolio it amends; otherwise as a restatement.
UNKNOWN_AMENDMENT_NEW_HOLDINGS_RATIO = 0.5

METADATA_FIELDS = (
    "form_type",
    "period_of_report",
    "amendment_type",
    "table_entry_total",
    "table_value_total",
)

# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

FILINGS_TABLE_DDL = """
    CREATE TABLE IF NOT EXISTS filings (
        accession_number VARCHAR PRIMARY KEY,
        fund_name VARCHAR,
        fund_cik VARCHAR,
        filing_date VARCHAR,
        acceptance_datetime VARCHAR,
        form_type VARCHAR,
        period_of_report VARCHAR,
        amendment_type VARCHAR,
        table_entry_total BIGINT,
        table_value_total BIGINT,
        row_count BIGINT,
        value_multiplier INTEGER,
        anchor_accession VARCHAR,
        anchor_filing_date VARCHAR,
        is_effective BOOLEAN,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
"""

HOLDINGS_EFFECTIVE_VIEW = "holdings_effective"

HOLDINGS_EFFECTIVE_VIEW_DDL = f"""
    CREATE VIEW {HOLDINGS_EFFECTIVE_VIEW} AS
    SELECT
        h.* REPLACE (
            f.anchor_accession AS accession_number,
            f.anchor_filing_date AS filing_date,
            h.value_usd * f.value_multiplier AS value_usd
        ),
        h.accession_number AS source_accession_number
    FROM holdings h
    INNER JOIN filings f
        ON f.accession_number = h.accession_number
    WHERE f.is_effective
"""


# ---------------------------------------------------------------------------
# Pure rules
# ---------------------------------------------------------------------------


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and math.isnan(value):
        return ""
    return str(value).strip()


def _score_price_scale(price: float, target_price: float = VALUE_UNIT_TARGET_PRICE) -> float:
    if price <= 0:
        return float("inf")
    return abs(math.log10(price) - math.log10(target_price))


def choose_value_multiplier(median_price: float | None, filing_date: str | None) -> int:
    """Return 1 when a filing's values are dollars, 1000 when they are thousands.

    ``median_price`` is the median of ``value / shares`` over the filing's plain
    share rows. The multiplier that puts that median closest to $100 in log
    space wins (a tie goes to dollars). Without a usable median the SEC's
    cutover date decides.
    """
    if median_price is not None and not (isinstance(median_price, float) and math.isnan(median_price)):
        price = float(median_price)
        if price > 0:
            scored = {
                multiplier: _score_price_scale(price * multiplier)
                for multiplier in CANDIDATE_VALUE_MULTIPLIERS
            }
            return min(scored, key=scored.get)
    date_text = _clean_text(filing_date)[:10]
    if date_text and date_text >= DOLLAR_VALUES_SINCE:
        return 1
    return 1000


def is_amendment(form_type: Any) -> bool:
    return _clean_text(form_type).upper().endswith("/A")


def normalize_amendment_type(value: Any) -> str | None:
    text = " ".join(_clean_text(value).upper().replace("_", " ").split())
    if text in (AMENDMENT_RESTATEMENT, AMENDMENT_NEW_HOLDINGS):
        return text
    return None


@dataclass(frozen=True)
class FilingRollup:
    accession_number: str
    kind: str
    anchor_accession: str
    anchor_filing_date: str | None
    is_effective: bool


def _order_key(filing: Mapping[str, Any]) -> tuple[str, str]:
    moment = _clean_text(filing.get("acceptance_datetime")) or _clean_text(filing.get("filing_date"))
    return moment, _clean_text(filing.get("accession_number"))


def _row_count(filing: Mapping[str, Any]) -> int:
    value = filing.get("row_count")
    try:
        return int(value) if value is not None and not pd.isna(value) else 0
    except (TypeError, ValueError):
        return 0


def _has_rows(filing: Mapping[str, Any]) -> bool:
    # A missing row_count means the caller did not say; only an explicit zero
    # marks a filing whose holdings are not (or no longer) in the database.
    value = filing.get("row_count")
    if value is None or pd.isna(value):
        return True
    return _row_count(filing) > 0


def _classify_group(ordered: Sequence[Mapping[str, Any]]) -> list[str]:
    kinds: list[str] = []
    largest_base = 0
    for filing in ordered:
        if not is_amendment(filing.get("form_type")):
            kind = KIND_ORIGINAL
        else:
            amendment_type = normalize_amendment_type(filing.get("amendment_type"))
            if amendment_type == AMENDMENT_RESTATEMENT:
                kind = KIND_RESTATEMENT
            elif amendment_type == AMENDMENT_NEW_HOLDINGS:
                kind = KIND_NEW_HOLDINGS
            elif largest_base and _row_count(filing) < largest_base * UNKNOWN_AMENDMENT_NEW_HOLDINGS_RATIO:
                kind = KIND_NEW_HOLDINGS
            else:
                kind = KIND_RESTATEMENT
        if kind in (KIND_ORIGINAL, KIND_RESTATEMENT):
            largest_base = max(largest_base, _row_count(filing))
        kinds.append(kind)
    return kinds


def compute_effective_filings(filings: Iterable[Mapping[str, Any]]) -> dict[str, FilingRollup]:
    """Fold one fund's amendments into the portfolios they belong to.

    Each mapping needs ``accession_number`` and may carry ``filing_date``,
    ``acceptance_datetime``, ``form_type``, ``period_of_report``,
    ``amendment_type`` and ``row_count``.

    Filings are grouped by ``period_of_report``; a filing without a period is a
    group of its own, so nothing is folded until the period is known. Within a
    group, in filing order, the last original or restatement is the anchor: it
    and every NEW HOLDINGS amendment filed after it are effective and read as
    one portfolio under the anchor's accession and filing date. Whatever came
    before the anchor has been superseded. A group made only of NEW HOLDINGS
    amendments has nothing to add them to, so each stands as its own portfolio.

    A filing whose ``row_count`` is explicitly 0 has no holdings stored (its
    metadata outlived a wipe, or it was never ingested). It is never effective
    and never anchors, so it cannot hide a portfolio that does have rows.
    """
    groups: dict[object, list[Mapping[str, Any]]] = {}
    for filing in filings:
        accession = _clean_text(filing.get("accession_number"))
        if not accession:
            continue
        period = _clean_text(filing.get("period_of_report"))
        key: object = ("period", period) if period else ("accession", accession)
        groups.setdefault(key, []).append(filing)

    result: dict[str, FilingRollup] = {}
    for members in groups.values():
        ordered_all = sorted(members, key=_order_key)
        for filing in ordered_all:
            if not _has_rows(filing):
                accession = _clean_text(filing.get("accession_number"))
                result[accession] = FilingRollup(
                    accession_number=accession,
                    kind=_classify_group([filing])[0],
                    anchor_accession=accession,
                    anchor_filing_date=_clean_text(filing.get("filing_date")) or None,
                    is_effective=False,
                )

        ordered = [filing for filing in ordered_all if _has_rows(filing)]
        kinds = _classify_group(ordered)
        anchor_index = max(
            (index for index, kind in enumerate(kinds) if kind in (KIND_ORIGINAL, KIND_RESTATEMENT)),
            default=None,
        )

        for index, (filing, kind) in enumerate(zip(ordered, kinds)):
            accession = _clean_text(filing.get("accession_number"))
            if anchor_index is None:
                anchor = filing
                effective = True
            else:
                anchor = ordered[anchor_index]
                effective = index >= anchor_index
            result[accession] = FilingRollup(
                accession_number=accession,
                kind=kind,
                anchor_accession=_clean_text(anchor.get("accession_number")),
                anchor_filing_date=_clean_text(anchor.get("filing_date")) or None,
                is_effective=effective,
            )
    return result


# ---------------------------------------------------------------------------
# DuckDB plumbing (every function takes an open connection)
# ---------------------------------------------------------------------------


def _fund_filter(fund_names: Iterable[str] | None, column: str) -> tuple[str, list[Any]]:
    if fund_names is None:
        return "", []
    names = sorted({str(name) for name in fund_names if name is not None})
    if not names:
        return " AND FALSE", []
    placeholders = ", ".join(["?"] * len(names))
    return f" AND {column} IN ({placeholders})", names


def _view_exists(conn) -> bool:
    row = conn.execute(
        "SELECT 1 FROM duckdb_views() WHERE view_name = ? AND NOT internal LIMIT 1",
        [HOLDINGS_EFFECTIVE_VIEW],
    ).fetchone()
    return row is not None


def ensure_filings_schema(conn) -> None:
    """Create ``filings`` and the view if missing, and register unseen accessions.

    Registering is not limited to an empty table: a writer still running older
    code can add holdings without a ``filings`` row, and those rows would be
    invisible through the view until something registered them.
    """
    conn.execute(FILINGS_TABLE_DDL)
    if not _view_exists(conn):
        conn.execute(HOLDINGS_EFFECTIVE_VIEW_DDL)
    affected = set(sync_filings_from_holdings(conn))
    # Rows whose derived columns were never filled (an interrupted run).
    affected.update(
        row[0]
        for row in conn.execute(
            "SELECT DISTINCT fund_name FROM filings WHERE is_effective IS NULL OR value_multiplier IS NULL"
        ).fetchall()
    )
    if affected:
        refresh_filing_rollup(conn, affected)


def sync_filings_from_holdings(conn) -> list[str]:
    """Insert a ``filings`` row for each holdings accession that has none.

    Returns the fund names that gained rows (their rollup needs recomputing).
    """
    missing = conn.execute(
        """
        SELECT DISTINCT h.accession_number
        FROM holdings h
        WHERE TRIM(COALESCE(h.accession_number, '')) <> ''
          AND NOT EXISTS (
              SELECT 1 FROM filings f WHERE f.accession_number = h.accession_number
          )
        """
    ).fetchall()
    if not missing:
        return []

    conn.execute(
        """
        INSERT INTO filings (accession_number, fund_name, fund_cik, filing_date, acceptance_datetime)
        SELECT
            h.accession_number,
            MAX(h.fund_name),
            MAX(h.fund_cik),
            MAX(h.filing_date),
            MAX(h.acceptance_datetime)
        FROM holdings h
        WHERE TRIM(COALESCE(h.accession_number, '')) <> ''
          AND NOT EXISTS (
              SELECT 1 FROM filings f WHERE f.accession_number = h.accession_number
          )
        GROUP BY h.accession_number
        """
    )
    rows = conn.execute(
        f"""
        SELECT DISTINCT fund_name
        FROM filings
        WHERE accession_number IN ({", ".join(["?"] * len(missing))})
        """,
        [row[0] for row in missing],
    ).fetchall()
    return [row[0] for row in rows]


def upsert_filing(
    conn,
    *,
    accession_number: str,
    fund_name: str,
    fund_cik: str | None,
    filing_date: str | None,
    acceptance_datetime: str | None,
    metadata: Mapping[str, Any] | None = None,
) -> None:
    """Insert or refresh one filing's identity; metadata given as None is kept."""
    metadata = metadata or {}
    values = [metadata.get(field) for field in METADATA_FIELDS]
    conn.execute(
        """
        INSERT INTO filings (
            accession_number, fund_name, fund_cik, filing_date, acceptance_datetime,
            form_type, period_of_report, amendment_type, table_entry_total, table_value_total,
            updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, now())
        ON CONFLICT (accession_number) DO UPDATE SET
            fund_name = excluded.fund_name,
            fund_cik = COALESCE(excluded.fund_cik, filings.fund_cik),
            filing_date = COALESCE(excluded.filing_date, filings.filing_date),
            acceptance_datetime = COALESCE(excluded.acceptance_datetime, filings.acceptance_datetime),
            form_type = COALESCE(excluded.form_type, filings.form_type),
            period_of_report = COALESCE(excluded.period_of_report, filings.period_of_report),
            amendment_type = COALESCE(excluded.amendment_type, filings.amendment_type),
            table_entry_total = COALESCE(excluded.table_entry_total, filings.table_entry_total),
            table_value_total = COALESCE(excluded.table_value_total, filings.table_value_total),
            updated_at = now()
        """,
        [accession_number, fund_name, fund_cik, filing_date, acceptance_datetime, *values],
    )


def update_filing_metadata(conn, records: Iterable[Mapping[str, Any]]) -> tuple[int, set[str]]:
    """Write the non-None metadata fields of each record onto its existing row.

    Returns ``(rows updated, fund names touched)``. Records for accessions with
    no ``filings`` row, or with nothing to write, are skipped.
    """
    updated = 0
    funds: set[str] = set()
    for record in records:
        accession = _clean_text(record.get("accession_number"))
        if not accession:
            continue
        fields = {
            field: record[field]
            for field in METADATA_FIELDS
            if field in record and record[field] is not None
        }
        if not fields:
            continue
        assignments = ", ".join(f"{field} = ?" for field in fields)
        row = conn.execute(
            f"""
            UPDATE filings
            SET {assignments}, updated_at = now()
            WHERE accession_number = ?
            RETURNING fund_name
            """,
            [*fields.values(), accession],
        ).fetchone()
        if row is not None:
            updated += 1
            funds.add(row[0])
    return updated, funds


def refresh_filing_rollup(conn, fund_names: Iterable[str] | None = None) -> None:
    """Recompute row counts, value units and amendment folding.

    ``fund_names`` limits the work to those funds; ``None`` recomputes all.
    """
    fund_sql, fund_params = _fund_filter(fund_names, "f.fund_name")
    inner_sql, inner_params = _fund_filter(fund_names, "fund_name")
    inputs = conn.execute(
        f"""
        SELECT
            f.accession_number,
            f.fund_name,
            f.filing_date,
            f.acceptance_datetime,
            f.form_type,
            f.period_of_report,
            f.amendment_type,
            COALESCE(s.row_count, 0) AS row_count,
            s.median_price
        FROM filings f
        LEFT JOIN (
            SELECT
                accession_number,
                COUNT(*) AS row_count,
                MEDIAN(value_usd::DOUBLE / shares) FILTER (
                    WHERE UPPER(TRIM(COALESCE(sh_prn, ''))) = 'SH'
                      AND TRIM(COALESCE(put_call, '')) = ''
                      AND value_usd > 0
                      AND shares > 0
                ) AS median_price
            FROM holdings
            WHERE accession_number IN (
                SELECT accession_number FROM filings WHERE TRUE{inner_sql}
            )
            GROUP BY accession_number
        ) s ON s.accession_number = f.accession_number
        WHERE TRUE{fund_sql}
        """,
        [*inner_params, *fund_params],
    ).df()
    if inputs.empty:
        return

    records = inputs.to_dict("records")
    by_fund: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        by_fund.setdefault(record.get("fund_name") or "", []).append(record)

    rollups: dict[str, FilingRollup] = {}
    for fund_records in by_fund.values():
        rollups.update(compute_effective_filings(fund_records))

    output_rows = []
    for record in records:
        accession = _clean_text(record.get("accession_number"))
        rollup = rollups.get(accession)
        if rollup is None:
            continue
        output_rows.append(
            {
                "accession_number": record["accession_number"],
                "row_count": _row_count(record),
                "value_multiplier": choose_value_multiplier(record.get("median_price"), record.get("filing_date")),
                "anchor_accession": rollup.anchor_accession,
                "anchor_filing_date": rollup.anchor_filing_date,
                "is_effective": rollup.is_effective,
            }
        )
    if not output_rows:
        return

    output = pd.DataFrame(
        output_rows,
        columns=[
            "accession_number",
            "row_count",
            "value_multiplier",
            "anchor_accession",
            "anchor_filing_date",
            "is_effective",
        ],
    )
    view_name = "filing_rollup_output_df"
    conn.register(view_name, output)
    try:
        conn.execute(
            f"""
            UPDATE filings
            SET row_count = r.row_count,
                value_multiplier = r.value_multiplier,
                anchor_accession = r.anchor_accession,
                anchor_filing_date = r.anchor_filing_date,
                is_effective = r.is_effective,
                updated_at = now()
            FROM {view_name} r
            WHERE filings.accession_number = r.accession_number
            """
        )
    finally:
        conn.unregister(view_name)


def prune_orphan_filings(conn) -> None:
    """Drop ``filings`` rows that have neither holdings nor persisted metadata.

    A row with metadata is kept even when its holdings are gone: that metadata
    came from SEC documents and a re-ingest will need it again. Its row_count
    becomes 0 at the next rollup, which keeps it out of the view.
    """
    conn.execute(
        f"""
        DELETE FROM filings
        WHERE {" AND ".join(f"{field} IS NULL" for field in METADATA_FIELDS)}
          AND NOT EXISTS (
              SELECT 1 FROM holdings h WHERE h.accession_number = filings.accession_number
          )
        """
    )


def rebuild_filings_from_holdings(conn) -> None:
    """Make ``filings`` match ``holdings`` after a wholesale replacement.

    Accessions still present keep their persisted metadata and take the
    identity columns from the new rows; orphans are pruned (see
    :func:`prune_orphan_filings`); new accessions are registered. Everything is
    then recomputed.
    """
    prune_orphan_filings(conn)
    conn.execute(
        """
        UPDATE filings
        SET fund_name = src.fund_name,
            fund_cik = src.fund_cik,
            filing_date = src.filing_date,
            acceptance_datetime = COALESCE(src.acceptance_datetime, filings.acceptance_datetime)
        FROM (
            SELECT
                accession_number,
                MAX(fund_name) AS fund_name,
                MAX(fund_cik) AS fund_cik,
                MAX(filing_date) AS filing_date,
                MAX(acceptance_datetime) AS acceptance_datetime
            FROM holdings
            GROUP BY accession_number
        ) src
        WHERE filings.accession_number = src.accession_number
        """
    )
    sync_filings_from_holdings(conn)
    refresh_filing_rollup(conn, None)


def query_filings_missing_metadata(conn, limit: int | None = None) -> list[dict[str, Any]]:
    sql = """
        SELECT
            f.accession_number,
            f.fund_name,
            f.fund_cik,
            f.filing_date,
            (
                SELECT MAX(h.filing_url)
                FROM holdings h
                WHERE h.accession_number = f.accession_number
            ) AS filing_url,
            f.form_type,
            f.period_of_report,
            f.amendment_type
        FROM filings f
        WHERE f.period_of_report IS NULL
           OR (UPPER(TRIM(COALESCE(f.form_type, ''))) LIKE '%/A' AND f.amendment_type IS NULL)
        ORDER BY f.filing_date DESC, f.accession_number DESC
    """
    params: list[Any] = []
    if limit is not None:
        sql += " LIMIT ?"
        params.append(int(limit))
    return _records(conn.execute(sql, params).df())


def query_entry_count_mismatches(conn) -> list[dict[str, Any]]:
    return _records(
        conn.execute(
            """
            SELECT
                accession_number,
                fund_name,
                fund_cik,
                filing_date,
                form_type,
                period_of_report,
                table_entry_total,
                row_count,
                row_count - table_entry_total AS row_count_difference
            FROM filings
            WHERE table_entry_total IS NOT NULL
              AND COALESCE(row_count, 0) <> table_entry_total
            ORDER BY filing_date DESC, accession_number DESC
            """
        ).df()
    )


def _records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    if frame.empty:
        return []
    cleaned = frame.astype(object).where(frame.notna(), None)
    return cleaned.to_dict("records")
