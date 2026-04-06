"""
Solarcharge: verwerk iLuCharge laadsessie-exports naar een kwartier-tijdreeks.

Verantwoordelijkheden
---------------------
- Alle *.csv-bestanden in de Solarcharge-map scannen (de outputfile uitgezonderd).
- Elke file inlezen: 6-regelige header overslaan, kolommen From/To/User/kWh/totKwh.
- Deduplicatie op (from_dt, to_dt, user, kwh).
- Per sessie de energie uitspreiden over alle kwartieren die de sessie overlapt:
    * Veronderstelling: constant laadvermogen gedurende de sessie.
    * vermogen_kw  = sessie_kwh / sessie_duur_uur       (constant)
    * energie_kwh  = vermogen_kw × overlap_uur           (per kwartier)
    * overlap_min  = overlap tussen kwartierslot en sessie (in minuten)
- Resultaat: één rij per kwartier per sessie, gesorteerd op kwartier.
- Opslaan als OUTPUT_FILE in dezelfde map.
"""

from __future__ import annotations

import csv
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

from scripts.config import SOLAR_DIR

# Solarcharge-map staat naast de Solarlogs-map
SOLARCHARGE_DIR: Path = SOLAR_DIR.parent / "Solarcharge"

# Outputbestand — dit wordt NIET meegenomen in de scan
OUTPUT_FILE: Path = SOLARCHARGE_DIR / "solarcharge_sessies.csv"

# Datumformaat in de bronbestanden: "HH:MM DD-MM-YYYY"
_DT_FMT = "%H:%M %d-%m-%Y"

# Aantal over te slaan header-regels (metadata + lege scheidingsregel)
_HEADER_ROWS = 6


def _parse_file(path: Path) -> list[dict]:
    """
    Lees één iLuCharge-exportbestand en geef de sessies terug als lijst van dicts.

    De eerste 6 regels zijn metadata; regel 7 bevat de kolomnamen
    ``From,To,User,kWh,totKwh``.  Voettekstregels (bv. ``Totaal kWh : …``)
    worden stilzwijgend overgeslagen.

    Args:
        path (Path): Pad naar het te verwerken iLuCharge CSV-bestand.

    Returns:
        list[dict]: Lijst met sessiedicts met sleutels ``from_dt``, ``to_dt``,
            ``user``, ``kwh``, ``tot_kwh``.
    """
    rows: list[dict] = []
    with path.open(newline="", encoding="utf-8-sig") as fh:
        for _ in range(_HEADER_ROWS):
            next(fh)
        reader = csv.DictReader(fh)
        for raw in reader:
            if not raw.get("From"):
                continue
            try:
                rows.append({
                    "from_dt": datetime.strptime(raw["From"].strip(), _DT_FMT),
                    "to_dt":   datetime.strptime(raw["To"].strip(),   _DT_FMT),
                    "user":    (raw.get("User") or "").strip(),
                    "kwh":     float(raw["kWh"].strip()),
                    "tot_kwh": float(raw["totKwh"].strip()),
                })
            except (ValueError, KeyError):
                continue  # voettekstregels overslaan
    return rows


def _sessie_naar_kwartieren(sessie: dict) -> list[dict]:
    """
    Spreid de energie van één sessie uit over alle kwartiersloten die ze overlapt.

    Het laadvermogen wordt als constant beschouwd gedurende de sessie:
    ``vermogen_kw = kwh / duur_uur``.  Per kwartierslot wordt de overlappende
    tijd bepaald, en de bijbehorende energie en dat constante vermogen gerapporteerd.

    Args:
        sessie (dict): Sessiedict met sleutels ``from_dt``, ``to_dt``,
            ``user``, ``kwh``, ``tot_kwh``.

    Returns:
        list[dict]: Lijst van kwartier-rijen met sleutels:
            - ``kwartier``   (datetime): starttijdstip van het 15-minuten slot.
            - ``from_dt``    (datetime): sessiestart.
            - ``to_dt``      (datetime): sessieeinde.
            - ``user``       (str):      gebruiker.
            - ``sessie_kwh`` (float):    totale sessie-energie (kWh).
            - ``overlap_min``(float):    minuten overlap in dit kwartier.
            - ``energie_kwh``(float):    energie toegewezen aan dit kwartier (kWh).
            - ``gem_vermogen_kw`` (float): gemiddeld vermogen over het kwartierslot (kW).
                Voor volle kwartieren gelijk aan het constant sessievermogen;
                voor gedeeltelijke kwartieren (begin/einde sessie) lager.
    """
    from_dt: datetime = sessie["from_dt"]
    to_dt:   datetime = sessie["to_dt"]
    kwh:     float    = sessie["kwh"]

    if to_dt <= from_dt or kwh <= 0:
        return []

    duur_min = (to_dt - from_dt).total_seconds() / 60
    duur_uur = duur_min / 60
    vermogen_kw = kwh / duur_uur  # constant laadvermogen

    # Eerste kwartierstart: afronden naar beneden op 15 min
    q = from_dt.replace(second=0, microsecond=0)
    q = q - timedelta(minutes=q.minute % 15)

    kwartier_rijen: list[dict] = []
    while q < to_dt:
        q_einde = q + timedelta(minutes=15)

        overlap_start = max(q, from_dt)
        overlap_einde = min(q_einde, to_dt)
        overlap_min   = (overlap_einde - overlap_start).total_seconds() / 60

        if overlap_min > 0:
            overlap_uur = overlap_min / 60
            # Energie voor dit kwartier: constant vermogen × overlap
            energie_kwh = vermogen_kw * overlap_uur
            # Gemiddeld vermogen over het volledige kwartierslot (15 min = 0,25 uur)
            # Voor volle kwartieren: gelijk aan vermogen_kw
            # Voor gedeeltelijke kwartieren: lager (bv. 5/15 × vermogen_kw)
            gem_vermogen_kw = energie_kwh / 0.25
            kwartier_rijen.append({
                "kwartier":       q,
                "from_dt":        from_dt,
                "to_dt":          to_dt,
                "user":           sessie["user"],
                "sessie_kwh":     kwh,
                "overlap_min":    round(overlap_min, 2),
                "energie_kwh":    round(energie_kwh, 4),
                "gem_vermogen_kw": round(gem_vermogen_kw, 4),
            })

        q = q_einde

    return kwartier_rijen


def load_all_sessions() -> pd.DataFrame:
    """
    Scan alle iLuCharge-bestanden, dedupliceer sessies en spreid energie per kwartier.

    Het outputbestand wordt overgeslagen als invoer.

    Returns:
        pd.DataFrame: Kwartier-tijdreeks met kolommen:
            ``kwartier``, ``from_dt``, ``to_dt``, ``user``,
            ``sessie_kwh``, ``overlap_min``, ``energie_kwh``, ``vermogen_kw``.
            Gesorteerd op ``kwartier``.

    Raises:
        FileNotFoundError: Als ``SOLARCHARGE_DIR`` niet bestaat.
    """
    if not SOLARCHARGE_DIR.exists():
        raise FileNotFoundError(f"Solarcharge-map niet gevonden: {SOLARCHARGE_DIR}")

    alle_sessies: list[dict] = []
    for csv_path in sorted(SOLARCHARGE_DIR.glob("*.csv")):
        if csv_path.resolve() == OUTPUT_FILE.resolve():
            continue
        alle_sessies.extend(_parse_file(csv_path))

    if not alle_sessies:
        return pd.DataFrame(columns=[
            "kwartier", "from_dt", "to_dt", "user",
            "sessie_kwh", "overlap_min", "energie_kwh", "gem_vermogen_kw",
        ])

    # Dedupliceer op sessieniveau vóór uitspreiden
    sess_df = pd.DataFrame(alle_sessies)
    sess_df = sess_df.drop_duplicates(subset=["from_dt", "to_dt", "user", "kwh"])

    # Spreid elke sessie over kwartieren
    alle_kwartieren: list[dict] = []
    for _, rij in sess_df.iterrows():
        alle_kwartieren.extend(_sessie_naar_kwartieren(rij.to_dict()))

    df = pd.DataFrame(alle_kwartieren)
    df = df.sort_values("kwartier").reset_index(drop=True)
    return df


def save_sessions() -> tuple[Path, int]:
    """
    Verwerk alle iLuCharge-bestanden en sla de kwartier-tijdreeks op als CSV.

    Het outputbestand wordt telkens overschreven.

    Returns:
        tuple[Path, int]: Pad naar het geschreven bestand en het aantal rijen.

    Raises:
        FileNotFoundError: Als ``SOLARCHARGE_DIR`` niet bestaat.
    """
    df = load_all_sessions()

    out = df.copy()
    out["kwartier"] = out["kwartier"].dt.strftime("%Y-%m-%d %H:%M")
    out["from_dt"]  = out["from_dt"].dt.strftime("%Y-%m-%d %H:%M")
    out["to_dt"]    = out["to_dt"].dt.strftime("%Y-%m-%d %H:%M")

    SOLARCHARGE_DIR.mkdir(parents=True, exist_ok=True)
    out.to_csv(OUTPUT_FILE, index=False, float_format="%.4f")

    return OUTPUT_FILE, len(df)


def available_sessions() -> pd.DataFrame | None:
    """
    Laad de opgeslagen kwartier-tijdreeks uit ``OUTPUT_FILE`` als die bestaat.

    Returns:
        pd.DataFrame | None: DataFrame met kwartierdata, of ``None`` als het
            outputbestand nog niet aangemaakt is.
    """
    if not OUTPUT_FILE.exists():
        return None
    df = pd.read_csv(OUTPUT_FILE, parse_dates=["kwartier", "from_dt", "to_dt"])
    return df
