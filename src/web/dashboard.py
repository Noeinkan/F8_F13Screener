"""
F8 F13 Screener — Streamlit Dashboard
Run locally:  streamlit run src/web/dashboard.py
"""
import sqlite3
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
DB_PATH = Path(__file__).parent.parent / "core" / "data" / "13f_holdings.db"

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
    st.title("Overview — Fondi monitorati")

    stats = query("SELECT * FROM statistics WHERE id = 1")
    if not stats.empty:
        s = stats.iloc[0]
        c1, c2, c3 = st.columns(3)
        c1.metric("Filing totali controllati", f"{int(s['total_checked']):,}")
        c2.metric("Filing matched", f"{int(s['matched']):,}")
        c3.metric("Filing filtrati", f"{int(s['filtered']):,}")

    st.subheader("Fondi nel database")
    df = query("""
        SELECT
            fund_name                                   AS "Fund",
            COUNT(*)                                    AS "Holdings",
            MAX(filing_date)                            AS "Ultimo Filing",
            COUNT(DISTINCT accession_number)            AS "Trimestri",
            SUM(value_usd)                              AS value_sum
        FROM holdings
        GROUP BY fund_name
        ORDER BY value_sum DESC
    """)

    if df.empty:
        st.info("Nessun dato nel database ancora.")
    else:
        df["Valore Totale"] = df["value_sum"].apply(fmt_value)
        st.dataframe(
            df[["Fund", "Trimestri", "Ultimo Filing", "Holdings", "Valore Totale"]],
            use_container_width=True,
            hide_index=True,
        )

        fig = px.bar(
            df.head(20),
            x="Fund",
            y="value_sum",
            labels={"value_sum": "Valore ($000s)", "Fund": ""},
            title="Top 20 fondi per valore portfolio",
        )
        fig.update_layout(xaxis_tickangle=-40)
        st.plotly_chart(fig, use_container_width=True)


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

    df = query("""
        SELECT issuer_name AS "Issuer", cusip AS "CUSIP",
               share_class AS "Classe", shares AS "Azioni",
               value_usd AS "Valore ($000s)", put_call AS "Put/Call"
        FROM holdings
        WHERE fund_name = ? AND accession_number = ?
        ORDER BY value_usd DESC NULLS LAST
    """, (fund, selected_acc))

    if df.empty:
        st.info("Nessuna holding trovata per questo trimestre.")
        st.stop()

    st.subheader(f"Top 10 holdings — {fund}")
    top10 = df.head(10)
    fig = px.bar(
        top10,
        x="Issuer",
        y="Valore ($000s)",
        title=f"Top 10 per valore — {fund}",
    )
    fig.update_layout(xaxis_tickangle=-30)
    st.plotly_chart(fig, use_container_width=True)

    st.subheader(f"Tutte le holdings ({len(df)})")
    search = st.text_input("Filtra per nome o CUSIP")
    if search:
        mask = (
            df["Issuer"].str.contains(search, case=False, na=False)
            | df["CUSIP"].str.contains(search, case=False, na=False)
        )
        df = df[mask]

    st.dataframe(df, use_container_width=True, hide_index=True)


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
        rows = query("""
            SELECT cusip, issuer_name, shares, value_usd
            FROM holdings WHERE fund_name = ? AND accession_number = ?
        """, (fund, acc))
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

    import sys
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
        st.dataframe(ndf[["issuer_name", "cusip", "Azioni", "Valore"]]
                     .rename(columns={"issuer_name": "Issuer", "cusip": "CUSIP"}),
                     use_container_width=True, hide_index=True)

    if diff["closed_positions"]:
        st.subheader("📉 Posizioni chiuse")
        cdf = pd.DataFrame(diff["closed_positions"])
        cdf["Valore precedente"] = cdf["value_usd"].apply(fmt_value)
        cdf["Azioni precedenti"] = cdf["shares"].apply(lambda x: f"{x:,}" if pd.notna(x) and x else "-")
        st.dataframe(cdf[["issuer_name", "cusip", "Azioni precedenti", "Valore precedente"]]
                     .rename(columns={"issuer_name": "Issuer", "cusip": "CUSIP"}),
                     use_container_width=True, hide_index=True)

    changes = diff["increased"] + diff["decreased"]
    if changes:
        st.subheader("🔄 Variazioni significative (≥10%)")
        chdf = pd.DataFrame(changes)
        chdf["Δ%"] = chdf["pct_change"].apply(lambda x: f"+{x:.1f}%" if x > 0 else f"{x:.1f}%")
        chdf["Azioni prima"] = chdf["old_shares"].apply(lambda x: f"{x:,}" if pd.notna(x) else "-")
        chdf["Azioni dopo"] = chdf["new_shares"].apply(lambda x: f"{x:,}" if pd.notna(x) else "-")
        chdf = chdf.sort_values("pct_change", ascending=False)
        st.dataframe(chdf[["issuer_name", "cusip", "Azioni prima", "Azioni dopo", "Δ%"]]
                     .rename(columns={"issuer_name": "Issuer", "cusip": "CUSIP"}),
                     use_container_width=True, hide_index=True)

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
