"""
Configuratie en secrets.

Secrets worden opgehaald uit de Windows Credential Manager via keyring.
Alle overige instellingen komen uit .env.

Secrets eenmalig opslaan (run dit één keer in een terminal):
    python -c "
    import keyring
    keyring.set_password('V1Eindwerk', 'solar_auth_key', '<jouw solar key>')
    keyring.set_password('V1Eindwerk', 'battery_auth_key', '<jouw battery key>')
    "
"""

import os
from pathlib import Path
from dotenv import load_dotenv
import keyring

# .env inladen vanuit de projectroot (ook als de app vanuit een submap wordt gestart)
# __file__ is scripts/config.py → parent = scripts/ → parent.parent = projectroot
_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_ROOT / ".env")


def _get_secret(name: str) -> str:
    """
    Haal een secret op uit de Windows Credential Manager via keyring.

    Args:
        name (str): Naam van het secret binnen de service "V1Eindwerk"
                    (bv. "solar_auth_key" of "battery_auth_key").

    Returns:
        str: De opgeslagen sleutelwaarde.

    Raises:
        RuntimeError: Als het secret niet gevonden wordt, met instructie hoe het op te slaan.
    """
    value = keyring.get_password("V1Eindwerk", name)
    if not value:
        raise RuntimeError(
            f"Secret '{name}' niet gevonden in Windows Credential Manager.\n"
            f"Sla het op met:\n"
            f"  python -c \"import keyring; keyring.set_password('V1Eindwerk', '{name}', '<waarde>')\""
        )
    return value


# ── Secrets (uit Windows Credential Manager) ─────────────────────────────
def solar_auth_key() -> str:
    """
    Retourneer de AUTH_key voor de SolarLogs API.

    Returns:
        str: De authenticatiesleutel, opgehaald uit Windows Credential Manager.

    Raises:
        RuntimeError: Als de sleutel niet gevonden wordt.
    """
    return _get_secret("solar_auth_key")


def battery_auth_key() -> str:
    """
    Retourneer de AUTH_key voor de SolarBattery API.

    Returns:
        str: De authenticatiesleutel, opgehaald uit Windows Credential Manager.

    Raises:
        RuntimeError: Als de sleutel niet gevonden wordt.
    """
    return _get_secret("battery_auth_key")


# ── Config (uit .env) ─────────────────────────────────────────────────────
SOLAR_DIR     = Path(os.environ["SOLAR_DIR"])
BATTERY_DIR   = Path(os.environ["BATTERY_DIR"])
WEATHER_CSV   = Path(os.environ["WEATHER_CSV"])

SOLAR_ADRESID = os.environ["SOLAR_ADRESID"]
BATTERY_SN    = os.environ["BATTERY_SN"]

LAT = float(os.environ["LAT"])
LON = float(os.environ["LON"])

PANEL_TILT    = float(os.environ.get("PANEL_TILT",    35))     # graden van horizontaal
PANEL_AZIMUTH = float(os.environ.get("PANEL_AZIMUTH", 292.5))  # kompasbearing: 0=Noord, 270=West, WNW=292.5
# .get() met standaardwaarden zodat paneelinstellingen optioneel zijn in .env

SOLAR_API_URL   = os.environ["SOLAR_API_URL"]
BATTERY_API_URL = os.environ["BATTERY_API_URL"]
WEATHER_API_URL = os.environ["WEATHER_API_URL"]
