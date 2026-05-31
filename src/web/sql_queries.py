"""SQL query constants for the Streamlit dashboard."""


FULL_HOLDINGS_EXPORT_SQL = """
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


LATEST_SNAPSHOT_EXPORT_SQL = """
    WITH latest_filing AS (
        SELECT fund_name, MAX(filing_date) AS filing_date
        FROM holdings
        GROUP BY fund_name
    )
    SELECT
        h.fund_name AS "Fund Name",
        h.filing_date AS "Filing Date",
        h.accession_number AS "Accession Number",
        h.issuer_name AS "Name of Issuer",
        h.share_class AS "Title of Class",
        h.cusip AS "CUSIP",
        h.value_usd AS "Value ($000s)",
        h.shares AS "Shares/Principal Amount",
        h.put_call AS "Put/Call"
    FROM holdings h
    INNER JOIN latest_filing lf
        ON h.fund_name = lf.fund_name
       AND h.filing_date = lf.filing_date
    ORDER BY h.fund_name, h.value_usd DESC NULLS LAST, h.issuer_name
"""


POSITION_KEY_SQL = """
    CASE
        WHEN TRIM(COALESCE(cusip, '')) <> '' THEN
             TRIM(COALESCE(cusip, '')) || '|' ||
             TRIM(COALESCE(share_class, '')) || '|' ||
             TRIM(COALESCE(put_call, ''))
        ELSE COALESCE(
             NULLIF(
                 TRIM(
                     BOTH '|'
                     FROM TRIM(COALESCE(issuer_name, '')) || '|' ||
                          TRIM(COALESCE(share_class, '')) || '|' ||
                          TRIM(COALESCE(put_call, ''))
                 ),
                 ''
             ),
             'UNKNOWN_POSITION'
        )
    END
"""


RAW_ACCESSION_HOLDINGS_SQL = """
    SELECT
        issuer_name AS "Issuer",
        TRIM(COALESCE(cusip, '')) AS "CUSIP",
        share_class AS "Class",
        shares AS "Shares",
        value_usd AS "Value ($000s)",
        put_call AS "Put/Call",
        investment_discretion AS "Investment Discretion",
        other_manager AS "Other Manager"
    FROM holdings
    WHERE fund_name = ? AND accession_number = ?
    ORDER BY value_usd DESC NULLS LAST, issuer_name
"""


NORMALIZED_ACCESSION_HOLDINGS_SQL = f"""
    SELECT
        MIN(issuer_name) AS "Issuer",
        MAX(TRIM(COALESCE(cusip, ''))) AS "CUSIP",
        GROUP_CONCAT(DISTINCT NULLIF(TRIM(share_class), '')) AS "Class",
        SUM(shares) AS "Shares",
        SUM(value_usd) AS "Value ($000s)",
        GROUP_CONCAT(DISTINCT NULLIF(TRIM(put_call), '')) AS "Put/Call",
        GROUP_CONCAT(DISTINCT NULLIF(TRIM(investment_discretion), '')) AS "Investment Discretion",
        GROUP_CONCAT(DISTINCT NULLIF(TRIM(other_manager), '')) AS "Other Manager",
        COUNT(*) AS "Raw 13F Lines"
    FROM holdings
    WHERE fund_name = ? AND accession_number = ?
    GROUP BY {POSITION_KEY_SQL}
    ORDER BY SUM(value_usd) DESC NULLS LAST, MIN(issuer_name)
"""


NORMALIZED_DIFF_SQL = f"""
    SELECT
        MAX(TRIM(COALESCE(cusip, ''))) AS cusip,
        MIN(issuer_name) AS issuer_name,
        GROUP_CONCAT(DISTINCT NULLIF(TRIM(share_class), '')) AS share_class,
        GROUP_CONCAT(DISTINCT NULLIF(TRIM(put_call), '')) AS put_call,
        SUM(shares) AS shares,
        SUM(value_usd) AS value_usd
    FROM holdings
    WHERE fund_name = ? AND accession_number = ?
    GROUP BY {POSITION_KEY_SQL}
    ORDER BY SUM(value_usd) DESC NULLS LAST, MIN(issuer_name)
"""


FUND_HISTORY_POSITIONS_SQL = f"""
    SELECT
        accession_number AS accession_number,
        filing_date AS filing_date,
        MAX(TRIM(COALESCE(cusip, ''))) AS cusip,
        MIN(issuer_name) AS issuer_name,
        GROUP_CONCAT(DISTINCT NULLIF(TRIM(share_class), '')) AS share_class,
        GROUP_CONCAT(DISTINCT NULLIF(TRIM(put_call), '')) AS put_call,
        SUM(shares) AS shares,
        SUM(value_usd) AS value_usd,
        COUNT(*) AS raw_lines
    FROM holdings
    WHERE fund_name = ?
      AND TRIM(COALESCE(accession_number, '')) <> ''
    GROUP BY accession_number, filing_date, {POSITION_KEY_SQL}
    ORDER BY filing_date DESC, SUM(value_usd) DESC NULLS LAST, MIN(issuer_name)
"""


OVERVIEW_SUMMARY_SQL = """
    SELECT
        COUNT(*) AS positions,
        COUNT(DISTINCT accession_number) AS filings,
        COUNT(DISTINCT fund_name) AS funds,
        MAX(filing_date) AS latest_filing_date,
        SUM(CASE WHEN value_usd IS NOT NULL THEN 1 ELSE 0 END) AS value_rows
    FROM holdings
"""


OVERVIEW_RECENT_ACTIVITY_SQL = """
    WITH anchor AS (
        SELECT MAX(filing_date) AS latest_filing_date
        FROM holdings
    )
    SELECT
        COUNT(DISTINCT accession_number) AS recent_filings,
        COUNT(DISTINCT fund_name) AS recent_funds
    FROM holdings, anchor
    WHERE CAST(filing_date AS DATE) >= CAST(anchor.latest_filing_date AS DATE) - INTERVAL 120 DAY
"""


LATEST_FUND_OVERVIEW_SQL = f"""
    WITH latest_filing AS (
        SELECT fund_name, MAX(filing_date) AS filing_date
        FROM holdings
        GROUP BY fund_name
    ),
    latest_accession AS (
        SELECT
            h.fund_name,
            lf.filing_date,
            MAX(h.accession_number) AS accession_number
        FROM holdings h
        INNER JOIN latest_filing lf
            ON h.fund_name = lf.fund_name
           AND h.filing_date = lf.filing_date
        GROUP BY h.fund_name, lf.filing_date
    ),
    quarters_tracked AS (
        SELECT
            fund_name,
            COUNT(DISTINCT accession_number) AS quarters_tracked
        FROM holdings
        GROUP BY fund_name
    ),
    latest_stats AS (
        SELECT
            h.fund_name,
            la.filing_date,
            la.accession_number,
            COUNT(*) AS raw_lines,
            COUNT(DISTINCT NULLIF(TRIM(cusip), '')) AS cusips,
            COUNT(DISTINCT {POSITION_KEY_SQL}) AS normalized_positions,
            SUM(value_usd) AS value_sum
        FROM holdings h
        INNER JOIN latest_accession la
            ON h.fund_name = la.fund_name
           AND h.accession_number = la.accession_number
        GROUP BY h.fund_name, la.filing_date, la.accession_number
    )
    SELECT
        ls.fund_name AS "Fund",
        qt.quarters_tracked AS "Quarters",
        ls.filing_date AS "Latest Filing",
        ls.raw_lines AS "Raw 13F Lines",
        ls.normalized_positions AS "Normalized Positions",
        ls.cusips AS "Distinct CUSIPs",
        ls.value_sum AS value_sum,
        ls.accession_number AS accession_number
    FROM latest_stats ls
    INNER JOIN quarters_tracked qt
        ON qt.fund_name = ls.fund_name
    ORDER BY ls.filing_date DESC, ls.raw_lines DESC, ls.fund_name
"""


RECENT_FILINGS_OVERVIEW_SQL = f"""
    WITH filing_stats AS (
        SELECT
            accession_number,
            fund_name,
            filing_date,
            COUNT(*) AS raw_lines,
            COUNT(DISTINCT NULLIF(TRIM(cusip), '')) AS cusips,
            COUNT(DISTINCT {POSITION_KEY_SQL}) AS normalized_positions
        FROM holdings
        WHERE TRIM(COALESCE(accession_number, '')) <> ''
        GROUP BY accession_number, fund_name, filing_date
    )
    SELECT
        fund_name AS "Fund",
        filing_date AS "Filing Date",
        accession_number AS "Accession",
        raw_lines AS "Raw 13F Lines",
        normalized_positions AS "Normalized Positions",
        cusips AS "Distinct CUSIPs"
    FROM filing_stats
    ORDER BY filing_date DESC, raw_lines DESC, fund_name
    LIMIT 20
"""


FILINGS_TIMELINE_SQL = """
    SELECT
        substr(filing_date, 1, 7) AS "Month",
        COUNT(DISTINCT accession_number) AS "Filings",
        COUNT(DISTINCT fund_name) AS "Funds"
    FROM holdings
    GROUP BY substr(filing_date, 1, 7)
    ORDER BY substr(filing_date, 1, 7)
"""


TOP_HELD_SECURITIES_SQL = f"""
    WITH latest_filing AS (
        SELECT fund_name, MAX(filing_date) AS filing_date
        FROM holdings
        GROUP BY fund_name
    ),
    latest_accession AS (
        SELECT
            h.fund_name,
            lf.filing_date,
            MAX(h.accession_number) AS accession_number
        FROM holdings h
        INNER JOIN latest_filing lf
            ON h.fund_name = lf.fund_name
           AND h.filing_date = lf.filing_date
        GROUP BY h.fund_name, lf.filing_date
    ),
    latest_positions AS (
        SELECT
            h.fund_name,
            {POSITION_KEY_SQL} AS position_key,
            MAX(TRIM(COALESCE(h.cusip, ''))) AS cusip,
            MIN(h.issuer_name) AS issuer_name
        FROM holdings h
        INNER JOIN latest_accession la
            ON h.fund_name = la.fund_name
           AND h.accession_number = la.accession_number
        GROUP BY h.fund_name, {POSITION_KEY_SQL}
    )
    SELECT
        MIN(issuer_name) AS "Issuer",
        NULLIF(MAX(cusip), '') AS "CUSIP",
        COUNT(*) AS "Funds Holding It"
    FROM latest_positions
    GROUP BY position_key
    ORDER BY COUNT(*) DESC, MIN(issuer_name)
    LIMIT 15
"""