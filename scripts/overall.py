"""
overall.py
==========
Bouw en verrijk het overall-kwartierbestand (data/Final/overall.csv).

Het bestand gebruikt de Fluvius-kwartierdata als basis en verrijkt die met
alle overige beschikbare bronnen:

    Fluvius     kwartiertotalen digitale meter (kWh dag/nacht)  ← BASIS
    OwnDev      seconde-tijdreeks P1 + SOFAR → gemiddelden per kwartier
    SolarLogs   uurlijkse afname/injectie/productie van de iLumen API
    Battery     uurlijkse geladen/ontladen/SOC van de iLumen API
    Solarcharge EV-laadsessies uitgespreid per kwartier
    Weather     uurlijkse POA-instraling en weerdata (Open-Meteo + pvlib)

KOLOMMEN VAN HET OUTPUTBESTAND
--------------------------------
Kwartier-info:
    kwartier            datetime  starttijdstip van het 15-minuten-slot

Fluvius (basis, energie kWh per kwartier):
    afname_kwh          float     totale afname van het net (dag + nacht)
    injectie_kwh        float     totale injectie naar het net (dag + nacht)
    tarief              str       'dag' of 'nacht' (actief tarief in dit kwartier)
    fl_afname_dag       float     afname dagtarief
    fl_afname_nacht     float     afname nachttarief
    fl_injectie_dag     float     injectie dagtarief
    fl_injectie_nacht   float     injectie nachttarief

OwnDev (gemiddeld vermogen, kW):
    bat_laden_kw        float     gemiddeld laadvermogen batterij
    bat_ontladen_kw     float     gemiddeld ontlaadvermogen batterij
    soc_begin           int       SOC (%) bij eerste meting in kwartier
    soc_eind            int       SOC (%) bij laatste meting in kwartier
    afname_kw           float     gemiddeld vermogen afgenomen van het net
    terugave_kw         float     gemiddeld vermogen teruggegeven aan net
    n_seconden          int       aantal meetpunten (kwaliteitsindicator)

SolarLogs (energie, kWh per uur — zelfde waarde voor alle 4 kwartieren):
    sl_afname_kwh       float     afname van het net
    sl_injectie_kwh     float     injectie naar het net
    sl_productie_kwh    float     PV-productie

Battery (energie/SOC per uur — zelfde waarde voor alle 4 kwartieren):
    bat_geladen_kwh     float     geladen energie (kWh)
    bat_ontladen_kwh    float     ontladen energie (kWh)
    bat_soc_uur         int       SOC (%) aan het einde van het uur

Solarcharge (EV-laden, per kwartier):
    ev_energie_kwh      float     EV-laadenergie in dit kwartier
    ev_vermogen_kw      float     gemiddeld EV-laadvermogen in dit kwartier

Weather (per uur — zelfde waarde voor alle 4 kwartieren):
    weer_poa_w_m2       float     instraling op paneeloppervlak (W/m²)
    weer_ghi_w_m2       float     globale horizontale instraling (W/m²)
    weer_zon_min        float     zonneschijnduur (minuten per uur)

GEBRUIK
-------
    from scripts.overall import bouw

    df, pad = bouw()
    print(f"{len(df)} kwartieren → {pad}")
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from scripts import battery, fluvius, owndev, solarcharge, weather
from scripts.config import BATTERY_DIR, FINAL_DIR, SOLAR_DIR, WEATHER_CSV
from scripts.owndev import OVERALL_FILE


# ═══════════════════════════════════════════════════════════════════════════
# INTERNE HELPERS
# ═══════════════════════════════════════════════════════════════════════════

def _solar_uurlijks(datum_min: date, datum_max: date) -> pd.DataFrame:
    """
    Laad alle beschikbare SolarLogs-dagbestanden in het opgegeven bereik
    en geef een uurlijks DataFrame terug.

    Productie staat in het ruwe JSON-bestand als 'production' per record;
    solar_logs.load_day() levert dit veld niet, dus we lezen het hier direct.

    Returns:
        pd.DataFrame met index 'tijdstip_uur' (datetime, hourly) en kolommen:
            sl_afname_kwh, sl_injectie_kwh, sl_productie_kwh
    """
    dag = datum_min
    rijen: list[dict] = []

    while dag <= datum_max:
        pad = SOLAR_DIR / f"{dag.strftime('%Y%m%d')} - solar.json"
        if pad.exists():
            raw = json.loads(pad.read_text(encoding="utf-8"))
            for r in raw.get("data") or []:
                try:
                    ts = pd.to_datetime(r["valueDate"])
                    rijen.append({
                        "tijdstip_uur":   ts.floor("h"),
                        "sl_afname_kwh":   float(r.get("meterValue_afname",   0) or 0),
                        "sl_injectie_kwh": float(r.get("meterValue_injectie", 0) or 0),
                        "sl_productie_kwh":float(r.get("production",          0) or 0),
                    })
                except (KeyError, TypeError, ValueError):
                    continue
        dag += timedelta(days=1)

    if not rijen:
        return pd.DataFrame(columns=["tijdstip_uur",
                                     "sl_afname_kwh", "sl_injectie_kwh", "sl_productie_kwh"])
    return pd.DataFrame(rijen).set_index("tijdstip_uur")


def _battery_uurlijks(datum_min: date, datum_max: date) -> pd.DataFrame:
    """
    Laad alle beschikbare Battery-dagbestanden in het bereik.

    Returns:
        pd.DataFrame met index 'tijdstip_uur' en kolommen:
            bat_geladen_kwh, bat_ontladen_kwh, bat_soc_uur
    """
    dag = datum_min
    rijen: list[dict] = []

    while dag <= datum_max:
        df_dag = battery.load_day(dag)
        if df_dag is not None:
            for uur, row in df_dag.iterrows():
                rijen.append({
                    "tijdstip_uur":    pd.Timestamp(dag.year, dag.month, dag.day, uur),
                    "bat_geladen_kwh": float(row.get("geladen",  0) or 0),
                    "bat_ontladen_kwh":float(row.get("ontladen", 0) or 0),
                    "bat_soc_uur":     row.get("soc"),
                })
        dag += timedelta(days=1)

    if not rijen:
        return pd.DataFrame(columns=["tijdstip_uur",
                                     "bat_geladen_kwh", "bat_ontladen_kwh", "bat_soc_uur"])
    return pd.DataFrame(rijen).set_index("tijdstip_uur")


def _weather_uurlijks() -> pd.DataFrame:
    """
    Laad de weer-CSV en hernoem de relevante kolommen naar de overall-naamconventie.

    Returns:
        pd.DataFrame met index 'tijdstip_uur' en kolommen:
            weer_poa_w_m2, weer_ghi_w_m2, weer_zon_min
    """
    if not WEATHER_CSV.exists():
        return pd.DataFrame(columns=["tijdstip_uur",
                                     "weer_poa_w_m2", "weer_ghi_w_m2", "weer_zon_min"])

    df_w = weather.load()

    # Hernoemen naar overall-naamconventie
    hernoeming = {
        "poa_irradiance":       "weer_poa_w_m2",
        "shortwave_radiation":  "weer_ghi_w_m2",
        "sunshine_min_per_hour":"weer_zon_min",
    }
    df_w = df_w.rename(columns={k: v for k, v in hernoeming.items() if k in df_w.columns})

    kolommen = [c for c in ["weer_poa_w_m2", "weer_ghi_w_m2", "weer_zon_min"]
                if c in df_w.columns]
    df_w.index = pd.to_datetime(df_w.index).floor("h")
    df_w.index.name = "tijdstip_uur"
    return df_w[kolommen]


def _fluvius_kwartier() -> pd.DataFrame:
    """
    Laad de Fluvius-kwartierdata en hernoem kolommen naar overall-naamconventie.

    Returns:
        pd.DataFrame geïndexeerd op 'kwartier' met kolommen:
            fl_afname_dag, fl_afname_nacht, fl_injectie_dag, fl_injectie_nacht
    """
    df_fl = fluvius.laad()
    if df_fl.empty:
        return pd.DataFrame(columns=["kwartier",
                                     "fl_afname_dag", "fl_afname_nacht",
                                     "fl_injectie_dag", "fl_injectie_nacht"])
    df_fl = df_fl.rename(columns={
        "afname_dag":     "fl_afname_dag",
        "afname_nacht":   "fl_afname_nacht",
        "injectie_dag":   "fl_injectie_dag",
        "injectie_nacht": "fl_injectie_nacht",
    })
    return df_fl[["kwartier", "fl_afname_dag", "fl_afname_nacht",
                  "fl_injectie_dag", "fl_injectie_nacht"]].set_index("kwartier")


def _solarcharge_kwartier() -> pd.DataFrame:
    """
    Laad de EV-laadsessiedata per kwartier.

    Meerdere sessies kunnen hetzelfde kwartierslot overlappen; ze worden
    opgeteld (energie) respectievelijk gemiddeld (vermogen).

    Returns:
        pd.DataFrame geïndexeerd op 'kwartier' met kolommen:
            ev_energie_kwh, ev_vermogen_kw
    """
    df_ev = solarcharge.available_sessions()
    if df_ev is None or df_ev.empty:
        return pd.DataFrame(columns=["kwartier", "ev_energie_kwh", "ev_vermogen_kw"])

    agg = (
        df_ev.groupby("kwartier")
        .agg(
            ev_energie_kwh=("energie_kwh",    "sum"),
            ev_vermogen_kw=("gem_vermogen_kw", "mean"),
        )
        .reset_index()
        .set_index("kwartier")
    )
    return agg


# ═══════════════════════════════════════════════════════════════════════════
# PUBLIEKE FUNCTIE
# ═══════════════════════════════════════════════════════════════════════════

def bouw(output_file: Path | None = None) -> tuple[pd.DataFrame, Path]:
    """
    Bouw het verrijkte kwartierbestand door alle bronnen samen te voegen.

    Stappenplan:
      1. Fluvius kwartierdata als basis laden.
         Totaalkolommen afname_kwh en injectie_kwh aanmaken.
         Tariefkolom 'dag'/'nacht' bepalen.
      2. OwnDev seconden groeperen naar kwartieren en left-joinen.
      3. SolarLogs uurdata left-joinen op afgerond uur.
      4. Battery uurdata left-joinen op afgerond uur.
      5. Solarcharge kwartierdata left-joinen op kwartier.
      6. Weerdata left-joinen op afgerond uur.

    Alle joins zijn left-joins op de Fluvius-kwartieren: kwartieren waarvoor
    een andere bron geen data heeft krijgen NaN in de betreffende kolommen.

    Args:
        output_file (Path | None): Uitvoerpad. Standaard: OVERALL_FILE.

    Returns:
        tuple[pd.DataFrame, Path]: Het verrijkte DataFrame en het pad naar
            het opgeslagen CSV-bestand.
    """
    output_file = output_file or OVERALL_FILE

    # ── Stap 1: Fluvius-basis ─────────────────────────────────────────────
    df_fl = fluvius.laad()

    if df_fl.empty:
        FINAL_DIR.mkdir(parents=True, exist_ok=True)
        df_fl.to_csv(output_file, index=False)
        return df_fl, output_file

    # Totaalkolommen
    df_fl["afname_kwh"]   = df_fl["afname_dag"]   + df_fl["afname_nacht"]
    df_fl["injectie_kwh"] = df_fl["injectie_dag"] + df_fl["injectie_nacht"]

    # Tariefkolom: dag als er dag-activiteit is, anders nacht
    df_fl["tarief"] = (
        df_fl.apply(
            lambda r: "dag"
            if (r["afname_dag"] > 0 or r["injectie_dag"] > 0)
            else "nacht",
            axis=1,
        )
    )

    # Hernoem originele kolommen naar fl_-prefix voor duidelijkheid
    df_fl = df_fl.rename(columns={
        "afname_dag":     "fl_afname_dag",
        "afname_nacht":   "fl_afname_nacht",
        "injectie_dag":   "fl_injectie_dag",
        "injectie_nacht": "fl_injectie_nacht",
    })

    # Zet de gewenste kolomvolgorde
    kolommen_fl = ["afname_kwh", "injectie_kwh", "tarief",
                   "fl_afname_dag", "fl_afname_nacht",
                   "fl_injectie_dag", "fl_injectie_nacht"]
    df = df_fl.set_index("kwartier")[kolommen_fl]

    datum_min: date = df.index.min().date()
    datum_max: date = df.index.max().date()

    # ── Stap 2: OwnDev ───────────────────────────────────────────────────
    df_od, _ = owndev.groepeer_per_kwartier()
    if not df_od.empty:
        df_od = df_od.set_index("kwartier")
        df = df.join(df_od, how="left")

    # ── Stap 3, 4 & 6: Uurlijkse bronnen (SolarLogs + Battery + Weer) ────
    # Maak een hulpkolom 'uur' = kwartierstart afgerond naar uur.
    # Na de join wordt deze hulpkolom verwijderd.
    df["_uur"] = df.index.floor("h")

    df_sl  = _solar_uurlijks(datum_min, datum_max)
    df_bat = _battery_uurlijks(datum_min, datum_max)
    df_w   = _weather_uurlijks()

    for df_bron in [df_sl, df_bat, df_w]:
        if df_bron.empty:
            continue
        df = df.join(df_bron, on="_uur", how="left")

    df = df.drop(columns=["_uur"])

    # ── Stap 5: Solarcharge ───────────────────────────────────────────────
    df = df.join(_solarcharge_kwartier(), how="left")

    # ── Opslaan ───────────────────────────────────────────────────────────
    df = df.reset_index()
    FINAL_DIR.mkdir(parents=True, exist_ok=True)
    df.to_csv(output_file, index=False, date_format="%Y-%m-%d %H:%M:%S")

    return df, output_file
