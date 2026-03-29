"""
Solar meter data: ophalen via API en inlezen van lokale bestanden.
"""

import json
import os
import time
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import requests

from scripts import config


_HEADERS = {
    "Accept": "*/*",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "User-Agent": "PostmanRuntime/7.52.0",
}


def fetch_day(jaar: int, maand: int, dag: int) -> dict:
    """Haal meterwaarden op voor één dag via de API. Retourneert de JSON als dict."""
    try:
        # Gebruik de date-constructor puur als validatie — gooit ValueError bij bv. dag 32
        _ = date(jaar, maand, dag)
    except ValueError:
        raise ValueError(f"Ongeldige datum: {jaar}-{maand:02d}-{dag:02d}")

    # AUTH_key wordt per request als header meegegeven (niet als query-parameter)
    headers = {**_HEADERS, "AUTH_key": config.solar_auth_key()}
    payload = {
        "action":  "metervalues_day",
        "adresid": config.SOLAR_ADRESID,
        "year":    str(jaar),
        "month":   str(maand),
        "day":     str(dag),
    }

    response = requests.post(config.SOLAR_API_URL, headers=headers, data=payload, timeout=12)
    response.raise_for_status()
    return response.json()


def download_range(start: date, end: date, output_dir: Path | None = None) -> list[Path]:
    """Download en sla op voor elke dag in [start, end]. Retourneert lijst van opgeslagen paden."""
    output_dir = output_dir or config.SOLAR_DIR
    output_dir.mkdir(parents=True, exist_ok=True)

    saved = []
    dag = start
    while dag <= end:
        data = fetch_day(dag.year, dag.month, dag.day)
        # Bestandsnaam: YYYYMMDD - solar.json  (vaste naamconventie voor parse in available_dates)
        path = output_dir / f"{dag.strftime('%Y%m%d')} - solar.json"
        path.write_text(json.dumps(data, indent=4), encoding="utf-8")
        saved.append(path)
        dag += timedelta(days=1)
    return saved


def load_day(datum: date, data_dir: Path | None = None) -> pd.DataFrame | None:
    """Lees één dag uit lokaal JSON-bestand. Retourneert DataFrame of None als bestand ontbreekt."""
    data_dir = data_dir or config.SOLAR_DIR
    path = data_dir / f"{datum.strftime('%Y%m%d')} - solar.json"
    if not path.exists():
        return None

    raw = json.loads(path.read_text(encoding="utf-8"))
    df = pd.DataFrame(raw["data"])
    df["valueDate"] = pd.to_datetime(df["valueDate"])
    # Uur extraheren als geheel getal (0–23) zodat het als index bruikbaar is
    df["uur"] = df["valueDate"].dt.hour
    # Expliciete cast naar float: de API levert soms strings in plaats van getallen
    df["injectie"] = df["meterValue_injectie"].astype(float)
    df["afname"]   = df["meterValue_afname"].astype(float)
    df["meterValue"] = df["meterValue"].astype(float)
    return df.set_index("uur").sort_index()


def load_all(data_dir: Path | None = None) -> pd.DataFrame:
    """
    Laad alle lokale JSON-bestanden en combineer tot een breed DataFrame:
    index = datum, kolommen = 00:00 t/m 23:00 (meterValue per uur).
    """
    data_dir = data_dir or config.SOLAR_DIR
    rows = []
    for path in sorted(data_dir.glob("*.json")):
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            # Sla bestanden over met fout-status of zonder meetdata
            if raw.get("status") != "OK" or not raw.get("data"):
                continue
            first = raw["data"][0]
            # Datumstring ophalen uit de eerste meting (eerste 10 tekens = YYYY-MM-DD)
            dag_str = first["valueDate"][:10]
            row = {"Datum": dag_str}
            for rec in raw["data"]:
                # Kolomnaam = "HH:00" → één kolom per uur voor brede pivotweergave
                uur = pd.to_datetime(rec["valueDate"]).hour
                row[f"{uur:02d}:00"] = float(rec["meterValue"])
            rows.append(row)
        except Exception:
            continue

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)
    df["Datum"] = pd.to_datetime(df["Datum"])
    df = df.sort_values("Datum").reset_index(drop=True)
    # Behoud alleen de uurkolommen die daadwerkelijk aanwezig zijn (niet alle bestanden bevatten 24 uur)
    uur_cols = [c for c in [f"{i:02d}:00" for i in range(24)] if c in df.columns]
    return df[["Datum"] + uur_cols]


def available_dates(data_dir: Path | None = None) -> list[date]:
    """Geef een gesorteerde lijst van alle beschikbare datums in de lokale map."""
    data_dir = data_dir or config.SOLAR_DIR
    dates = []
    for path in sorted(data_dir.glob("*.json")):
        try:
            # Bestandsnaam heeft formaat YYYYMMDD - solar.json; eerste 8 tekens zijn de datum
            d = date(int(path.name[:4]), int(path.name[4:6]), int(path.name[6:8]))
            dates.append(d)
        except ValueError:
            # Sla bestanden over waarvan de naam niet met een geldige datum begint
            continue
    return dates
