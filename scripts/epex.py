"""
epex.py
=======
Ophalen en cachen van EPEX SPOT Belgium dag-vooruit prijzen (€/MWh, uurlijks)
via de ENTSO-E Transparency Platform REST API.

VEREISTEN
---------
Een gratis ENTSO-E API-sleutel opgeslagen in de Windows Credential Manager:

    python -c "import keyring; keyring.set_password('V1Eindwerk', 'entso_api_key', '<sleutel>')"

API-sleutel aanvragen via https://transparency.entsoe.eu/
(gratis na registratie — sleutel direct beschikbaar in het dashboard)

GEBRUIK
-------
    from scripts.epex import load, fetch_and_save

    # Gecachede prijzen inladen (of leeg DataFrame als nog niet opgehaald)
    df = load()

    # Prijzen ophalen/vernieuwen van ENTSO-E API
    df = fetch_and_save(start='2024-11-01', end='2026-04-06')

OUTPUTFORMAAT
-------------
DataFrame geïndexeerd op 'tijdstip' (tz-aware Europe/Brussels, uurlijks):
    price_eur_mwh   float   dag-vooruit prijs in €/MWh
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import requests

from scripts.config import INTERMEDIATE_DIR

CACHE_FILE: Path = INTERMEDIATE_DIR / "epex_be.csv"
_ENTSO_URL = "https://web-api.tp.entsoe.eu/api"
_BE_ZONE = "10YBE----------2"


def _api_key() -> str:
    import keyring

    key = keyring.get_password("V1Eindwerk", "entso_api_key")
    if not key:
        raise RuntimeError(
            "ENTSO-E API-sleutel niet gevonden in Windows Credential Manager.\n"
            "Sla de sleutel op via:\n"
            "  python -c \"import keyring; keyring.set_password("
            "'V1Eindwerk', 'entso_api_key', '<sleutel>')\"\n"
            "Sleutel aanvragen op: https://transparency.entsoe.eu/"
        )
    return key


def _parse_xml(xml_text: str) -> pd.Series:
    """
    Parseer de ENTSO-E XML-respons voor documentType A44 (Day-Ahead Prices).

    Returns:
        pd.Series: index = tz-aware timestamps (UTC), values = €/MWh.
    """
    # Detecteer namespace automatisch uit de root-tag
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise ValueError(f"Ongeldige XML ontvangen: {exc}") from exc

    # Namespace kan variëren — haal op uit root-tag
    ns_uri = ""
    if root.tag.startswith("{"):
        ns_uri = root.tag[1: root.tag.index("}")]
    ns = {"ns": ns_uri} if ns_uri else {}

    def tag(name: str) -> str:
        return f"{{ns}}{name}" if not ns_uri else f"{{{ns_uri}}}{name}"

    records: dict[datetime, float] = {}

    for ts_elem in root.iter(tag("TimeSeries")):
        for period in ts_elem.iter(tag("Period")):
            start_node = period.find(f".//{tag('start')}")
            res_node   = period.find(tag("resolution"))
            if start_node is None or res_node is None:
                continue
            if res_node.text != "PT60M":
                continue  # alleen uurlijkse resolutie

            ts_start = datetime.fromisoformat(
                start_node.text.replace("Z", "+00:00")
            )

            for pt in period.iter(tag("Point")):
                pos_node   = pt.find(tag("position"))
                price_node = pt.find(tag("price.amount"))
                if pos_node is None or price_node is None:
                    continue
                try:
                    pos   = int(pos_node.text)
                    price = float(price_node.text)
                except (ValueError, TypeError):
                    continue
                ts = ts_start + timedelta(hours=pos - 1)
                records[ts] = price

    if not records:
        return pd.Series(dtype=float, name="price_eur_mwh")

    series = pd.Series(records, name="price_eur_mwh")
    series.index = pd.to_datetime(series.index, utc=True)
    series.index.name = "tijdstip"
    return series.sort_index()


def _fetch_chunk(api_key: str, start: datetime, end: datetime) -> pd.Series:
    """Haal maximaal 1 jaar EPEX-prijzen op via ENTSO-E API."""
    params = {
        "securityToken": api_key,
        "documentType":  "A44",
        "in_Domain":     _BE_ZONE,
        "out_Domain":    _BE_ZONE,
        "periodStart":   start.strftime("%Y%m%d%H%M"),
        "periodEnd":     end.strftime("%Y%m%d%H%M"),
    }
    resp = requests.get(_ENTSO_URL, params=params, timeout=60)
    resp.raise_for_status()
    return _parse_xml(resp.text)


def fetch_and_save(
    start: str,
    end: str,
    cache_file: Path | None = None,
) -> pd.DataFrame:
    """
    Haal EPEX BE dag-vooruit prijzen op via de ENTSO-E API en sla ze op.

    Bestaande gecachede data wordt bewaard; enkel ontbrekende periodes
    worden opgehaald (incrementeel bijwerken).

    Args:
        start (str): Startdatum "YYYY-MM-DD".
        end   (str): Einddatum "YYYY-MM-DD" (inclusief).
        cache_file (Path|None): Uitvoerpad; standaard CACHE_FILE.

    Returns:
        pd.DataFrame: Geïndexeerd op 'tijdstip' (tz-aware Europe/Brussels)
                      met kolom 'price_eur_mwh'.
    """
    cache_file = cache_file or CACHE_FILE
    INTERMEDIATE_DIR.mkdir(parents=True, exist_ok=True)
    api_key = _api_key()

    dt_start = datetime.fromisoformat(start).replace(tzinfo=timezone.utc)
    dt_end   = (datetime.fromisoformat(end)
                + timedelta(days=1)).replace(tzinfo=timezone.utc)

    # Laad bestaande cache
    if cache_file.exists():
        df_cache = pd.read_csv(cache_file, index_col="tijdstip", parse_dates=True)
        df_cache.index = pd.to_datetime(df_cache.index, utc=True)
    else:
        df_cache = pd.DataFrame(
            columns=["price_eur_mwh"],
            index=pd.DatetimeIndex([], tz="UTC", name="tijdstip"),
        )

    # Haal ontbrekende stukken op (max 1 jaar per request)
    nieuwe_stukken: list[pd.Series] = []
    chunk_start = dt_start
    while chunk_start < dt_end:
        chunk_end = min(
            chunk_start + timedelta(days=365),
            dt_end,
        )
        # Tel gecachede uren in dit venster
        mask = (df_cache.index >= pd.Timestamp(chunk_start)) & (
            df_cache.index < pd.Timestamp(chunk_end)
        )
        verwacht = int((chunk_end - chunk_start).total_seconds() / 3600)
        if mask.sum() < verwacht * 0.95:
            print(
                f"  ENTSO-E: ophalen "
                f"{chunk_start.date()} \u2192 {chunk_end.date()} ..."
            )
            stuk = _fetch_chunk(api_key, chunk_start, chunk_end)
            if not stuk.empty:
                nieuwe_stukken.append(stuk)
        chunk_start = chunk_end

    if not nieuwe_stukken:
        df_result = df_cache
    else:
        df_nieuw = pd.concat(nieuwe_stukken).to_frame()
        df_result = pd.concat(
            [df_cache[~df_cache.index.isin(df_nieuw.index)], df_nieuw]
        ).sort_index()
        df_result.to_csv(cache_file)

    # Zet om naar Europe/Brussels voor gebruik in notebook
    if not df_result.empty and df_result.index.tz is not None:
        df_result.index = df_result.index.tz_convert("Europe/Brussels")

    return df_result


def load(cache_file: Path | None = None) -> pd.DataFrame:
    """
    Lees de gecachede EPEX-prijzen in.

    Returns:
        pd.DataFrame: Geïndexeerd op 'tijdstip' (tz-aware Europe/Brussels)
                      met kolom 'price_eur_mwh'. Leeg als cache ontbreekt.
    """
    cache_file = cache_file or CACHE_FILE
    if not cache_file.exists():
        return pd.DataFrame(
            columns=["price_eur_mwh"],
            index=pd.DatetimeIndex([], tz="Europe/Brussels", name="tijdstip"),
        )
    df = pd.read_csv(cache_file, index_col="tijdstip", parse_dates=True)
    if not df.empty:
        df.index = pd.to_datetime(df.index, utc=True).tz_convert("Europe/Brussels")
    return df
