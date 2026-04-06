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
    bat_df   = battery.load_day(datum)
    soc_data = bat_df.reindex(uren)["soc"].ffill().fillna(0) if bat_df is not None else None

# ── Batterijactiviteit per uur ────────────────────────────────────────────
# OwnDev: charge/discharge kWh + nettovermogen (kWh) + SOFAR actie-labels
# API:    charge/discharge kWh uit de battery-module (geen nettovermogen beschikbaar)
bat_charge = bat_discharge = net_power_h = sofar_actions = None
if use_owndev:
    if "battery_charge_kwh" in uur_df.columns:
        bat_charge    = uur_df.reindex(uren)["battery_charge_kwh"].fillna(0)
        bat_discharge = uur_df.reindex(uren)["battery_discharge_kwh"].fillna(0)
    if "net_power_kwh" in uur_df.columns:
        net_power_h   = uur_df.reindex(uren)["net_power_kwh"].fillna(0)
    if "sofar_action" in uur_df.columns:
        sofar_actions = uur_df.reindex(uren)["sofar_action"]
else:
    if bat_df is not None:
        # battery.load_day() levert "charged" en "decharged" rechtstreeks in kWh
        bat_charge    = bat_df.reindex(uren)["charged"].fillna(0)
        bat_discharge = bat_df.reindex(uren)["decharged"].fillna(0)

has_bat = bat_charge is not None

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
# Subplotindices op naam zodat de volgorde eenvoudig te volgen is:
# 0=injectie, 1=afname, 2=SOC, [3=batterij], [3 of 4=zonneschijn]
AX_INJ = 0
AX_AFN = 1
AX_SOC = 2
AX_BAT  = 3 if has_bat else None
AX_WEER = (4 if has_bat else 3) if weer_dag is not None else None

n_rows = 3 + (1 if has_bat else 0) + (1 if weer_dag is not None else 0)
fig, axes = plt.subplots(n_rows, 1, figsize=(14, 4 * n_rows), sharex=True)
fig.suptitle(
    f"Energieoverzicht — {datum.strftime('%d/%m/%Y')}  [{bron_label}]",
    fontsize=14, fontweight="bold",
)

# Grafiek 1: Injectie
ax = axes[AX_INJ]
ax.bar(uren, inj, color=c["injectie"], width=0.7, label=f"Injectie [{bron_label}]")
_label_bars(ax, inj, c["injectie_lbl"], inj.max())
ax.set_ylabel("kWh")
ax.set_title("Injectie naar net")
ax.legend(loc="upper right")
ax.grid(axis="y", linestyle="--", alpha=0.5)

# Grafiek 2: Afname
ax = axes[AX_AFN]
ax.bar(uren, afn, color=c["afname"], width=0.7, label=f"Afname [{bron_label}]")
_label_bars(ax, afn, c["afname_lbl"], afn.max())
ax.set_ylabel("kWh")
ax.set_title("Afname van net")
ax.legend(loc="upper right")
ax.grid(axis="y", linestyle="--", alpha=0.5)

# Grafiek 3: Batterij SOC
ax = axes[AX_SOC]
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
if soc_data is not None:
    ax.legend(loc="upper right")
ax.grid(axis="y", linestyle="--", alpha=0.5)

# Grafiek 4: Batterijactiviteit (laden / ontladen / nettovermogen / SOFAR acties)
if has_bat and AX_BAT is not None:
    # Actiekleur en -afkorting per SOFAR-commandotype (conform BatMgmtV3.py actienamen)
    _ACTION_COLOR = {
        "laden tot voorziene level":             "#27ae60",
        "ontladen tot voorziene level":          "#c0392b",
        "laden door zon":                        "#f39c12",
        "overschot ontladen tot voorziene level":"#e67e22",
        "stoppen":                               "#95a5a6",
    }
    _ACTION_SHORT = {
        "laden tot voorziene level":             "L↑net",
        "ontladen tot voorziene level":          "O↓net",
        "laden door zon":                        "L☀",
        "overschot ontladen tot voorziene level":"O↓ovs",
        "stoppen":                               "■",
    }

    ax = axes[AX_BAT]
    # Groene bars voor laden, rode bars voor ontladen — licht verschoven zodat ze naast elkaar staan
    ax.bar([u - 0.2 for u in uren], bat_charge,    width=0.35, color="#2ecc71", alpha=0.85,
           label="Geladen (kWh)")
    ax.bar([u + 0.2 for u in uren], bat_discharge, width=0.35, color="#e74c3c", alpha=0.85,
           label="Ontladen (kWh)")

    # Nettovermogen als lijn op tweede Y-as (alleen beschikbaar bij OwnDev)
    if net_power_h is not None:
        ax2 = ax.twinx()
        ax2.plot(uren, net_power_h, color="#2c3e50", linewidth=1.5, linestyle="--",
                 marker=".", markersize=4, label="Nettovermogen (kWh)")
        # Nullijn: scheiding tussen afname (positief) en injectie (negatief)
        ax2.axhline(0, color="#7f8c8d", linewidth=0.6, linestyle=":")
        ax2.set_ylabel("Nettovermogen (kWh)", color="#2c3e50", fontsize=8)
        ax2.tick_params(axis="y", labelcolor="#2c3e50")
        ax2.legend(loc="upper left", fontsize=7)

    # SOFAR actie-labels boven elke uur-kolom (klein, gekleurd per actie)
    if sofar_actions is not None:
        max_y = max(bat_charge.max(), bat_discharge.max()) if (bat_charge.max() + bat_discharge.max()) > 0 else 1
        for u, action in zip(uren, sofar_actions):
            if pd.notna(action):
                a_low  = str(action).lower()
                color  = _ACTION_COLOR.get(a_low, "#bdc3c7")
                short  = _ACTION_SHORT.get(a_low, str(action)[:4])
                ax.text(u, max_y * 1.01, short, ha="center", va="bottom",
                        fontsize=6, color=color, fontweight="bold")

    ax.set_ylabel("kWh")
    ax.set_title("Batterijactiviteit per uur")
    ax.legend(loc="upper right", fontsize=7)
    ax.grid(axis="y", linestyle="--", alpha=0.5)

# Grafiek 5: Zonneschijn
if weer_dag is not None:
    ax = axes[AX_WEER]
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

# Legenda databronnen — toont enkel de actieve bron
actieve_patch = mpatches.Patch(color=c["injectie"], label=f"{bron_label} data")
fig.legend(handles=[actieve_patch], loc="lower center",
           bbox_to_anchor=(0.5, -0.01), frameon=True)

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

if bat_charge is not None:
    tabel["Geladen (kWh)"]  = bat_charge.values
    tabel["Ontladen (kWh)"] = bat_discharge.values

if net_power_h is not None:
    tabel["Nettovermogen (kWh)"] = net_power_h.values

if sofar_actions is not None:
    # Actie-afkortingen voor leesbaarheid in de tabel
    _SHORT = {
        "laden tot voorziene level":             "L↑net",
        "ontladen tot voorziene level":          "O↓net",
        "laden door zon":                        "L☀",
        "overschot ontladen tot voorziene level":"O↓ovs",
        "stoppen":                               "■",
    }
    tabel["SOFAR actie"] = sofar_actions.map(
        lambda a: _SHORT.get(str(a).lower(), str(a)) if pd.notna(a) else ""
    ).values

totaal = {"Uur": "Totaal", "Injectie (kWh)": inj.sum(), "Afname (kWh)": afn.sum()}
if soc_data is not None:
    totaal["SOC (%)"] = None   # SOC heeft geen zinvolle som
if bat_charge is not None:
    totaal["Geladen (kWh)"]  = bat_charge.sum()
    totaal["Ontladen (kWh)"] = bat_discharge.sum()
if net_power_h is not None:
    totaal["Nettovermogen (kWh)"] = net_power_h.sum()
if sofar_actions is not None:
    totaal["SOFAR actie"] = None

tabel = pd.concat([tabel, pd.DataFrame([totaal])], ignore_index=True)

def _fmt_num(v):
    if pd.isna(v) or v == 0:
        return ""
    return f"{v:.2f}"

num_cols = ["Injectie (kWh)", "Afname (kWh)", "Geladen (kWh)", "Ontladen (kWh)", "Nettovermogen (kWh)"]
# Zorg dat alle numerieke kolommen puur float zijn (Arrow-compatibel)
for col in num_cols:
    if col in tabel.columns:
        tabel[col] = pd.to_numeric(tabel[col], errors="coerce")

fmt_dict = {c: _fmt_num for c in num_cols if c in tabel.columns}
if "SOC (%)" in tabel.columns:
    tabel["SOC (%)"] = pd.to_numeric(tabel["SOC (%)"], errors="coerce")
    fmt_dict["SOC (%)"] = lambda v: "" if pd.isna(v) else f"{v:.0f}"
if "SOFAR actie" in tabel.columns:
    fmt_dict["SOFAR actie"] = lambda v: "" if pd.isna(v) or v is None else str(v)

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
