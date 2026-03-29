"""
OwnDev parser: leest de minuut-voor-minuut P1 + SOFAR telegram bestanden.
Bestandsstructuur: OwnDev/YYYY-MM-DD/HH/telegram_YYYY-MM-DD_HH-MM.txt
"""

import re
from datetime import date, datetime
from pathlib import Path

import pandas as pd

from scripts import config

# ── Mappings (uit BatMgmtV3.py) ──────────────────────────────────────────
P1_FIELDS = {
    "0-0:1.0.0":  "tijd_p1",
    "1-0:1.7.0":  "verbruik_kw",
    "1-0:2.7.0":  "levering_kw",
    "1-0:1.6.0":  "piek_maand_kw",
    "1-0:1.4.0":  "gemiddeld_15min_kw",
    "0-1:24.2.3": "gas_m3",
    "0-2:24.2.1": "water_m3",
}

# Reg 512 + offset
SOFAR_OFFSET_BATTERY_POWER = 13   # reg 525 — signed int16, ×0.01 kW
SOFAR_OFFSET_SOC           = 16   # reg 528 — %
SOFAR_START                = 512


def _int16(value: int) -> int:
    # Modbus-registers zijn 16-bit unsigned; waarden ≥ 0x8000 (32768) zijn negatief in signed int16
    # Aftrekken van 0x10000 converteert naar het juiste negatieve getal (bv. 0xFFFF → -1)
    return value - 0x10000 if value >= 0x8000 else value


def _parse_p1_block(lines: list[str]) -> dict:
    data = {}
    for line in lines:
        for obis, col in P1_FIELDS.items():
            if line.startswith(obis):
                # P1-formaat: OBIS-code(waarde*eenheid)  bv. 1-0:1.7.0(00.123*kW)
                parts = line.split("(")
                # Laatste haakjespaar bevat de waarde; "*eenheid" verwijderen
                value_part = parts[-1].split(")")[0].split("*")[0]
                # Verwijder alle niet-numerieke tekens behalve punt en min-teken
                cleaned = re.sub(r"[^0-9.-]", "", value_part)
                try:
                    data[col] = float(cleaned) if cleaned else 0.0
                except ValueError:
                    data[col] = 0.0
    return data


def _parse_sofar_block(lines: list[str]) -> dict:
    data = {}
    timestamp = None
    regs = {}

    for line in lines:
        if line.startswith("Metingsmoment:"):
            try:
                timestamp = datetime.strptime(line.split(": ", 1)[1].strip(), "%Y-%m-%d %H:%M:%S")
            except ValueError:
                pass
        elif line.startswith("Reg "):
            parts = line.split(":")
            if len(parts) == 2:
                try:
                    reg = int(parts[0].split()[1])
                    val = int(parts[1].strip())
                    regs[reg] = val
                except ValueError:
                    pass

    # Bereken de absolute registernummers op basis van startadres en offset
    battery_power_reg = SOFAR_START + SOFAR_OFFSET_BATTERY_POWER
    soc_reg           = SOFAR_START + SOFAR_OFFSET_SOC

    if battery_power_reg in regs:
        # Signed int16 omzetten en schalen: register-eenheid is 10 W → ×0.01 geeft kW
        bp = _int16(regs[battery_power_reg]) * 0.01
        data["battery_power_kw"]      = bp
        # Positieve waarde = laden, negatieve waarde = ontladen; opsplitsen in twee kolommen
        data["battery_charge_kw"]     = max(bp, 0)
        data["battery_discharge_kw"]  = abs(min(bp, 0))

    if soc_reg in regs:
        data["battery_soc_pct"] = float(regs[soc_reg])

    if timestamp:
        data["sofar_timestamp"] = timestamp

    return data


def _parse_file(path: Path) -> list[dict]:
    """Parseer één minuutbestand. Eén bestand kan meerdere P1+SOFAR blokken bevatten."""
    text = path.read_text(encoding="utf-8", errors="ignore")

    # Splits op blokgrenzen: scheiders zijn rijen met ≥5 =-tekens rond de bloknaam
    p1_blocks    = re.split(r"={5,}\s*P1 TELEGRAM\s*={5,}", text)
    sofar_blocks = re.split(r"={5,}\s*SOFAR ME3000SP\s*={5,}", text)

    p1_parsed    = [_parse_p1_block(b.splitlines()) for b in p1_blocks if b.strip()]
    sofar_parsed = [_parse_sofar_block(b.splitlines()) for b in sofar_blocks if b.strip()]

    # Koppel P1 en SOFAR op volgorde: index i verbindt het i-de P1-blok met het i-de SOFAR-blok
    rows = []
    for i in range(max(len(p1_parsed), len(sofar_parsed))):
        row = {}
        if i < len(p1_parsed):
            row.update(p1_parsed[i])
        if i < len(sofar_parsed):
            row.update(sofar_parsed[i])

        # Gebruik SOFAR timestamp als hoofdtijd, anders bouw uit bestandsnaam
        if "sofar_timestamp" in row:
            row["timestamp"] = row.pop("sofar_timestamp")
        else:
            # Bestandsnaam bevat datum en tijd: telegram_YYYY-MM-DD_HH-MM.txt
            stem = path.stem  # telegram_2026-01-22_10-00
            try:
                row["timestamp"] = datetime.strptime(stem, "telegram_%Y-%m-%d_%H-%M")
            except ValueError:
                continue

        if row:
            rows.append(row)

    return rows


def load_day_minutes(datum: date, data_dir: Path | None = None) -> pd.DataFrame | None:
    """
    Laad alle minuut-metingen voor één dag.
    Retourneert DataFrame met kolommen: timestamp, verbruik_kw, levering_kw,
    battery_power_kw, battery_charge_kw, battery_discharge_kw, battery_soc_pct,
    gas_m3, water_m3, piek_maand_kw, gemiddeld_15min_kw.
    """
    data_dir = data_dir or (config.SOLAR_DIR.parent / "OwnDev")
    dag_dir  = data_dir / datum.strftime("%Y-%m-%d")
    if not dag_dir.exists():
        return None

    rows = []
    for txt in sorted(dag_dir.rglob("telegram_*.txt")):
        rows.extend(_parse_file(txt))

    if not rows:
        return None

    df = pd.DataFrame(rows)
    df = df.sort_values("timestamp").reset_index(drop=True)
    return df


def load_day_hourly(datum: date, data_dir: Path | None = None) -> pd.DataFrame | None:
    """
    Aggregeer minuutdata naar uurdata (vergelijkbaar met SolarLogs formaat).
    Retourneert DataFrame geïndexeerd op uur (0–23) met:
      injectie (kWh), afname (kWh), battery_soc_pct (einde uur),
      battery_charge_kw (gem.), battery_discharge_kw (gem.)
    """
    df = load_day_minutes(datum, data_dir)
    if df is None or df.empty:
        return None

    df["uur"] = df["timestamp"].dt.hour

    # kWh = gemiddeld kW × (aantal metingen / 60)  — metingen zijn ±1/minuut
    # Formule: energie (kWh) ≈ gemiddeld vermogen (kW) × gemeten duur (uur)
    # "aantal metingen / 60" schat de werkelijk gemeten duur in uren
    agg = df.groupby("uur").agg(
        injectie        =("levering_kw",       lambda x: x.mean() * len(x) / 60),
        afname          =("verbruik_kw",        lambda x: x.mean() * len(x) / 60),
        # SOC aan het einde van elk uur (laatste meting geeft de eindtoestand)
        battery_soc_pct =("battery_soc_pct",    "last"),
        battery_charge_kw    =("battery_charge_kw",    "mean"),
        battery_discharge_kw =("battery_discharge_kw", "mean"),
    ).reindex(range(24))  # Alle 24 uren garanderen, ook uren zonder metingen (→ NaN)

    return agg


def available_dates(data_dir: Path | None = None) -> list[date]:
    """Gesorteerde lijst van beschikbare datums in de OwnDev map."""
    data_dir = data_dir or (config.SOLAR_DIR.parent / "OwnDev")
    if not data_dir.exists():
        return []
    dates = []
    for d in sorted(data_dir.iterdir()):
        if d.is_dir():
            try:
                dates.append(datetime.strptime(d.name, "%Y-%m-%d").date())
            except ValueError:
                continue
    return dates
