"""
Weerdata: ophalen via Open-Meteo API en inlezen van lokale CSV.
Instraling op de panelen (POA) wordt lokaal berekend via pvlib,
op basis van de paneeloriëntatie in config (PANEL_TILT, PANEL_AZIMUTH).
"""

from pathlib import Path

import pandas as pd
import pvlib
import requests

from scripts import config

# Ruwe variabelen die we ophalen — géén global_tilted_irradiance van de API
_HOURLY_VARS = [
    "shortwave_radiation",       # GHI (W/m²)
    "direct_normal_irradiance",  # DNI (W/m²)
    "diffuse_radiation",         # DHI (W/m²)
    "sunshine_duration",         # seconden zonneschijn per uur
]

_LOCATION = pvlib.location.Location(
    latitude=config.LAT,
    longitude=config.LON,
    tz="Europe/Brussels",
    altitude=15,
)


def _bereken_poa(df: pd.DataFrame) -> pd.Series:
    """
    Bereken de instraling op het paneeloppervlak (POA, W/m²) met pvlib.

    Gebruikt het Hay-Davies diffuus-stralingsmodel en de paneeloriëntatie
    uit config (PANEL_TILT, PANEL_AZIMUTH).

    Args:
        df (pd.DataFrame): DataFrame met DatetimIndex (timezone-aware of naive Brussels)
                           en kolommen shortwave_radiation (GHI), direct_normal_irradiance (DNI)
                           en diffuse_radiation (DHI), alle in W/m².

    Returns:
        pd.Series: POA-instraling in W/m² per tijdstip, genaamd "poa_irradiance".
                   Waarden zijn 0 wanneer de zenithoek van de zon > 85° (zon te laag).
    """
    # Bereken azimut en zenithoek van de zon voor elk tijdstip in de index
    solar_pos = _LOCATION.get_solarposition(df.index)

    # Extra-terrestrische instraling (bovenkant atmosfeer) nodig voor Hay-Davies model
    dni_extra = pvlib.irradiance.get_extra_radiation(df.index)

    # Hay-Davies model verdeelt diffuse straling in isotropisch + circumsolaire component;
    # geschikt voor scheve en niet-zuidgerichte panelen zoals WNW
    poa = pvlib.irradiance.get_total_irradiance(
        surface_tilt=config.PANEL_TILT,
        surface_azimuth=config.PANEL_AZIMUTH,          # 0=Noord, 270=West, 292.5=WNW
        dni=df["direct_normal_irradiance"].clip(lower=0),
        ghi=df["shortwave_radiation"].clip(lower=0),
        dhi=df["diffuse_radiation"].clip(lower=0),
        solar_zenith=solar_pos["apparent_zenith"],
        solar_azimuth=solar_pos["azimuth"],
        dni_extra=dni_extra,
        model="haydavies",
    )

    # poa_global = som van directe, diffuse en gereflecteerde component op het paneeloppervlak
    result = poa["poa_global"].clip(lower=0)

    # Zet POA op 0 wanneer de zon te laag staat (zenithoek > 85°):
    # het model wordt onbetrouwbaar dicht bij de horizon.
    result = result.where(solar_pos["apparent_zenith"] < 85, other=0.0)

    return result.rename("poa_irradiance")


def fetch(start_date: str, end_date: str) -> pd.DataFrame:
    """
    Haal uurlijkse weerdata op via de Open-Meteo API en bereken de POA-instraling lokaal.

    Args:
        start_date (str): Startdatum in formaat "YYYY-MM-DD".
        end_date   (str): Einddatum in formaat "YYYY-MM-DD".

    Returns:
        pd.DataFrame: Geïndexeerd op tijdstip (uurlijks, Europe/Brussels), met kolommen:
                      - shortwave_radiation       (float): GHI in W/m².
                      - direct_normal_irradiance  (float): DNI in W/m².
                      - diffuse_radiation         (float): DHI in W/m².
                      - sunshine_duration         (float): zonneschijnduur in seconden per uur.
                      - sunshine_min_per_hour     (float): zonneschijnduur omgezet naar minuten.
                      - poa_irradiance            (float): instraling op paneeloppervlak in W/m².

    Raises:
        requests.HTTPError: Bij een netwerk- of HTTP-fout.
        RuntimeError:       Als de API een foutmelding teruggeeft in de JSON-respons.
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
        # Dictionary-uitpakking: voeg elke gevraagde variabele als kolom toe
        **{var: data["hourly"].get(var) for var in _HOURLY_VARS},
    })
    df["time"] = pd.to_datetime(df["time"])
    df = df.set_index("time")

    # Open-Meteo levert sunshine_duration in seconden per uur → omzetten naar minuten
    df["sunshine_min_per_hour"] = df["sunshine_duration"] / 60
    # POA (Plane of Array) instraling lokaal berekenen via pvlib i.p.v. API-kolom gebruiken
    df["poa_irradiance"] = _bereken_poa(df)

    return df


def fetch_and_save(start_date: str, end_date: str, output_path: Path | None = None) -> Path:
    """
    Haal weerdata op via de API en sla het resultaat op als CSV-bestand.

    Args:
        start_date   (str):       Startdatum in formaat "YYYY-MM-DD".
        end_date     (str):       Einddatum in formaat "YYYY-MM-DD".
        output_path  (Path|None): Pad waar de CSV wordt opgeslagen.
                                  Standaard: config.WEATHER_CSV.

    Returns:
        Path: Pad naar het opgeslagen CSV-bestand.
    """
    output_path = output_path or config.WEATHER_CSV
    df = fetch(start_date, end_date)
    df.to_csv(output_path, float_format="%.2f")
    return output_path


def recalculate_poa(csv_path: Path | None = None) -> Path:
    """
    Herbereken de poa_irradiance kolom in de bestaande CSV zonder opnieuw te fetchen.

    Nuttig wanneer PANEL_TILT of PANEL_AZIMUTH gewijzigd zijn.
    Verwijdert de eventueel aanwezige verouderde kolom global_tilted_irradiance.

    Args:
        csv_path (Path|None): Pad naar de lokale weer-CSV.
                              Standaard: config.WEATHER_CSV.

    Returns:
        Path: Pad naar de bijgewerkte CSV.
    """
    csv_path = csv_path or config.WEATHER_CSV
    df = pd.read_csv(csv_path, index_col="time", parse_dates=True)
    df["poa_irradiance"] = _bereken_poa(df)
    if "global_tilted_irradiance" in df.columns:
        df = df.drop(columns=["global_tilted_irradiance"])
    df.to_csv(csv_path, float_format="%.2f")
    return csv_path


def load(csv_path: Path | None = None) -> pd.DataFrame:
    """
    Lees de lokale weer-CSV in als DataFrame.

    Args:
        csv_path (Path|None): Pad naar de lokale weer-CSV.
                              Standaard: config.WEATHER_CSV.

    Returns:
        pd.DataFrame: Geïndexeerd op tijdstip (uurlijks), met kolommen zoals aangemaakt
                      door fetch() — waaronder poa_irradiance en sunshine_min_per_hour.
    """
    csv_path = csv_path or config.WEATHER_CSV
    df = pd.read_csv(csv_path, index_col="time", parse_dates=True)
    return df
