"""
Dag Grafiek: injectie, afname en batterij SOC per uur voor een gekozen dag.
"""

import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
import streamlit as st

from scripts import battery, solar_logs

st.set_page_config(page_title="Dag Grafiek", page_icon="📊", layout="wide")
st.title("📊 Dag Grafiek")

# ── Datumkiezer ───────────────────────────────────────────────────────────
dates = solar_logs.available_dates()
if not dates:
    st.error("Geen lokale solar data gevonden. Download eerst data via ⬇️ Data Ophalen.")
    st.stop()

datum = st.date_input(
    "Kies een datum",
    value=dates[-1],
    min_value=dates[0],
    max_value=dates[-1],
)

# ── Data laden ────────────────────────────────────────────────────────────
solar_df = solar_logs.load_day(datum)
if solar_df is None:
    st.warning(f"Geen solar data voor {datum}.")
    st.stop()

battery_df = battery.load_day(datum)
if battery_df is None:
    st.info("Geen batterijdata beschikbaar voor deze dag — SOC grafiek wordt weggelaten.")

# ── Grafieken ─────────────────────────────────────────────────────────────
uren = list(range(24))
n_plots = 3 if battery_df is not None else 2
fig, axes = plt.subplots(n_plots, 1, figsize=(14, 4 * n_plots), sharex=True)
fig.suptitle(f"Energieoverzicht — {datum.strftime('%d/%m/%Y')}", fontsize=14, fontweight="bold")

# Injectie
ax = axes[0]
inj = solar_df.reindex(uren)["injectie"].fillna(0)
ax.bar(uren, inj, color="#2ecc71", width=0.7, label="Injectie")
ax.set_ylabel("kWh")
ax.set_title("Injectie naar net")
ax.legend(loc="upper right")
ax.grid(axis="y", linestyle="--", alpha=0.5)

# Afname
ax = axes[1]
afn = solar_df.reindex(uren)["afname"].fillna(0)
ax.bar(uren, afn, color="#e74c3c", width=0.7, label="Afname")
ax.set_ylabel("kWh")
ax.set_title("Afname van net")
ax.legend(loc="upper right")
ax.grid(axis="y", linestyle="--", alpha=0.5)

# SOC
if battery_df is not None:
    ax = axes[2]
    soc = battery_df.reindex(uren)["soc"].ffill().fillna(0)
    ax.plot(uren, soc, color="#3498db", marker="o", linewidth=2, label="SOC batterij")
    ax.fill_between(uren, soc, alpha=0.15, color="#3498db")
    ax.set_ylim(0, 105)
    ax.set_ylabel("%")
    ax.set_title("Laadtoestand batterij (SOC)")
    ax.legend(loc="upper right")
    ax.grid(axis="y", linestyle="--", alpha=0.5)

axes[-1].set_xlabel("Uur")
axes[-1].set_xticks(uren)
axes[-1].set_xticklabels([f"{u:02d}:00" for u in uren], rotation=45, ha="right")
plt.tight_layout()

st.pyplot(fig)

# ── Ruwe data tabel ───────────────────────────────────────────────────────
with st.expander("Ruwe data"):
    st.dataframe(solar_df[["injectie", "afname", "meterValue"]].rename(
        columns={"meterValue": "netto (kWh)"}
    ))
