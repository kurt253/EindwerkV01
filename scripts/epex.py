"""
epex.py
=======
Importeert EPEX SPOT Belgium dag-vooruit-prijzen (€/MWh, uurlijks) vanuit
het lokale Excel-bronbestand en cachet ze als CSV tussenresultaat.

BRONBESTAND
-----------
    data/Source Data/epex.xlsx

    Kolommen:
        Date   object   datum als "DD/MM/YYYY"
        Time   object   uur als "Xu"  (bv. "0u" = 00:00, "23u" = 23:00)
                        in Belgische lokale tijd (Europe/Brussels)
        Euro   float    dag-vooruit-prijs in €/MWh

GEBRUIK
-------
    from scripts.epex import load, importeer_xlsx

    # Importeer xlsx → epex_be.csv (enkel als nodig)
    df = importeer_xlsx()

    # Gecachede prijzen inladen
    df = load()

OUTPUTFORMAAT
-------------
DataFrame geïndexeerd op 'tijdstip' (tz-aware Europe/Brussels, uurlijks):
    price_eur_mwh   float   dag-vooruit prijs in €/MWh
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from scripts.config import INTERMEDIATE_DIR, SOURCE_DIR

CACHE_FILE:   Path = INTERMEDIATE_DIR / "epex_be.csv"
XLSX_SOURCE:  Path = SOURCE_DIR / "epex.xlsx"


# ─────────────────────────────────────────────────────────────────────────────
#  Excel-import
# ─────────────────────────────────────────────────────────────────────────────

def importeer_xlsx(
    xlsx_file: Path | None = None,
    cache_file: Path | None = None,
    force: bool = False,
) -> pd.DataFrame:
    """
    Leest de EPEX-prijzen uit het lokale Excel-bronbestand en slaat ze op
    als ``epex_be.csv`` in de intermediate results-map.

    Slimme bijwerkdetectie
    ----------------------
    De import wordt alleen uitgevoerd als:
      - ``epex_be.csv`` nog niet bestaat, OF
      - ``epex.xlsx`` recenter gewijzigd is dan ``epex_be.csv``, OF
      - ``force=True``.

    Parameters
    ----------
    xlsx_file : Path | None
        Pad naar het Excel-bronbestand. Standaard ``data/Source Data/epex.xlsx``.
    cache_file : Path | None
        Uitvoerpad voor de CSV-cache. Standaard ``data/intermediate results/epex_be.csv``.
    force : bool
        Als True: altijd opnieuw importeren, ook als de cache actueel is.

    Returns
    -------
    pd.DataFrame
        Index: 'tijdstip' (tz-aware Europe/Brussels, uurlijks, oplopend).
        Kolom: 'price_eur_mwh' (€/MWh).

    Raises
    ------
    FileNotFoundError
        Als epex.xlsx niet gevonden wordt.
    ValueError
        Als het Excel-bestand geen herkende kolommen bevat.
    """
    xlsx_file  = xlsx_file  or XLSX_SOURCE
    cache_file = cache_file or CACHE_FILE
    INTERMEDIATE_DIR.mkdir(parents=True, exist_ok=True)

    if not xlsx_file.exists():
        raise FileNotFoundError(
            f"EPEX-bronbestand niet gevonden: {xlsx_file}\n"
            "Zorg dat 'epex.xlsx' aanwezig is in 'data/Source Data/'."
        )

    # Bijwerkdetectie op basis van bestandstijdstempels
    if not force and cache_file.exists():
        if cache_file.stat().st_mtime >= xlsx_file.stat().st_mtime:
            print(
                f"EPEX-cache is actueel ({cache_file.name}). "
                "Gebruik force=True om toch opnieuw te importeren."
            )
            return load(cache_file)

    # ── Inlezen ──────────────────────────────────────────────────────────────
    df_raw = pd.read_excel(xlsx_file)

    # Normaliseer kolomnamen (hoofdletterongevoelig)
    df_raw.columns = [c.strip().lower() for c in df_raw.columns]
    rename_map = {}
    for col in df_raw.columns:
        if col in ("date", "datum"):
            rename_map[col] = "date"
        elif col in ("time", "tijd", "hour", "uur"):
            rename_map[col] = "time"
        elif col in ("euro", "price", "prijs", "price_eur_mwh"):
            rename_map[col] = "euro"
    df_raw = df_raw.rename(columns=rename_map)

    vereist = {"date", "time", "euro"}
    ontbrekend = vereist - set(df_raw.columns)
    if ontbrekend:
        raise ValueError(
            f"Verwachte kolommen ontbreken in {xlsx_file.name}: {ontbrekend}\n"
            f"Aanwezige kolommen: {list(df_raw.columns)}"
        )

    # ── Tijdstempel opbouwen ─────────────────────────────────────────────────
    # Time-formaat: "Xu" waarbij X het uur is in Belgische lokale tijd.
    # Bv. "0u" = 00:00, "23u" = 23:00.
    uur_str = df_raw["time"].astype(str).str.strip().str.replace("u", "", regex=False)
    datum_str = df_raw["date"].astype(str).str.strip()

    # Combineer naar datetime-string "DD/MM/YYYY HH:00" en parseer
    dt_str = datum_str + " " + uur_str.str.zfill(2) + ":00"
    tijdstip_naive = pd.to_datetime(dt_str, format="%d/%m/%Y %H:%M", errors="coerce")

    # Controleer op niet-parseerbare waarden
    n_null = tijdstip_naive.isna().sum()
    if n_null > 0:
        print(f"  Waarschuwing: {n_null} tijdstempels konden niet worden geparseerd en worden overgeslagen.")

    df = pd.DataFrame({
        "tijdstip": tijdstip_naive,
        "price_eur_mwh": pd.to_numeric(df_raw["euro"], errors="coerce"),
    }).dropna()

    # Sorteren voor correcte DST-afhandeling (tz_localize vereist monotoon stijgende reeks)
    df = df.sort_values("tijdstip").reset_index(drop=True)

    # Lokaliseer naar Europe/Brussels
    # ambiguous='infer': bij winteruur-overgang (25 uur) wordt de volgorde gebruikt
    #                    om te onderscheiden welk uur voor/na de terugzetting is.
    # nonexistent='shift_forward': bij zomeruurovergang (23 uur) bestaat 02:00
    #                               niet; verschuif naar 03:00.
    df["tijdstip"] = df["tijdstip"].dt.tz_localize(
        "Europe/Brussels",
        ambiguous="infer",
        nonexistent="shift_forward",
    )
    df = df.set_index("tijdstip").sort_index()
    df.index.name = "tijdstip"

    # Verwijder duplicaten (mogen niet voorkomen, maar als veiligheidsmaatregel)
    df = df[~df.index.duplicated(keep="last")]

    # ── Opslaan ──────────────────────────────────────────────────────────────
    df_opslaan = df.copy()
    df_opslaan.index = df_opslaan.index.tz_convert("UTC")
    df_opslaan.index.name = "tijdstip"
    df_opslaan.to_csv(cache_file)

    print(
        f"EPEX-cache aangemaakt: {cache_file.name}\n"
        f"  {len(df)} uren over "
        f"{df.index.normalize().nunique()} dagen\n"
        f"  Bereik  : {df.index.min().date()} \u2192 {df.index.max().date()}\n"
        f"  Gem.    : {df['price_eur_mwh'].mean():.2f} \u20ac/MWh\n"
        f"  Min.    : {df['price_eur_mwh'].min():.2f} \u20ac/MWh\n"
        f"  Max.    : {df['price_eur_mwh'].max():.2f} \u20ac/MWh"
    )
    return df


# ─────────────────────────────────────────────────────────────────────────────
#  Inlaadfunctie
# ─────────────────────────────────────────────────────────────────────────────

def load(cache_file: Path | None = None) -> pd.DataFrame:
    """
    Lees de gecachede EPEX-uurprijzen in vanuit ``epex_be.csv``.

    Returns
    -------
    pd.DataFrame
        Index: 'tijdstip' (tz-aware Europe/Brussels, uurlijks).
        Kolom: 'price_eur_mwh' (€/MWh).
        Leeg DataFrame als het cachebestand niet bestaat.
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
