"""
Analyse: overzicht van gedetecteerde SOFAR-commandowisselingen.
"""

import pandas as pd
import streamlit as st

from scripts import analyse_response

st.set_page_config(page_title="Analyse", page_icon="📈", layout="wide")
st.title("📈 Commandowisselingen")

st.caption(
    "Elke rij is een moment waarop het SOFAR-systeem een nieuwe opdracht kreeg "
    "(andere actie of ander vermogen dan het vorige commando)."
)

if not analyse_response.OUTPUT_FILE.exists():
    st.warning(
        "Nog geen analysedata. Ga naar **Data Ophalen** en klik op "
        "**🔬 Analyseer batterij-respons**."
    )
    st.stop()

df = pd.read_csv(analyse_response.OUTPUT_FILE, parse_dates=["command_timestamp"])

# ── Samenvatting ──────────────────────────────────────────────────────────
k1, k2, k3 = st.columns(3)
k1.metric("Commandowisselingen", f"{len(df):,}")
k2.metric("Dagen", df["datum"].nunique())
k3.metric("Unieke transitietypes", df[["prev_action", "new_action"]].drop_duplicates().shape[0])

st.divider()

# ── Filters ───────────────────────────────────────────────────────────────
col1, col2, col3 = st.columns(3)

gekozen_prev = col1.multiselect(
    "Van actie",
    options=sorted(df["prev_action"].dropna().unique()),
    placeholder="Alle",
)
gekozen_new = col2.multiselect(
    "Naar actie",
    options=sorted(df["new_action"].dropna().unique()),
    placeholder="Alle",
)
periode = col3.date_input(
    "Periode",
    value=(df["command_timestamp"].dt.date.min(), df["command_timestamp"].dt.date.max()),
    min_value=df["command_timestamp"].dt.date.min(),
    max_value=df["command_timestamp"].dt.date.max(),
)

sel = df.copy()
if gekozen_prev:
    sel = sel[sel["prev_action"].isin(gekozen_prev)]
if gekozen_new:
    sel = sel[sel["new_action"].isin(gekozen_new)]
if isinstance(periode, tuple) and len(periode) == 2:
    sel = sel[
        (sel["command_timestamp"].dt.date >= periode[0])
        & (sel["command_timestamp"].dt.date <= periode[1])
    ]

st.caption(f"{len(sel):,} wisselingen geselecteerd")

# ── Transitiefrequentie per type ──────────────────────────────────────────
st.subheader("Frequentie per transitietype")
freq = (
    sel.groupby(["prev_action", "new_action"])
    .size()
    .reset_index(name="aantal")
    .sort_values("aantal", ascending=False)
)
freq.columns = ["Van", "Naar", "Aantal"]
st.dataframe(freq, hide_index=True, use_container_width=True)

# ── Gedetailleerde tabel ──────────────────────────────────────────────────
st.subheader("Alle wisselingen")
weergave = sel.copy()
weergave["command_timestamp"] = weergave["command_timestamp"].dt.strftime("%d/%m/%Y %H:%M:%S")
weergave.columns = ["Datum", "Tijdstip", "Van actie", "Naar actie", "Vermogen (W)"]
st.dataframe(weergave.head(500), hide_index=True, use_container_width=True)
if len(sel) > 500:
    st.caption(f"Eerste 500 van {len(sel):,} rijen getoond.")
