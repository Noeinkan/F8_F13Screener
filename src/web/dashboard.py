"""
F8 F13 Screener — Streamlit Dashboard
Run locally:  streamlit run src/web/dashboard.py
"""
import sqlite3
import sys
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

from src.core.paths import HOLDINGS_DB_FILE

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
DB_PATH = HOLDINGS_DB_FILE

st.set_page_config(
    page_title="F8 13F Screener",
    page_icon="📊",
    layout="wide",
)


# ---------------------------------------------------------------------------
# Data helpers
# ---------------------------------------------------------------------------
@st.cache_resource
def get_connection():
    if not DB_PATH.exists():
        st.error(f"Database non trovato: {DB_PATH}")
        st.stop()
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def query(sql: str, params: tuple = ()) -> pd.DataFrame:
    conn = get_connection()
    return pd.read_sql_query(sql, conn, params=params)


def dataframe_to_csv_bytes(df: pd.DataFrame | pd.Series) -> bytes:
    frame = df.to_frame() if isinstance(df, pd.Series) else df
    return frame.to_csv(index=False).encode("utf-8")


def fmt_value(val_thousands):
    """Format thousands-of-USD into readable string."""
    if pd.isna(val_thousands) or val_thousands == 0:
        return "-"
    v = float(val_thousands) * 1000
    if v >= 1e9:
        return f"${v/1e9:.2f}B"
    if v >= 1e6:
        return f"${v/1e6:.1f}M"
    if v >= 1e3:
        return f"${v/1e3:.0f}k"
    return f"${v:,.0f}"


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
        WHEN TRIM(COALESCE(cusip, '')) <> '' THEN TRIM(cusip)
        ELSE TRIM(COALESCE(issuer_name, '')) || '|' ||
             TRIM(COALESCE(share_class, '')) || '|' ||
             TRIM(COALESCE(put_call, ''))
    END
"""


RAW_ACCESSION_HOLDINGS_SQL = """
    SELECT
        issuer_name AS "Issuer",
        TRIM(COALESCE(cusip, '')) AS "CUSIP",
        share_class AS "Classe",
        shares AS "Azioni",
        value_usd AS "Valore ($000s)",
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
        GROUP_CONCAT(DISTINCT NULLIF(TRIM(share_class), '')) AS "Classe",
        SUM(shares) AS "Azioni",
        SUM(value_usd) AS "Valore ($000s)",
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
        SUM(shares) AS shares,
        SUM(value_usd) AS value_usd
    FROM holdings
    WHERE fund_name = ? AND accession_number = ?
    GROUP BY {POSITION_KEY_SQL}
    ORDER BY SUM(value_usd) DESC NULLS LAST, MIN(issuer_name)
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
    WHERE filing_date >= date(anchor.latest_filing_date, '-120 day')
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
        qt.quarters_tracked AS "Trimestri",
        ls.filing_date AS "Ultimo Filing",
        ls.raw_lines AS "Raw 13F Lines",
        ls.normalized_positions AS "Posizioni normalizzate",
        ls.cusips AS "CUSIP distinti",
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
        normalized_positions AS "Posizioni normalizzate",
        cusips AS "CUSIP distinti"
    FROM filing_stats
    ORDER BY filing_date DESC, raw_lines DESC, fund_name
    LIMIT 20
"""


FILINGS_TIMELINE_SQL = """
    SELECT
        substr(filing_date, 1, 7) AS "Mese",
        COUNT(DISTINCT accession_number) AS "Filing",
        COUNT(DISTINCT fund_name) AS "Fondi"
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
        COUNT(*) AS "Fondi che la detengono"
    FROM latest_positions
    GROUP BY position_key
    ORDER BY COUNT(*) DESC, MIN(issuer_name)
    LIMIT 15
"""


# ---------------------------------------------------------------------------
# Sidebar navigation
# ---------------------------------------------------------------------------
st.sidebar.title("📊 F8 13F Screener")
page = st.sidebar.radio(
    "Sezione",
    ["Overview", "Fund Detail", "Portfolio Diff", "Holdings Search"],
)
st.sidebar.markdown("---")
st.sidebar.caption(f"DB: `{DB_PATH}`")
if st.sidebar.button("🔄 Aggiorna dati"):
    st.cache_data.clear()
    st.rerun()


# ---------------------------------------------------------------------------
# Page 1 — Overview
# ---------------------------------------------------------------------------
if page == "Overview":
    st.title("Overview — Stato del database 13F")

    dataset = query(OVERVIEW_SUMMARY_SQL)
    recent_activity = query(OVERVIEW_RECENT_ACTIVITY_SQL)
    has_portfolio_values = False

    if not dataset.empty:
        d = dataset.iloc[0]
        recent = recent_activity.iloc[0] if not recent_activity.empty else None
        has_portfolio_values = int(d["value_rows"] or 0) > 0
        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("Righe holdings", f"{int(d['positions']):,}")
        c2.metric("Filing 13F", f"{int(d['filings']):,}")
        c3.metric("Fondi coperti", f"{int(d['funds']):,}")
        c4.metric("Ultimo filing", d["latest_filing_date"] or "-")
        c5.metric(
            "Filing ultimi ~120gg",
            f"{int(recent['recent_filings']):,}" if recent is not None else "-",
        )

        if recent is not None:
            st.caption(
                f"Fondi con almeno un filing negli ultimi ~120 giorni: "
                f"{int(recent['recent_funds']):,}"
            )

        if not has_portfolio_values:
            st.warning(
                "Nel database corrente i valori di portafoglio non sono presenti "
                "(`value_usd` / `value_x1000` sono vuoti). "
                "Questa overview mostra quindi segnali utili basati su filing, "
                "copertura e posizioni normalizzate, che sono i dati realmente disponibili."
            )
        else:
            st.success(
                "I valori di portafoglio sono disponibili: classifica fondi e grafici ora usano l'ultimo filing valorizzato."
            )

    stats = query("SELECT * FROM statistics WHERE id = 1")
    if not stats.empty:
        s = stats.iloc[0]
        if any(int(s[col]) for col in ("total_checked", "matched", "filtered")):
            st.caption(
                "Feed monitor stats: "
                f"checked {int(s['total_checked']):,} | "
                f"matched {int(s['matched']):,} | "
                f"filtered {int(s['filtered']):,}"
            )

    st.subheader("Ultimo filing per fondo")
    st.caption(
        "Per ogni fondo mostriamo solo l'ultimo filing disponibile, con conteggio raw e "
        "conteggio normalizzato per CUSIP."
    )
    df = query(LATEST_FUND_OVERVIEW_SQL)

    if df.empty:
        st.info("Nessun dato nel database ancora.")
    else:
        full_export = query(FULL_HOLDINGS_EXPORT_SQL)
        latest_snapshot = query(LATEST_SNAPSHOT_EXPORT_SQL)
        recent_filings = query(RECENT_FILINGS_OVERVIEW_SQL)
        timeline_df = query(FILINGS_TIMELINE_SQL)
        common_holdings = query(TOP_HELD_SECURITIES_SQL)

        d1, d2 = st.columns(2)
        d1.download_button(
            "Scarica CSV completo holdings",
            dataframe_to_csv_bytes(full_export),
            file_name="f8_13f_all_holdings.csv",
            mime="text/csv",
            use_container_width=True,
        )
        d2.download_button(
            "Scarica ultimo snapshot per fondo",
            dataframe_to_csv_bytes(latest_snapshot),
            file_name="f8_13f_latest_snapshot.csv",
            mime="text/csv",
            use_container_width=True,
        )

        filter_text = st.text_input(
            "Filtra fondo",
            placeholder="es. AQR, Berkshire, Appaloosa",
        )
        filtered_df = df.copy()
        if filter_text:
            filtered_df = filtered_df[
                filtered_df["Fund"].str.contains(filter_text, case=False, na=False)
            ].copy()

        if has_portfolio_values:
            filtered_df["Valore portfolio"] = filtered_df["value_sum"].apply(fmt_value)

        display_columns = [
            "Fund",
            "Trimestri",
            "Ultimo Filing",
            "Raw 13F Lines",
            "Posizioni normalizzate",
            "CUSIP distinti",
        ]
        if has_portfolio_values:
            display_columns.append("Valore portfolio")
        st.dataframe(
            filtered_df[display_columns],
            use_container_width=True,
            hide_index=True,
        )

        chart_col1, chart_col2 = st.columns(2)
        with chart_col1:
            if has_portfolio_values:
                fig = px.bar(
                    df.sort_values("value_sum", ascending=False).head(20),
                    x="Fund",
                    y="value_sum",
                    labels={"value_sum": "Valore ($000s)", "Fund": ""},
                    title="Top 20 fondi per valore ultimo filing",
                )
            else:
                fig = px.bar(
                    df.head(20),
                    x="Fund",
                    y="Posizioni normalizzate",
                    labels={"Posizioni normalizzate": "Posizioni", "Fund": ""},
                    title="Top 20 fondi per posizioni normalizzate",
                )
            fig.update_layout(xaxis_tickangle=-40)
            st.plotly_chart(fig, use_container_width=True)

        with chart_col2:
            if not timeline_df.empty:
                fig = px.line(
                    timeline_df.tail(24),
                    x="Mese",
                    y="Filing",
                    markers=True,
                    title="Filing archiviati per mese",
                )
                st.plotly_chart(fig, use_container_width=True)

        insights_col1, insights_col2 = st.columns(2)
        with insights_col1:
            st.subheader("Filing piu recenti")
            st.dataframe(recent_filings, use_container_width=True, hide_index=True)

        with insights_col2:
            st.subheader("Titoli piu diffusi oggi")
            st.dataframe(common_holdings, use_container_width=True, hide_index=True)


# ---------------------------------------------------------------------------
# Page 2 — Fund Detail
# ---------------------------------------------------------------------------
elif page == "Fund Detail":
    st.title("Fund Detail")

    funds = query("SELECT DISTINCT fund_name FROM holdings ORDER BY fund_name")
    if funds.empty:
        st.info("Nessun dato nel database ancora.")
        st.stop()

    fund = st.selectbox("Seleziona fondo", funds["fund_name"].tolist())

    accessions = query("""
        SELECT DISTINCT accession_number, filing_date
        FROM holdings WHERE fund_name = ?
        ORDER BY filing_date DESC
    """, (fund,))

    label_map = {
        row["accession_number"]: f"{row['filing_date']}  ({row['accession_number']})"
        for _, row in accessions.iterrows()
    }
    selected_acc = st.selectbox("Trimestre (accession)", list(label_map.keys()),
                                format_func=lambda k: label_map[k])

    raw_df = query(RAW_ACCESSION_HOLDINGS_SQL, (fund, selected_acc))
    normalized_df = query(NORMALIZED_ACCESSION_HOLDINGS_SQL, (fund, selected_acc))

    if raw_df.empty:
        st.info("Nessuna holding trovata per questo trimestre.")
        st.stop()

    c1, c2, c3 = st.columns(3)
    c1.metric("Raw 13F lines", f"{len(raw_df):,}")
    c2.metric("Posizioni normalizzate", f"{len(normalized_df):,}")
    compression_ratio = 1 - (len(normalized_df) / len(raw_df))
    c3.metric("Compressione", f"{compression_ratio:.1%}")

    view_mode = st.radio(
        "Vista holdings",
        ["Normalizzata per CUSIP", "Raw 13F lines"],
        horizontal=True,
    )
    st.caption(
        "La vista normalizzata aggrega le righe 13F con lo stesso CUSIP, "
        "sommando azioni e valore. E' la vista corretta per fondi come AQR."
    )

    display_df = normalized_df.copy() if view_mode == "Normalizzata per CUSIP" else raw_df.copy()

    st.subheader(f"Top 10 holdings — {fund}")
    top10 = display_df.head(10)
    fig = px.bar(
        top10,
        x="Issuer",
        y="Valore ($000s)",
        title=f"Top 10 per valore — {fund}",
    )
    fig.update_layout(xaxis_tickangle=-30)
    st.plotly_chart(fig, use_container_width=True)

    view_label = "posizioni normalizzate" if view_mode == "Normalizzata per CUSIP" else "righe raw 13F"
    st.subheader(f"Tutte le {view_label} ({len(display_df):,})")
    search = st.text_input("Filtra per nome o CUSIP")
    filtered_df = display_df.copy()
    if search:
        mask = (
            filtered_df["Issuer"].str.contains(search, case=False, na=False)
            | filtered_df["CUSIP"].str.contains(search, case=False, na=False)
        )
        filtered_df = filtered_df.loc[mask].copy()

    st.download_button(
        "Scarica CSV del trimestre selezionato",
        dataframe_to_csv_bytes(filtered_df),
        file_name=(
            f"f8_13f_{selected_acc}_normalized.csv"
            if view_mode == "Normalizzata per CUSIP"
            else f"f8_13f_{selected_acc}_raw.csv"
        ),
        mime="text/csv",
    )
    st.dataframe(filtered_df, use_container_width=True, hide_index=True)


# ---------------------------------------------------------------------------
# Page 3 — Portfolio Diff
# ---------------------------------------------------------------------------
elif page == "Portfolio Diff":
    st.title("Portfolio Diff — Quarter over Quarter")

    funds = query("SELECT DISTINCT fund_name FROM holdings ORDER BY fund_name")
    if funds.empty:
        st.info("Nessun dato nel database ancora.")
        st.stop()

    fund = st.selectbox("Seleziona fondo", funds["fund_name"].tolist())

    accessions = query("""
        SELECT DISTINCT accession_number, filing_date
        FROM holdings WHERE fund_name = ?
        ORDER BY filing_date DESC
    """, (fund,))

    if len(accessions) < 2:
        st.warning("Servono almeno 2 trimestri per calcolare il diff.")
        st.stop()

    label_map = {
        row["accession_number"]: f"{row['filing_date']}  ({row['accession_number']})"
        for _, row in accessions.iterrows()
    }
    acc_list = list(label_map.keys())

    col1, col2 = st.columns(2)
    with col1:
        acc_new = st.selectbox("Trimestre NUOVO", acc_list,
                               format_func=lambda k: label_map[k], index=0)
    with col2:
        acc_old = st.selectbox("Trimestre PRECEDENTE", acc_list,
                               format_func=lambda k: label_map[k], index=1)

    if acc_new == acc_old:
        st.warning("Seleziona due trimestri diversi.")
        st.stop()

    def load_acc(acc):
        rows = query(NORMALIZED_DIFF_SQL, (fund, acc))
        return {
            row["cusip"]: {
                "issuer_name": row["issuer_name"],
                "shares": row["shares"],
                "value_usd": row["value_usd"],
            }
            for _, row in rows.iterrows() if row["cusip"]
        }

    old_map = load_acc(acc_old)
    new_map = load_acc(acc_new)

    sys.path.insert(0, str(Path(__file__).parent.parent.parent))
    from src.core.diff import compute_portfolio_diff

    diff = compute_portfolio_diff(old_map, new_map)

    # Summary metrics
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Nuove posizioni", len(diff["new_positions"]))
    c2.metric("Posizioni chiuse", len(diff["closed_positions"]))
    c3.metric("Aumentate", len(diff["increased"]))
    c4.metric("Diminuite", len(diff["decreased"]))

    if diff["new_positions"]:
        st.subheader("📈 Nuove posizioni")
        ndf = pd.DataFrame(diff["new_positions"])
        ndf["Valore"] = ndf["value_usd"].apply(fmt_value)
        ndf["Azioni"] = ndf["shares"].apply(lambda x: f"{x:,}" if pd.notna(x) and x else "-")
        new_positions_df = pd.DataFrame({
            "Issuer": ndf["issuer_name"],
            "CUSIP": ndf["cusip"],
            "Azioni": ndf["Azioni"],
            "Valore": ndf["Valore"],
        })
        st.dataframe(new_positions_df, use_container_width=True, hide_index=True)

    if diff["closed_positions"]:
        st.subheader("📉 Posizioni chiuse")
        cdf = pd.DataFrame(diff["closed_positions"])
        cdf["Valore precedente"] = cdf["value_usd"].apply(fmt_value)
        cdf["Azioni precedenti"] = cdf["shares"].apply(lambda x: f"{x:,}" if pd.notna(x) and x else "-")
        closed_positions_df = pd.DataFrame({
            "Issuer": cdf["issuer_name"],
            "CUSIP": cdf["cusip"],
            "Azioni precedenti": cdf["Azioni precedenti"],
            "Valore precedente": cdf["Valore precedente"],
        })
        st.dataframe(closed_positions_df, use_container_width=True, hide_index=True)

    changes = diff["increased"] + diff["decreased"]
    if changes:
        st.subheader("🔄 Variazioni significative (≥10%)")
        chdf = pd.DataFrame(changes)
        chdf["Δ%"] = chdf["pct_change"].apply(lambda x: f"+{x:.1f}%" if x > 0 else f"{x:.1f}%")
        chdf["Azioni prima"] = chdf["old_shares"].apply(lambda x: f"{x:,}" if pd.notna(x) else "-")
        chdf["Azioni dopo"] = chdf["new_shares"].apply(lambda x: f"{x:,}" if pd.notna(x) else "-")
        chdf = chdf.sort_values("pct_change", ascending=False)
        changes_df = pd.DataFrame({
            "Issuer": chdf["issuer_name"],
            "CUSIP": chdf["cusip"],
            "Azioni prima": chdf["Azioni prima"],
            "Azioni dopo": chdf["Azioni dopo"],
            "Δ%": chdf["Δ%"],
        })
        st.dataframe(changes_df, use_container_width=True, hide_index=True)

    if not any([diff["new_positions"], diff["closed_positions"], changes]):
        st.success("Nessuna variazione significativa tra i due trimestri.")


# ---------------------------------------------------------------------------
# Page 4 — Holdings Search
# ---------------------------------------------------------------------------
elif page == "Holdings Search":
    st.title("Holdings Search")

    query_text = st.text_input("Cerca per nome issuer o CUSIP", placeholder="es. Apple, 037833100")

    if not query_text:
        st.info("Inserisci un termine di ricerca per iniziare.")
        st.stop()

    df = query("""
        SELECT
            issuer_name AS "Issuer",
            cusip       AS "CUSIP",
            fund_name   AS "Fund",
            filing_date AS "Filing Date",
            shares      AS "Azioni",
            value_usd   AS "Valore ($000s)",
            accession_number AS "Accession"
        FROM holdings
        WHERE issuer_name LIKE ? OR cusip LIKE ?
        ORDER BY filing_date DESC, value_usd DESC NULLS LAST
    """, (f"%{query_text}%", f"%{query_text}%"))

    if df.empty:
        st.warning(f"Nessun risultato per '{query_text}'")
        st.stop()

    st.success(f"{len(df)} risultati trovati")
    df["Valore"] = df["Valore ($000s)"].apply(fmt_value)
    df["Azioni"] = df["Azioni"].apply(lambda x: f"{int(x):,}" if pd.notna(x) and x else "-")

    st.download_button(
        "Scarica risultati CSV",
        dataframe_to_csv_bytes(df),
        file_name="f8_13f_search_results.csv",
        mime="text/csv",
    )
    st.dataframe(
        df[["Issuer", "CUSIP", "Fund", "Filing Date", "Azioni", "Valore"]],
        use_container_width=True,
        hide_index=True,
    )

    # Show which funds currently hold this asset (latest filing per fund)
    st.subheader("Chi la detiene oggi (ultimo filing per fondo)")
    latest = query("""
        SELECT h.fund_name AS "Fund", h.filing_date AS "Filing Date",
               h.shares AS "Azioni", h.value_usd AS "Valore ($000s)"
        FROM holdings h
        INNER JOIN (
            SELECT fund_name, MAX(filing_date) AS max_date
            FROM holdings
            WHERE issuer_name LIKE ? OR cusip LIKE ?
            GROUP BY fund_name
        ) latest ON h.fund_name = latest.fund_name AND h.filing_date = latest.max_date
        WHERE h.issuer_name LIKE ? OR h.cusip LIKE ?
        ORDER BY h.value_usd DESC NULLS LAST
    """, (f"%{query_text}%", f"%{query_text}%", f"%{query_text}%", f"%{query_text}%"))

    if not latest.empty:
        latest["Valore"] = latest["Valore ($000s)"].apply(fmt_value)
        latest["Azioni"] = latest["Azioni"].apply(lambda x: f"{int(x):,}" if pd.notna(x) and x else "-")
        st.dataframe(latest[["Fund", "Filing Date", "Azioni", "Valore"]],
                     use_container_width=True, hide_index=True)
