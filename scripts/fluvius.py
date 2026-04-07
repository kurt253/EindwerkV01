"""
fluvius.py
==========
Verwerk Fluvius kwartiertotalen-exports naar één compacte tijdreeks.

BRONFORMAAT
-----------
De Fluvius-exports zijn semikolon-gescheiden CSV-bestanden met twee rijen per
kwartier (één per register). Kolommen die relevant zijn:

    Van (datum)  ;Van (tijdstip) ;Tot (datum)  ;Tot (tijdstip) ;Register;Volume;Eenheid
    01-11-2024   ;00:00:00       ;01-11-2024   ;00:15:00       ;Afname Nacht;0,229;kWh
    01-11-2024   ;00:00:00       ;01-11-2024   ;00:15:00       ;Injectie Nacht;0,009;kWh

Registers die voorkomen: Afname Dag, Afname Nacht, Injectie Dag, Injectie Nacht.

OUTPUTFORMAAT
-------------
Één rij per kwartier met de kolommen:

    kwartier          datetime  starttijdstip van het 15-minuten slot (YYYY-MM-DD HH:MM)
    afname_dag        float     kWh afgenomen van het net — dagtarief
    afname_nacht      float     kWh afgenomen van het net — nachttarief
    injectie_dag      float     kWh geïnjecteerd naar het net — dagtarief
    injectie_nacht    float     kWh geïnjecteerd naar het net — nachttarief

INCREMENTEEL BIJWERKEN
----------------------
Bij een volgende export hoeft enkel het nieuwste bestand toegevoegd te worden.
Het script leest de hoogste al verwerkte `kwartier`-tijdstempel uit het
outputbestand en schrijft alleen kwartieren die daarna vallen. Zo hoeven
historische bestanden niet opnieuw verwerkt te worden.

GEBRUIK
-------
    from scripts.fluvius import verwerk, laad

    # Verwerk alle bestanden (of alleen nieuwe kwartieren)
    pad, n_nieuw = verwerk()
    print(f"{n_nieuw} nieuwe kwartieren toegevoegd aan {pad}")

    # Inlezen voor analyse
    df = laad()
"""

from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path

import pandas as pd

from scripts.config import SOURCE_DIR

# ── Paden ─────────────────────────────────────────────────────────────────
FLUVIUS_DIR: Path = SOURCE_DIR / "Fluvius"
OUTPUT_FILE: Path = FLUVIUS_DIR / "fluvius_kwartieren.csv"

# Datumformaat in de bronbestanden: "DD-MM-YYYY" en "HH:MM:SS"
_DT_FMT = "%d-%m-%Y %H:%M:%S"

# Kolomnaam in het outputbestand
_KOL_KWARTIER = "kwartier"

# Mapping: register-label → outputkolom
_REGISTER_MAP = {
    "Afname Dag":     "afname_dag",
    "Afname Nacht":   "afname_nacht",
    "Injectie Dag":   "injectie_dag",
    "Injectie Nacht": "injectie_nacht",
}


# ── Interne parsering ─────────────────────────────────────────────────────

def _parse_csv(path: Path) -> list[dict]:
    """
    Lees één Fluvius-exportbestand en geef de rijen terug als lijst van dicts.

    Elke dict heeft de sleutels 'kwartier' (datetime), 'register' (str) en
    'volume' (float). Rijen met een onbekend register of ongeldige waarden
    worden stilzwijgend overgeslagen.

    Args:
        path (Path): Pad naar het Fluvius CSV-bestand.

    Returns:
        list[dict]: Lijst met geparseerde rijen.
    """
    rijen: list[dict] = []
    with path.open(newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh, delimiter=";")
        for raw in reader:
            register = (raw.get("Register") or "").strip()
            if register not in _REGISTER_MAP:
                continue
            try:
                datum_str = raw["Van (datum)"].strip()
                tijd_str  = raw["Van (tijdstip)"].strip()
                kwartier  = datetime.strptime(f"{datum_str} {tijd_str}", _DT_FMT)
                # Fluvius gebruikt komma als decimaalscheider
                volume = float(raw["Volume"].strip().replace(",", "."))
            except (ValueError, KeyError):
                continue
            rijen.append({
                "kwartier": kwartier,
                "register": register,
                "volume":   volume,
            })
    return rijen


def _pivot(rijen: list[dict]) -> pd.DataFrame:
    """
    Pivot de rijen (één per register per kwartier) naar één rij per kwartier.

    Ontbrekende waarden (bv. als een register niet in elke export zit) worden
    met 0 gevuld.

    Args:
        rijen (list[dict]): Uitvoer van _parse_csv().

    Returns:
        pd.DataFrame: Gesorteerd op kwartier, met kolommen:
                      kwartier, afname_dag, afname_nacht, injectie_dag, injectie_nacht.
    """
    if not rijen:
        return pd.DataFrame(columns=[_KOL_KWARTIER] + list(_REGISTER_MAP.values()))

    df = pd.DataFrame(rijen)
    # Vertaal register-labels naar compacte kolomnamen
    df["register"] = df["register"].map(_REGISTER_MAP)

    # Pivot: één rij per kwartier, één kolom per register
    df_pivot = (
        df.pivot_table(
            index="kwartier",
            columns="register",
            values="volume",
            aggfunc="sum",
        )
        .reindex(columns=list(_REGISTER_MAP.values()))
        .fillna(0)
        .reset_index()
    )
    df_pivot.columns.name = None
    return df_pivot.sort_values("kwartier").reset_index(drop=True)


# ── Publieke functies ─────────────────────────────────────────────────────

def verwerk(fluvius_dir: Path | None = None) -> tuple[Path, int]:
    """
    Verwerk alle Fluvius-exportbestanden en schrijf (of verleng) het outputbestand.

    Incrementele logica:
      1. Als het outputbestand al bestaat, lees de hoogste 'kwartier'-waarde.
      2. Parseer alle bronbestanden maar filter rijen die al in het output zitten.
      3. Voeg alleen nieuwe kwartieren toe (append).

    Args:
        fluvius_dir (Path|None): Map met de bronbestanden.
                                 Standaard: FLUVIUS_DIR (uit config.SOURCE_DIR).

    Returns:
        tuple[Path, int]: Pad naar het outputbestand en aantal nieuw toegevoegde rijen.

    Raises:
        FileNotFoundError: Als fluvius_dir niet bestaat.
    """
    fluvius_dir = fluvius_dir or FLUVIUS_DIR
    output     = OUTPUT_FILE if fluvius_dir == FLUVIUS_DIR else fluvius_dir / OUTPUT_FILE.name

    if not fluvius_dir.exists():
        raise FileNotFoundError(f"Fluvius-map niet gevonden: {fluvius_dir}")

    # Bepaal de hoogste al verwerkte tijdstempel
    laatste_kwartier: datetime | None = None
    if output.exists():
        bestaand = pd.read_csv(output, parse_dates=[_KOL_KWARTIER])
        if not bestaand.empty:
            laatste_kwartier = bestaand[_KOL_KWARTIER].max()

    # Parseer alle bronbestanden (het outputbestand zelf overslaan)
    alle_rijen: list[dict] = []
    for csv_path in sorted(fluvius_dir.glob("*.csv")):
        if csv_path.resolve() == output.resolve():
            continue
        rijen = _parse_csv(csv_path)
        # Filter rijen die al verwerkt zijn
        if laatste_kwartier is not None:
            rijen = [r for r in rijen if r["kwartier"] > laatste_kwartier]
        alle_rijen.extend(rijen)

    if not alle_rijen:
        # Geen nieuwe data — geef 0 terug zonder het bestand aan te raken
        return output, 0

    df_nieuw = _pivot(alle_rijen)

    # Schrijf: append als het outputbestand al bestaat, anders nieuw aanmaken
    if output.exists():
        df_nieuw.to_csv(output, mode="a", header=False, index=False,
                        date_format="%Y-%m-%d %H:%M")
    else:
        df_nieuw.to_csv(output, index=False, date_format="%Y-%m-%d %H:%M")

    return output, len(df_nieuw)


def laad(fluvius_dir: Path | None = None) -> pd.DataFrame:
    """
    Lees het verwerkte outputbestand in als DataFrame.

    Args:
        fluvius_dir (Path|None): Map waar het outputbestand staat.
                                 Standaard: FLUVIUS_DIR.

    Returns:
        pd.DataFrame: Gesorteerd op kwartier, met kolommen:
                      kwartier, afname_dag, afname_nacht, injectie_dag, injectie_nacht.
                      Leeg DataFrame als het outputbestand niet bestaat.
    """
    fluvius_dir = fluvius_dir or FLUVIUS_DIR
    output = OUTPUT_FILE if fluvius_dir == FLUVIUS_DIR else fluvius_dir / OUTPUT_FILE.name

    if not output.exists():
        return pd.DataFrame(columns=[_KOL_KWARTIER] + list(_REGISTER_MAP.values()))

    df = pd.read_csv(output, parse_dates=[_KOL_KWARTIER])
    return df.sort_values(_KOL_KWARTIER).reset_index(drop=True)
