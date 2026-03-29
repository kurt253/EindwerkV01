"""
Dag Grafiek: injectie, afname, batterij SOC en zonneschijn per uur.
Kleurcode: groen/rood/blauw = API-data  |  teal/oranje/paars = OwnDev-data
"""

import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
import pandas as pd
import streamlit as st

from scripts import battery, owndev, solar_logs, weather

st.set_page_config(page_title="Dag Grafiek", page_icon="📊", layout="wide")
st.title("📊 Dag Grafiek")

# ── Kleurschema ───────────────────────────────────────────────────────────
COLORS = {
    "api":    {"injectie": "#2ecc71", "afname": "#e74c3c", "soc": "#3498db",
               "injectie_lbl": "#1a7a43", "afname_lbl": "#922b21", "soc_lbl": "#1a5276"},
    "owndev": {"injectie": "#1abc9c", "afname": "#e67e22", "soc": "#9b59b6",
               "injectie_lbl": "#0e6655", "afname_lbl": "#935116", "soc_lbl": "#6c3483"},
}

# ── Datumkiezer ───────────────────────────────────────────────────────────
all_solar   = solar_logs.available_dates()
all_owndev  = owndev.available_dates()
# Samenvoegen van beide bronnen zodat de datumkiezer alle beschikbare dagen toont
all_dates   = sorted(set(all_solar) | set(all_owndev))

if not all_dates:
    st.error("Geen lokale data gevonden.")
    st.stop()

datum = st.date_input(
    "Kies een datum",
    value=all_dates[-1],
    min_value=all_dates[0],
    max_value=all_dates[-1],
)

# ── Bronbepaling ──────────────────────────────────────────────────────────
has_owndev = datum in all_owndev
has_api    = datum in all_solar

if has_owndev and has_api:
    # Beide bronnen beschikbaar: gebruiker kiest zelf
    bron = st.radio("Databron", ["OwnDev (minuutdata)", "API (uurdata)"], horizontal=True)
    use_owndev = bron.startswith("OwnDev")
elif has_owndev:
    # Alleen OwnDev aanwezig voor deze dag (bv. voor recente dagen zonder API-download)
    use_owndev = True
    st.info("Alleen OwnDev data beschikbaar voor deze dag.")
else:
    # Alleen API-data aanwezig
    use_owndev = False

c = COLORS["owndev"] if use_owndev else COLORS["api"]
bron_label = "OwnDev" if use_owndev else "API"

# ── Data laden ────────────────────────────────────────────────────────────
if use_owndev:
    uur_df = owndev.load_day_hourly(datum)
    if uur_df is None:
        st.warning("OwnDev data kon niet worden geladen.")
        st.stop()
    soc_col = "battery_soc_pct"
else:
    uur_df = solar_logs.load_day(datum)
    if uur_df is None:
        st.warning(f"Geen solar data voor {datum}.")
        st.stop()
    bat_df = battery.load_day(datum)
    soc_col = None

uren = list(range(24))
# reindex garandeert dat alle 24 uren aanwezig zijn; ontbrekende uren worden 0
inj  = uur_df.reindex(uren)["injectie"].fillna(0)
afn  = uur_df.reindex(uren)["afname"].fillna(0)

if use_owndev:
    # ffill vult uren zonder SOC-meting op met de laatste bekende waarde
    soc_data = uur_df.reindex(uren)[soc_col].ffill().fillna(0) if soc_col in uur_df.columns else None
else:
    # Batterijdata komt uit een apart bestand (battery module), niet uit solar_logs
    soc_data = bat_df.reindex(uren)["soc"].ffill().fillna(0) if (bat_df := battery.load_day(datum)) is not None else None

# Zonneschijn
weer_df = None
try:
    weer_df = weather.load()
    dag_str = datum.strftime("%Y-%m-%d")
    weer_dag = weer_df[weer_df.index.strftime("%Y-%m-%d") == dag_str]
    if weer_dag.empty:
        weer_dag = None
except Exception:
    weer_dag = None


# ── Hulpfunctie: labels op staven ────────────────────────────────────────
def _label_bars(ax, values, color, max_val):
    if max_val == 0:
        return
    for x, v in enumerate(values):
        # Waarden kleiner dan 1 Wh weergeven heeft geen praktische meerwaarde
        if v > 0.001:
            # Label 1,5% boven de staaf zodat het niet overlapt met de bovenkant
            ax.text(x, v + max_val * 0.015, f"{v:.2f}",
                    ha="center", va="bottom", fontsize=6.5, color=color)


# ── Grafieken opbouwen ───────────────────────────────────────────────────
# Aantal grafieken: altijd 3 (injectie, afname, SOC) + optioneel 1 voor zonneschijn
n_rows = 3 + (1 if weer_dag is not None else 0)
fig, axes = plt.subplots(n_rows, 1, figsize=(14, 4 * n_rows), sharex=True)
fig.suptitle(
    f"Energieoverzicht — {datum.strftime('%d/%m/%Y')}  [{bron_label}]",
    fontsize=14, fontweight="bold",
)

# Grafiek 1: Injectie
ax = axes[0]
ax.bar(uren, inj, color=c["injectie"], width=0.7, label=f"Injectie [{bron_label}]")
_label_bars(ax, inj, c["injectie_lbl"], inj.max())
ax.set_ylabel("kWh")
ax.set_title("Injectie naar net")
ax.legend(loc="upper right")
ax.grid(axis="y", linestyle="--", alpha=0.5)

# Grafiek 2: Afname
ax = axes[1]
ax.bar(uren, afn, color=c["afname"], width=0.7, label=f"Afname [{bron_label}]")
_label_bars(ax, afn, c["afname_lbl"], afn.max())
ax.set_ylabel("kWh")
ax.set_title("Afname van net")
ax.legend(loc="upper right")
ax.grid(axis="y", linestyle="--", alpha=0.5)

# Grafiek 3: Batterij SOC
ax = axes[2]
if soc_data is not None:
    ax.plot(uren, soc_data, color=c["soc"], marker="o", linewidth=2,
            label=f"SOC [{bron_label}]")
    ax.fill_between(uren, soc_data, alpha=0.15, color=c["soc"])
    for x, v in enumerate(soc_data):
        if not pd.isna(v):
            ax.text(x, v + 2, f"{v:.0f}%", ha="center", va="bottom",
                    fontsize=6.5, color=c["soc_lbl"])
    ax.set_ylim(0, 115)
else:
    ax.text(0.5, 0.5, "Geen batterijdata", transform=ax.transAxes,
            ha="center", va="center", color="gray")
ax.set_ylabel("%")
ax.set_title("Laadtoestand batterij (SOC)")
ax.legend(loc="upper right")
ax.grid(axis="y", linestyle="--", alpha=0.5)

# Grafiek 4: Zonneschijn
if weer_dag is not None:
    ax = axes[3]
    wx_uren = weer_dag.index.hour.tolist()

    # Zonneschijnduur ophalen (minuten per uur)
    if "sunshine_min_per_hour" in weer_dag.columns:
        zon_min = weer_dag["sunshine_min_per_hour"].fillna(0)
    elif "sunshine_duration" in weer_dag.columns:
        zon_min = weer_dag["sunshine_duration"].fillna(0) / 60
    else:
        zon_min = pd.Series(60.0, index=weer_dag.index)  # geen data: ga uit van vol uur

    # Effectieve energie op de panelen:
    # poa_irradiance is gemiddeld vermogen over het uur (W/m²),
    # maar de zon schijnt slechts een deel van het uur.
    # Wh/m² = W/m² × (effectieve uren) = poa_irradiance × (sunshine_min / 60)
    if "poa_irradiance" in weer_dag.columns:
        rad = (weer_dag["poa_irradiance"].fillna(0) * zon_min / 60).tolist()
        rad_label = "Effectieve instraling op paneel WNW (Wh/m²)"
    elif "shortwave_radiation" in weer_dag.columns:
        rad = (weer_dag["shortwave_radiation"].fillna(0) * zon_min / 60).tolist()
        rad_label = "Effectieve instraling horizontaal (Wh/m²)"
    else:
        rad, rad_label = [], ""

    zon_min = zon_min.tolist()

    if rad:
        ax.bar(wx_uren, rad, color="#f39c12", width=0.7, alpha=0.8, label=rad_label)
        if rad:
            for x, v in zip(wx_uren, rad):
                if v > 5:
                    ax.text(x, v + max(rad) * 0.015, f"{v:.0f}",
                            ha="center", va="bottom", fontsize=6.5, color="#b7770d")

    if zon_min:
        # Tweede Y-as voor zonneschijn (min/uur) naast de instraling-as (W/m²)
        ax2 = ax.twinx()
        ax2.plot(wx_uren, zon_min, color="#c0392b", marker="s", linewidth=1.5,
                 linestyle="--", markersize=4, label="Zonneschijn (min/uur)")
        ax2.set_ylim(0, 65)  # Maximum is 60 min/uur; kleine marge voor leesbaarheid
        ax2.set_ylabel("min/uur", color="#c0392b")
        ax2.tick_params(axis="y", labelcolor="#c0392b")
        ax2.legend(loc="upper left")

    ax.set_ylabel("Wh/m²")
    ax.set_title("Zonneschijn & instraling")
    if rad:
        ax.legend(loc="upper right")
    ax.grid(axis="y", linestyle="--", alpha=0.5)

# X-as
axes[-1].set_xlabel("Uur")
axes[-1].set_xticks(uren)
axes[-1].set_xticklabels([f"{u:02d}:00" for u in uren], rotation=45, ha="right")

# Legenda databronnen
api_patch    = mpatches.Patch(color=COLORS["api"]["injectie"],    label="API data")
owndev_patch = mpatches.Patch(color=COLORS["owndev"]["injectie"], label="OwnDev data")
fig.legend(handles=[api_patch, owndev_patch], loc="lower center",
           ncol=2, bbox_to_anchor=(0.5, -0.01), frameon=True)

plt.tight_layout()
st.pyplot(fig)

# ── Overzichtstabel ───────────────────────────────────────────────────────
st.subheader("Overzicht per uur")

tabel = pd.DataFrame({
    "Uur":            [f"{u:02d}:00" for u in uren],
    "Injectie (kWh)": inj.values,
    "Afname (kWh)":   afn.values,
})

if soc_data is not None:
    tabel["SOC (%)"] = soc_data.values

totaal = {"Uur": "Totaal", "Injectie (kWh)": inj.sum(), "Afname (kWh)": afn.sum()}
if soc_data is not None:
    totaal["SOC (%)"] = None  # float-kolom houden, geen lege string (sommeer geen SOC — heeft geen zin)

tabel = pd.concat([tabel, pd.DataFrame([totaal])], ignore_index=True)

# Zorg dat numerieke kolommen puur float zijn (Arrow-compatibel)
# pd.concat kan gemengde types introduceren doordat de totaalrij dict-waarden bevat
for col in ["Injectie (kWh)", "Afname (kWh)"]:
    tabel[col] = pd.to_numeric(tabel[col], errors="coerce")
if "SOC (%)" in tabel.columns:
    tabel["SOC (%)"] = pd.to_numeric(tabel["SOC (%)"], errors="coerce")

def _fmt_num(v):
    if pd.isna(v) or v == 0:
        return ""
    return f"{v:.2f}"

fmt_dict = {"Injectie (kWh)": _fmt_num, "Afname (kWh)": _fmt_num}
if "SOC (%)" in tabel.columns:
    fmt_dict["SOC (%)"] = lambda v: "" if pd.isna(v) else f"{v:.0f}"

styled = (
    tabel.style
    .format(fmt_dict)
    .apply(
        lambda row: ["font-weight: bold; background-color: #f0f0f0"] * len(row)
        if row["Uur"] == "Totaal" else [""] * len(row),
        axis=1,
    )
)

st.dataframe(styled, width="stretch", hide_index=True)

# ── Bronbadge ─────────────────────────────────────────────────────────────
kleur = "#1abc9c" if use_owndev else "#2ecc71"
st.markdown(
    f'<span style="background:{kleur};color:white;padding:3px 10px;'
    f'border-radius:4px;font-size:0.8em">Bron: {bron_label}</span>',
    unsafe_allow_html=True,
)
