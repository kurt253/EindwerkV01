"""
Batterij data: ophalen via API en inlezen van lokale bestanden.
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
    Haal batterijdata op voor één dag. Herhaalt tot 'data' gevuld is of max_retries bereikt.
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
            last = data
            field = data.get("data")
            if field:
                return data
        except requests.RequestException:
            pass
        if attempt < max_retries:
            time.sleep(delay)

    return last


def download_range(start: date, end: date, output_dir: Path | None = None) -> list[Path]:
    """Download en sla op voor elke dag in [start, end]."""
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
    """Lees één dag batterijdata. Retourneert DataFrame met kolommen soc, charged, decharged."""
    data_dir = data_dir or config.BATTERY_DIR
    path = data_dir / f"{datum.strftime('%Y%m%d')} - solar.json"
    if not path.exists():
        return None

    raw = json.loads(path.read_text(encoding="utf-8"))
    if not raw.get("data"):
        return None

    df = pd.DataFrame(raw["data"])
    df["valueDate"] = pd.to_datetime(df["valueDate"])
    df["uur"]       = df["valueDate"].dt.hour
    df["soc"]       = df["soc"].astype(float)
    df["charged"]   = df["charged"].astype(float)
    df["decharged"] = df["decharged"].astype(float)
    return df.set_index("uur").sort_index()


def available_dates(data_dir: Path | None = None) -> list[date]:
    """Gesorteerde lijst van beschikbare datums in de lokale map."""
    data_dir = data_dir or config.BATTERY_DIR
    dates = []
    for path in sorted(data_dir.glob("*.json")):
        try:
            d = date(int(path.name[:4]), int(path.name[4:6]), int(path.name[6:8]))
            dates.append(d)
        except ValueError:
            continue
    return dates
