"""Build the frozen DuckDB snapshot the public demo reads from.

The live dashboard DuckDB is ~224 MB across 1.15M holding rows and every
quarter since 2013. The demo does not need all of it: it needs enough filing
quarters for the consensus view's four-quarter window to mean something, and
it needs to be small enough to live in git so a clone alone can reproduce the
demo.

This keeps every row of the N most recent *filing* quarters -- calendar
quarters of ``filing_date``, which is how ``_consensus_analytics`` groups them
-- for every tracked fund. No column is dropped and no row is sampled, so the
demo exercises the same SQL the live app does and the numbers on screen are
real. One exception: ``all_columns_raw`` is nulled. That column holds the raw
XML row each holding was parsed from -- 23 MB of the 33 MB the four quarters
weigh, read by nothing but the full CSV export, which the demo disables anyway.
The column stays in the schema so every query still runs; only its contents go.

Run it from the repo root::

    python -m demo.freeze_demo_data                 # 4 quarters, default paths
    python -m demo.freeze_demo_data --quarters 5
"""

from __future__ import annotations

import argparse
import json
import shutil
from datetime import date, datetime, timezone
from pathlib import Path

import duckdb

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = REPO_ROOT / "src" / "core" / "data" / "13f_dashboard.duckdb"
DEFAULT_OUT = REPO_ROOT / "demo" / "fixtures" / "13f_demo.duckdb"
DEFAULT_QUARTERS = 4

# Written beside the snapshot; the API reads it for the "data as of" badge so
# the demo never has to guess how old it is.
META_NAME = "13f_demo.meta.json"


def _recent_quarter_start(con: duckdb.DuckDBPyConnection, quarters: int) -> date:
    """Return the first day of the oldest filing quarter we are keeping."""
    rows = con.execute(
        """
        SELECT DISTINCT date_trunc('quarter', TRY_CAST(filing_date AS DATE)) AS quarter_start
        FROM live.holdings
        WHERE TRY_CAST(filing_date AS DATE) IS NOT NULL
        ORDER BY quarter_start DESC
        LIMIT ?
        """,
        [quarters],
    ).fetchall()
    if not rows:
        raise SystemExit("Source database has no usable filing_date values.")
    return min(row[0] for row in rows)


def freeze(source: Path, out: Path, quarters: int) -> dict:
    if not source.exists():
        raise SystemExit(
            f"Source DuckDB not found: {source}\n"
            "Rebuild it first with: python -m src.cli.process_historical_13f full --yes"
        )

    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists():
        out.unlink()

    con = duckdb.connect(str(out))
    try:
        con.execute(f"ATTACH '{source.as_posix()}' AS live (READ_ONLY)")
        cutoff = _recent_quarter_start(con, quarters)
        con.execute(
            """
            CREATE TABLE holdings AS
            SELECT * REPLACE (CAST(NULL AS VARCHAR) AS all_columns_raw)
            FROM live.holdings
            WHERE TRY_CAST(filing_date AS DATE) >= ?
            """,
            [cutoff],
        )
        con.execute("DETACH live")

        stats = con.execute(
            """
            SELECT COUNT(*),
                   COUNT(DISTINCT fund_cik),
                   COUNT(DISTINCT accession_number),
                   MIN(filing_date),
                   MAX(filing_date)
            FROM holdings
            """
        ).fetchone()
        quarter_labels = [
            str(row[0])
            for row in con.execute(
                """
                SELECT DISTINCT strftime(date_trunc('quarter', TRY_CAST(filing_date AS DATE)), '%Y-Q')
                       || CAST(quarter(TRY_CAST(filing_date AS DATE)) AS VARCHAR) AS label
                FROM holdings
                ORDER BY label
                """
            ).fetchall()
        ]
    finally:
        con.close()

    # DuckDB leaves the file at its high-water mark; a rewrite compacts it.
    _compact(out)

    meta = {
        "snapshotDate": stats[4],
        "capturedAt": datetime.now(timezone.utc).date().isoformat(),
        "quartersKept": quarters,
        "quarters": quarter_labels,
        "rows": stats[0],
        "funds": stats[1],
        "filings": stats[2],
        "earliestFilingDate": stats[3],
        "latestFilingDate": stats[4],
        "sizeBytes": out.stat().st_size,
        "source": str(source.relative_to(REPO_ROOT)).replace("\\", "/"),
    }
    (out.parent / META_NAME).write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    _copy_ticker_index(source, out)
    return meta



def _copy_ticker_index(source: Path, out: Path) -> None:
    """Ship the ticker -> CUSIP index beside the snapshot.

    Search accepts tickers ("NVDA") only because of this index, and building one
    means asking SEC for its ticker reference. The demo must not make that call,
    so the index travels with the snapshot. The API restamps its recorded mtime
    at startup -- see ``src.api.demo.stamp_ticker_index``.
    """
    live_index = source.parent / "holdings_ticker_index.json"
    if not live_index.exists():
        print(f"  note: no ticker index at {live_index}; demo search matches names only")
        return
    shutil.copyfile(live_index, out.parent / "holdings_ticker_index.json")


def _compact(path: Path) -> None:
    """Copy the database through a fresh file so deleted pages are not carried."""
    tmp = path.with_suffix(".compact.duckdb")
    if tmp.exists():
        tmp.unlink()
    con = duckdb.connect(str(tmp))
    try:
        con.execute(f"ATTACH '{path.as_posix()}' AS big (READ_ONLY)")
        con.execute("CREATE TABLE holdings AS SELECT * FROM big.holdings")
        con.execute("DETACH big")
    finally:
        con.close()
    path.unlink()
    shutil.move(str(tmp), str(path))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--quarters", type=int, default=DEFAULT_QUARTERS)
    args = parser.parse_args()

    meta = freeze(args.source, args.out, args.quarters)
    size_mb = meta["sizeBytes"] / (1024 * 1024)
    print(f"Wrote {args.out}")
    print(f"  {meta['rows']:,} rows, {meta['filings']} filings, {meta['funds']} funds")
    print(f"  filing dates {meta['earliestFilingDate']} -> {meta['latestFilingDate']}")
    print(f"  quarters kept: {', '.join(meta['quarters'])}")
    print(f"  size: {size_mb:.1f} MB")


if __name__ == "__main__":
    main()
