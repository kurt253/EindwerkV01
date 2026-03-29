"""
Dagelijkse Totalen: overzicht van injectie, afname en batterij per dag.
"""

import pandas as pd
import streamlit as st

from scripts import battery, solar_logs

st.set_page_config(page_title="Dagelijkse Totalen", page_icon="📋", layout="wide")
st.title("📋 Dagelijkse Totalen")

# ── Data laden ────────────────────────────────────────────────────────────
solar_all   = solar_logs.load_all()
battery_all = battery.load_all()

if solar_all.empty:
    st.error("Geen lokale solar data gevonden.")
    st.stop()

# Dagelijkse totalen uit solar: som van alle uren per dag
uur_cols = [c for c in solar_all.columns if c != "Datum"]
solar_totals = solar_all[["Datum"]].copy()

# load_all() geeft alleen meterValue (netto teller) per uur; injectie en afname apart optellen
# uit de ruwe bestanden om te vermijden dat tekens worden weggemiddeld
from scripts.config import SOLAR_DIR, BATTERY_DIR
import json
from pathlib import Path

rows = []
for path in sorted(SOLAR_DIR.glob("*.json")):
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if raw.get("status") != "OK" or not raw.get("data"):
            continue
        # Bestandsnaam: eerste 8 tekens = YYYYMMDD
        datum = pd.to_datetime(path.name[:8], format="%Y%m%d")
        # Dagsom = optelling van uurwaarden; elke uurwaarde is al in kWh uitgedrukt door de API
        injectie = sum(float(r["meterValue_injectie"]) for r in raw["data"])
        afname   = sum(float(r["meterValue_afname"])   for r in raw["data"])
        rows.append({"Datum": datum, "Injectie (kWh)": injectie, "Afname (kWh)": afname})
    except Exception:
        continue

solar_totals = pd.DataFrame(rows).sort_values("Datum").reset_index(drop=True)

# ── Samenvoegen met batterij ──────────────────────────────────────────────
if not battery_all.empty:
    df = solar_totals.merge(battery_all, on="Datum", how="left")
else:
    df = solar_totals

df["Datum"] = df["Datum"].dt.strftime("%d/%m/%Y")

# ── Filters ───────────────────────────────────────────────────────────────
with st.expander("Filter op periode"):
    dates_raw = solar_logs.available_dates()
    col1, col2 = st.columns(2)
    filter_van = col1.date_input("Van", value=dates_raw[0],  min_value=dates_raw[0],  max_value=dates_raw[-1])
    filter_tot = col2.date_input("Tot", value=dates_raw[-1], min_value=dates_raw[0],  max_value=dates_raw[-1])

    filter_van_str = filter_van.strftime("%d/%m/%Y")
    filter_tot_str = filter_tot.strftime("%d/%m/%Y")

    # Datum is al geformatteerd als string "DD/MM/YYYY" voor weergave;
    # tijdelijk terugparseren voor de vergelijking met de datumkiezers
    mask = (
        pd.to_datetime(df["Datum"], format="%d/%m/%Y") >= pd.Timestamp(filter_van)
    ) & (
        pd.to_datetime(df["Datum"], format="%d/%m/%Y") <= pd.Timestamp(filter_tot)
    )
    df = df[mask]

# ── Totaalrij ─────────────────────────────────────────────────────────────
num_cols = [c for c in df.columns if c != "Datum"]
# Som alle numerieke kolommen op voor de totaalrij onderaan de tabel
totaal = {c: df[c].sum() for c in num_cols}
totaal["Datum"] = "Totaal"
df_display = pd.concat([df, pd.DataFrame([totaal])], ignore_index=True)

# ── Tabel tonen ───────────────────────────────────────────────────────────
def _highlight_totaal(row):
    return ["font-weight: bold; background-color: #f0f0f0"] * len(row) if row["Datum"] == "Totaal" else [""] * len(row)

styled = (
    df_display.style
    .format({c: "{:.2f}" for c in num_cols}, na_rep="—")
    .apply(_highlight_totaal, axis=1)
)

st.dataframe(styled, width="stretch", hide_index=True)

# ── Metrics ───────────────────────────────────────────────────────────────
st.divider()
col1, col2, col3, col4 = st.columns(4)
col1.metric("Totaal injectie",  f"{df['Injectie (kWh)'].sum():.2f} kWh")
col2.metric("Totaal afname",    f"{df['Afname (kWh)'].sum():.2f} kWh")
if "Geladen (kWh)" in df.columns:
    col3.metric("Totaal geladen",   f"{df['Geladen (kWh)'].sum():.2f} kWh")
    col4.metric("Totaal ontladen",  f"{df['Ontladen (kWh)'].sum():.2f} kWh")
