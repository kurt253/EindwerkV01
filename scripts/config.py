"""
Configuratie voor het V1Eindwerk energiedashboard.

Secrets worden opgehaald uit de Windows Credential Manager via keyring.
Paden en instellingen komen uit .env in de projectroot.

Parametermapping voor de telegrambestanden: config/telegram_mapping.json
"""

import json
import os
from pathlib import Path

from dotenv import load_dotenv
import keyring

# Projectroot: scripts/config.py -> scripts/ -> projectroot
ROOT = Path(__file__).resolve().parent.parent

load_dotenv(ROOT / ".env")


# ── Parametermapping ──────────────────────────────────────────────────────

TELEGRAM_MAPPING_FILE = ROOT / "config" / "telegram_mapping.json"


def laad_mapping() -> dict:
    """
    Laad de volledige parametermapping uit telegram_mapping.json.

    Returns:
        dict: Geneste mapping met p1.obis_codes, sofar_me3000sp.registers,
              sofar_command_blok en bijbehorende metadata.

    Raises:
        FileNotFoundError: Als telegram_mapping.json niet gevonden wordt.
    """
    with TELEGRAM_MAPPING_FILE.open(encoding="utf-8") as f:
        return json.load(f)


# ── Secrets ───────────────────────────────────────────────────────────────

def _get_secret(name: str) -> str:
    """
    Haal een secret op uit de Windows Credential Manager.

    Args:
        name (str): Naam van het secret binnen de service 'V1Eindwerk'.

    Returns:
        str: De opgeslagen sleutelwaarde.

    Raises:
        RuntimeError: Als het secret niet gevonden wordt.
    """
    value = keyring.get_password("V1Eindwerk", name)
    if not value:
        raise RuntimeError(
            f"Secret '{name}' niet gevonden in Windows Credential Manager.\n"
            f"Sla het op met:\n"
            f"  python -c \"import keyring; keyring.set_password('V1Eindwerk', '{name}', '<waarde>')\""
        )
    return value


def solar_auth_key() -> str:
    """Authenticatiesleutel voor de SolarLogs API."""
    return _get_secret("solar_auth_key")


def battery_auth_key() -> str:
    """Authenticatiesleutel voor de SolarBattery API."""
    return _get_secret("battery_auth_key")


# ── Paden ─────────────────────────────────────────────────────────────────

DATA_DIR      = ROOT / "data"
SOURCE_DIR    = DATA_DIR / "Source Data"

SOLAR_DIR     = Path(os.environ["SOLAR_DIR"])
BATTERY_DIR   = Path(os.environ["BATTERY_DIR"])
OWNDEV_DIR    = SOURCE_DIR / "OwnDev"
SOLARCHARGE_DIR = SOURCE_DIR / "Solarcharge"
WEATHER_CSV   = Path(os.environ["WEATHER_CSV"])

INTERMEDIATE_DIR = DATA_DIR / "intermediate results"


# ── API ───────────────────────────────────────────────────────────────────

SOLAR_ADRESID   = os.environ["SOLAR_ADRESID"]
BATTERY_SN      = os.environ["BATTERY_SN"]
SOLAR_API_URL   = os.environ["SOLAR_API_URL"]
BATTERY_API_URL = os.environ["BATTERY_API_URL"]
WEATHER_API_URL = os.environ["WEATHER_API_URL"]


# ── Locatie ───────────────────────────────────────────────────────────────

LAT           = float(os.environ["LAT"])
LON           = float(os.environ["LON"])
PANEL_TILT    = float(os.environ.get("PANEL_TILT",    35))
PANEL_AZIMUTH = float(os.environ.get("PANEL_AZIMUTH", 292.5))
