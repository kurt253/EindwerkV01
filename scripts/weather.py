"""
Weerdata: ophalen via Open-Meteo API en inlezen van lokale CSV.
"""

from pathlib import Path

import pandas as pd
import requests

from scripts import config

_HOURLY_VARS = [
    "shortwave_radiation",
    "direct_radiation",
    "diffuse_radiation",
    "sunshine_duration",
    "direct_normal_irradiance",
    "global_tilted_irradiance",
]


def fetch(start_date: str, end_date: str) -> pd.DataFrame:
    """
    Haal uurlijkse weerdata op via Open-Meteo voor de opgegeven periode.
    start_date / end_date: "YYYY-MM-DD"
    """
    params = {
        "latitude":   config.LAT,
        "longitude":  config.LON,
        "start_date": start_date,
        "end_date":   end_date,
        "hourly":     ",".join(_HOURLY_VARS),
        "timezone":   "Europe/Brussels",
    }
    resp = requests.get(config.WEATHER_API_URL, params=params, timeout=30)
    resp.raise_for_status()
    data = resp.json()

    if "error" in data:
        raise RuntimeError(f"Open-Meteo fout: {data.get('reason', 'onbekend')}")

    df = pd.DataFrame({
        "time": data["hourly"]["time"],
        **{var: data["hourly"].get(var) for var in _HOURLY_VARS},
    })
    df["time"] = pd.to_datetime(df["time"])
    df = df.set_index("time")
    if "sunshine_duration" in df.columns:
        df["sunshine_min_per_hour"] = df["sunshine_duration"] / 60
    return df


def fetch_and_save(start_date: str, end_date: str, output_path: Path | None = None) -> Path:
    """Haal weerdata op en sla op als CSV."""
    output_path = output_path or config.WEATHER_CSV
    df = fetch(start_date, end_date)
    df.to_csv(output_path, float_format="%.2f")
    return output_path


def load(csv_path: Path | None = None) -> pd.DataFrame:
    """Lees de lokale weer-CSV in."""
    csv_path = csv_path or config.WEATHER_CSV
    df = pd.read_csv(csv_path, index_col="time", parse_dates=True)
    return df
