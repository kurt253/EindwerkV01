"""
battery.py
==========
Lees en download SolarBattery-data (laden, ontladen, SOC per uur).

De JSON-bestanden staan in BATTERY_DIR en hebben het naamformaat
``YYYYMMDD - solar.json``. Ze worden aangemaakt door de iLumen API
(actie ``ilubat_day_v2``).

Elke record per uur bevat:
    - charged       (float) kWh geladen in het uur
    - decharged     (float) kWh ontladen in het uur
    - soc           (int)   State of Charge op het einde van het uur (%)
    - amount_charged  (float) kostprijs laden (EUR)
    - amount_decharged(float) kostprijs ontladen (EUR)
"""

from __future__ import annotations

import json
import time
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import requests

from scripts import config

_VERTRAGING_SEC: float = 0.5


# ── Bestandspaden ─────────────────────────────────────────────────────────

def _pad(datum: date, data_dir: Path) -> Path:
    return data_dir / f"{datum.strftime('%Y%m%d')} - solar.json"


def available_dates(data_dir: Path | None = None) -> list[date]:
    """
    Gesorteerde lijst van alle datums waarvoor een lokaal batterij-JSON-bestand bestaat.

    Args:
        data_dir (Path|None): Map met de JSON-bestanden. Standaard: config.BATTERY_DIR.

    Returns:
        list[date]: Gesorteerde lijst van date-objecten.
    """
    data_dir = data_dir or config.BATTERY_DIR
    dates = []
    for path in sorted(data_dir.glob("???????? - solar.json")):
        try:
            dates.append(date(int(path.name[:4]), int(path.name[4:6]), int(path.name[6:8])))
        except ValueError:
            continue
    return dates


# ── Inlezen van lokale bestanden ──────────────────────────────────────────

def load_day(datum: date, data_dir: Path | None = None) -> pd.DataFrame | None:
    """
    Lees batterijdata voor één dag uit een lokaal JSON-bestand.

    Args:
        datum    (date):      De dag om te laden.
        data_dir (Path|None): Map met de JSON-bestanden. Standaard: config.BATTERY_DIR.

    Returns:
        pd.DataFrame: Geïndexeerd op uur (0–23), met kolommen:
                      - geladen    (float): kWh geladen in het net dat uur.
                      - ontladen   (float): kWh ontladen in het net dat uur.
                      - soc        (int):   State of Charge (%) op het einde van het uur.
        None: Als het JSON-bestand niet bestaat.
    """
    data_dir = data_dir or config.BATTERY_DIR
    path = _pad(datum, data_dir)
    if not path.exists():
        return None

    raw = json.loads(path.read_text(encoding="utf-8"))
    records = raw.get("data") or []
    if not records:
        return None
    df = pd.DataFrame(records)
    df["valueDate"] = pd.to_datetime(df["valueDate"])
    df["uur"]      = df["valueDate"].dt.hour
    df["geladen"]  = df["charged"].astype(float)
    df["ontladen"] = df["decharged"].astype(float)
    df["soc"]      = df["soc"].astype(int)
    return df[["uur", "geladen", "ontladen", "soc"]].set_index("uur").sort_index()


# ── API: ophalen via iLumen ───────────────────────────────────────────────

def _fetch_raw(datum: date) -> dict:
    """
    Haal ruwe batterijdata op voor één dag via de iLumen API.

    Args:
        datum (date): De dag om op te halen.

    Returns:
        dict: Ruwe JSON-respons met sleutels 'data' en 'tot'.

    Raises:
        requests.HTTPError: Bij HTTP-fout.
        requests.Timeout:   Bij time-out.
    """
    resp = requests.post(
        config.BATTERY_API_URL,
        headers={
            "AUTH_key":     config.battery_auth_key(),
            "Content-Type": "application/json",
        },
        json={
            "action": "ilubat_day_v2",
            "sn":     config.BATTERY_SN,
            "date":   datum.strftime("%Y-%m-%d"),
        },
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def download_range(
    start: date,
    end: date,
    output_dir: Path | None = None,
    overschrijven: bool = False,
) -> tuple[list[date], dict[date, str]]:
    """
    Download batterijdata voor elke dag in [start, end] en sla op als JSON.

    Bestaande bestanden worden overgeslagen tenzij overschrijven=True.

    Args:
        start         (date):      Eerste dag (inclusief).
        end           (date):      Laatste dag (inclusief).
        output_dir    (Path|None): Doelmap. Standaard: config.BATTERY_DIR.
        overschrijven (bool):      Overschrijf bestaande bestanden.

    Returns:
        tuple: (opgeslagen: list[date], fouten: dict[date, str])
    """
    output_dir = output_dir or config.BATTERY_DIR
    output_dir.mkdir(parents=True, exist_ok=True)

    opgeslagen: list[date]      = []
    fouten:     dict[date, str] = {}

    dag = start
    while dag <= end:
        path = _pad(dag, output_dir)
        if not overschrijven and path.exists():
            dag += timedelta(days=1)
            continue
        try:
            data = _fetch_raw(dag)
            path.write_text(json.dumps(data, indent=4, ensure_ascii=False), encoding="utf-8")
            opgeslagen.append(dag)
            time.sleep(_VERTRAGING_SEC)
        except Exception as exc:
            fouten[dag] = str(exc)
        dag += timedelta(days=1)

    return opgeslagen, fouten
