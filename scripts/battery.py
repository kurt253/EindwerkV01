"""
Batterij data — SolarBattery API (ilucharge_api.php)
=====================================================

Verantwoordelijkheden
---------------------
* Ophalen van uurlijkse batterijdata via de SolarBattery REST-API (POST-requests).
* Lokaal opslaan als JSON per dag (YYYYMMDD - solar.json) in BATTERY_DIR.
* Inlezen van die lokale bestanden naar pandas DataFrames voor gebruik in de app.

Geleverde data per dag
----------------------
Per uur:
  - soc        : State of Charge in % (0–100)
  - charged    : energie geladen uit het net in kWh
  - decharged  : energie teruggeleverd aan het net in kWh

Dagelijkse totalen (via "tot"-blok in de API-respons):
  - Geladen (kWh)        : totaal geladen gedurende de dag
  - Ontladen (kWh)       : totaal ontladen gedurende de dag
  - Kost laden (€)       : netafnamekosten voor het laden
  - Opbrengst ontl. (€)  : opbrengst van teruglevering na ontladen

Authenticatie
-------------
De AUTH_key header wordt opgehaald via scripts.config.battery_auth_key(),
die de sleutel uit de Windows Credential Manager leest (keyring).
De sleutel wordt nooit in .env of broncode opgeslagen.

Retry-mechanisme
----------------
De API retourneert soms een leeg "data"-veld bij snelle opeenvolgende
aanvragen. fetch_day() herprobeert automatisch tot max_retries keer
(standaard 10) met een pauze van delay seconden (standaard 2.5 s).

Publieke functies
-----------------
  fetch_day(jaar, maand, dag)          → dict   (ruwe API-respons)
  download_range(start, end)           → list[Path]
  load_day(datum)                      → DataFrame | None
  load_all()                           → DataFrame (dagelijkse totalen)
  available_dates()                    → list[date]
"""

import json
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
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
}


def fetch_day(jaar: int, maand: int, dag: int, max_retries: int = 10, delay: float = 2.5) -> dict:
    """
    Haal uurlijkse batterijdata op voor één dag via de SolarBattery API.

    De API retourneert soms een leeg "data"-veld bij snelle opeenvolgende aanvragen.
    De functie herprobeert automatisch tot max_retries keer met een pauze van delay seconden.

    Args:
        jaar        (int):   Het jaar (bv. 2026).
        maand       (int):   De maand (1–12).
        dag         (int):   De dag (1–31).
        max_retries (int):   Maximum aantal pogingen bij lege API-respons. Standaard: 10.
        delay       (float): Wachttijd in seconden tussen pogingen. Standaard: 2.5.

    Returns:
        dict: Ruwe API-respons met sleutels:
              - "data" (lijst van uurrecords met soc, charged, decharged).
              - "tot"  (dagelijkse samenvatting met charged, decharged, amount_charged, amount_decharged).
              Retourneert het laatste antwoord ook als data leeg bleef na alle pogingen.

    Raises:
        ValueError: Als de datum ongeldig is (bv. 30 februari).
    """
    try:
        _ = date(jaar, maand, dag)
    except ValueError:
        raise ValueError(f"Ongeldige datum: {jaar}-{maand:02d}-{dag:02d}")

    headers = {**_HEADERS, "AUTH_key": config.battery_auth_key()}
    payload = {
        "action": "ilubat_day_v2",
        "sn":     config.BATTERY_SN,
        "date":   f"{jaar}-{maand:02d}-{dag:02d}",
    }

    last: dict = {}
    for attempt in range(1, max_retries + 1):
        try:
            resp = requests.post(config.BATTERY_API_URL, headers=headers, data=payload, timeout=15)
            resp.raise_for_status()
            data = resp.json()
            last = data  # bewaar altijd het laatste antwoord als noodoplossing
            field = data.get("data")
            # De API retourneert soms een leeg "data"-veld bij te snelle opeenvolgende requests;
            # herhaal dan de aanvraag na een korte pauze
            if field:
                return data
        except requests.RequestException:
            pass
        if attempt < max_retries:
            time.sleep(delay)

    # Alle pogingen mislukt of data bleef leeg → retourneer toch het laatste antwoord
    return last


def download_range(start: date, end: date, output_dir: Path | None = None) -> list[Path]:
    """
    Download batterijdata voor elke dag in het bereik [start, end] en sla op als JSON.

    Args:
        start      (date):      Eerste dag van het bereik (inclusief).
        end        (date):      Laatste dag van het bereik (inclusief).
        output_dir (Path|None): Map waar bestanden worden opgeslagen.
                                Standaard: config.BATTERY_DIR.

    Returns:
        list[Path]: Lijst van paden naar alle opgeslagen JSON-bestanden.
    """
    output_dir = output_dir or config.BATTERY_DIR
    output_dir.mkdir(parents=True, exist_ok=True)

    saved = []
    dag = start
    while dag <= end:
        data = fetch_day(dag.year, dag.month, dag.day)
        path = output_dir / f"{dag.strftime('%Y%m%d')} - solar.json"
        path.write_text(json.dumps(data, indent=4), encoding="utf-8")
        saved.append(path)
        dag += timedelta(days=1)
    return saved


def load_day(datum: date, data_dir: Path | None = None) -> pd.DataFrame | None:
    """
    Lees batterijdata voor één dag uit een lokaal JSON-bestand.

    Args:
        datum    (date):      De dag om te laden.
        data_dir (Path|None): Map met de JSON-bestanden.
                              Standaard: config.BATTERY_DIR.

    Returns:
        pd.DataFrame: Geïndexeerd op uur (0–23), met kolommen:
                      - soc       (float): State of Charge in % (0–100) aan het einde van het uur.
                      - charged   (float): Energie geladen in kWh gedurende dat uur.
                      - decharged (float): Energie ontladen in kWh gedurende dat uur.
        None: Als het bestand niet bestaat of geen meetdata bevat.
    """
    data_dir = data_dir or config.BATTERY_DIR
    path = data_dir / f"{datum.strftime('%Y%m%d')} - solar.json"
    if not path.exists():
        return None

    raw = json.loads(path.read_text(encoding="utf-8"))
    # Sommige bestanden bevatten enkel metadata zonder meetpunten (bv. dag zonder batterijactiviteit)
    if not raw.get("data"):
        return None

    df = pd.DataFrame(raw["data"])
    df["valueDate"] = pd.to_datetime(df["valueDate"])
    df["uur"]       = df["valueDate"].dt.hour
    # soc = State of Charge in % (0–100)
    df["soc"]       = df["soc"].astype(float)
    # charged/decharged = energie in kWh geladen resp. ontladen gedurende dat uur
    df["charged"]   = df["charged"].astype(float)
    df["decharged"] = df["decharged"].astype(float)
    return df.set_index("uur").sort_index()


def load_all(data_dir: Path | None = None) -> pd.DataFrame:
    """
    Laad alle lokale JSON-bestanden en combineer tot een DataFrame met dagelijkse totalen.

    Args:
        data_dir (Path|None): Map met de JSON-bestanden.
                              Standaard: config.BATTERY_DIR.

    Returns:
        pd.DataFrame: Één rij per dag, gesorteerd op datum, met kolommen:
                      - Datum              (datetime): de datum.
                      - Geladen (kWh)      (float):    totaal geladen gedurende de dag.
                      - Ontladen (kWh)     (float):    totaal ontladen gedurende de dag.
                      - Kost laden (€)     (float):    netafnamekosten voor het laden.
                      - Opbrengst ontl. (€)(float):    opbrengst van teruglevering na ontladen.
                      Lege DataFrame als er geen geldige bestanden zijn.
    """
    data_dir = data_dir or config.BATTERY_DIR
    rows = []
    for path in sorted(data_dir.glob("*.json")):
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            # "tot" bevat de dagelijkse samenvattingen; ontbreekt als de API geen data had
            if not raw.get("tot"):
                continue
            tot = raw["tot"]
            row = {
                # Datum uit de eerste 8 tekens van de bestandsnaam (YYYYMMDD)
                "Datum":             path.name[:8],
                "Geladen (kWh)":     float(tot.get("charged", 0)),
                "Ontladen (kWh)":    float(tot.get("decharged", 0)),
                # amount_charged = kosten van netafname voor het laden (€)
                "Kost laden (€)":    float(tot.get("amount_charged", 0)),
                # amount_decharged = opbrengst van teruglevering na ontladen (€)
                "Opbrengst ontl. (€)": float(tot.get("amount_decharged", 0)),
            }
            rows.append(row)
        except Exception:
            continue

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)
    df["Datum"] = pd.to_datetime(df["Datum"], format="%Y%m%d")
    return df.sort_values("Datum").reset_index(drop=True)


def available_dates(data_dir: Path | None = None) -> list[date]:
    """
    Geef een gesorteerde lijst van alle datums waarvoor een lokaal JSON-bestand bestaat.

    Args:
        data_dir (Path|None): Map met de JSON-bestanden.
                              Standaard: config.BATTERY_DIR.

    Returns:
        list[date]: Gesorteerde lijst van date-objecten. Leeg als er geen bestanden zijn.
    """
    data_dir = data_dir or config.BATTERY_DIR
    dates = []
    for path in sorted(data_dir.glob("*.json")):
        try:
            d = date(int(path.name[:4]), int(path.name[4:6]), int(path.name[6:8]))
            dates.append(d)
        except ValueError:
            continue
    return dates
