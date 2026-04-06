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
    """
    Converteer een unsigned 16-bit Modbus-registerwaarde naar signed int16.

    Args:
        value (int): Unsigned registerwaarde (0–65535).

    Returns:
        int: Signed waarde (-32768–32767).
             Waarden ≥ 0x8000 (32768) worden negatief via two's complement
             (bv. 0xFFFF → -1, 0x8000 → -32768).
    """
    # Modbus-registers zijn 16-bit unsigned; waarden ≥ 0x8000 (32768) zijn negatief in signed int16
    # Aftrekken van 0x10000 converteert naar het juiste negatieve getal (bv. 0xFFFF → -1)
    return value - 0x10000 if value >= 0x8000 else value


def _parse_p1_block(lines: list[str]) -> dict:
    """
    Parseer de regels van één P1-telegramblok naar een dictionary met meetwaarden.

    Args:
        lines (list[str]): Regels van het P1-blok, zoals gesplitst uit het telegrambestand.

    Returns:
        dict: Dictionary met sleutels uit P1_FIELDS (bv. verbruik_kw, levering_kw, gas_m3).
              Ontbrekende velden worden niet opgenomen; ongeldige waarden worden 0.0.
    """
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


def _parse_command_block(lines: list[str], action: str) -> dict:
    """
    Parseer de inhoud van één SOFAR COMMAND blok.

    Args:
        lines  (list[str]): Regels van het commandoblok (zonder de scheidingsregel).
        action (str):       De actienaam uit de scheidingsregel
                            (bv. "laden door zon", "stoppen").

    Returns:
        dict: Dictionary met sleutels:
              - sofar_action      (str):      De actienaam.
              - sofar_command_time(datetime): Tijdstip van het commando (indien aanwezig).
              - sofar_command_w   (float):    Opgedragen vermogen in W (enkel bij laden/ontladen).
    """
    data = {"sofar_action": action.strip()}
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("Measurement time"):
            try:
                # Formaat: "Measurement time : YYYY-MM-DD HH:MM:SS"
                data["sofar_command_time"] = datetime.strptime(
                    stripped.split(": ", 1)[1], "%Y-%m-%d %H:%M:%S"
                )
            except (ValueError, IndexError):
                pass
        elif re.match(r"^\d+$", stripped):
            # Vermogen in W (aanwezig bij laden/ontladen, afwezig bij stoppen)
            data["sofar_command_w"] = float(stripped)
    return data


def _parse_sofar_block(lines: list[str]) -> dict:
    """
    Parseer de regels van één SOFAR ME3000SP Modbus-blok naar een dictionary met meetwaarden.

    Leest het metingsmoment en alle registerwaarden. Berekent batterijvermogen (reg 525)
    en State of Charge (reg 528) uit de ruwe registerwaarden.

    Args:
        lines (list[str]): Regels van het SOFAR-blok, zoals gesplitst uit het telegrambestand.

    Returns:
        dict: Dictionary met sleutels:
              - sofar_timestamp      (datetime): tijdstip van de meting.
              - battery_power_kw     (float):    netto batterijvermogen in kW
                                                 (positief = laden, negatief = ontladen).
              - battery_charge_kw    (float):    laadvermogen in kW (0 bij ontladen).
              - battery_discharge_kw (float):    ontlaadvermogen in kW (0 bij laden).
              - battery_soc_pct      (float):    State of Charge in % (0–100).
              Sleutels worden weggelaten als de bijbehorende registers ontbreken.
    """
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


def _csv_paths(datum: date, data_dir: Path) -> tuple[Path, Path, Path]:
    """
    Retourneer de paden voor de 3 CSV-uitvoerbestanden van een dag.

    Args:
        datum    (date): De dag.
        data_dir (Path): Bovenliggende map van de datumsmappen (YYYY-MM-DD/).

    Returns:
        tuple[Path, Path, Path]: Paden naar respectievelijk de P1-, SOFAR- en commando-CSV.
                                 Bestandsnamen: YYYY-MM-DD_p1.csv, YYYY-MM-DD_sofar.csv,
                                 YYYY-MM-DD_commando.csv — allemaal in de dagmap.
    """
    dag_dir = data_dir / datum.strftime("%Y-%m-%d")
    prefix  = datum.strftime("%Y-%m-%d")
    return (
        dag_dir / f"{prefix}_p1.csv",
        dag_dir / f"{prefix}_sofar.csv",
        dag_dir / f"{prefix}_commando.csv",
    )


def _parse_file_split(path: Path) -> tuple[list[dict], list[dict], list[dict]]:
    """
    Parseer één minuutbestand en splits de resultaten per bron.

    In tegenstelling tot _parse_file worden P1- en SOFAR-meetrijen apart gehouden
    zodat ze in aparte CSV-bestanden kunnen worden opgeslagen.
    Alle rijen delen dezelfde timestamp (afkomstig uit het SOFAR-blok of de bestandsnaam).

    Args:
        path (Path): Pad naar een telegram_YYYY-MM-DD_HH-MM.txt bestand.

    Returns:
        tuple[list[dict], list[dict], list[dict]]:
          - p1_rows:      lijst van dicts met {timestamp, verbruik_kw, levering_kw, …}
          - sofar_rows:   lijst van dicts met {timestamp, battery_power_kw, battery_soc_pct, …}
          - command_rows: lijst van dicts met {timestamp, sofar_action, sofar_command_w}
    """
    text = path.read_text(encoding="utf-8", errors="ignore")

    p1_blocks    = re.split(r"={5,}\s*P1 TELEGRAM\s*={5,}",    text)
    sofar_blocks = re.split(r"={5,}\s*SOFAR ME3000SP\s*={5,}", text)

    p1_parsed    = [_parse_p1_block(b.splitlines())    for b in p1_blocks    if b.strip()]
    sofar_parsed = [_parse_sofar_block(b.splitlines()) for b in sofar_blocks if b.strip()]

    p1_rows    = []
    sofar_rows = []

    for i in range(max(len(p1_parsed), len(sofar_parsed))):
        # Timestamp: afkomstig uit het SOFAR-blok van dezelfde cyclus, anders uit bestandsnaam
        sofar = sofar_parsed[i] if i < len(sofar_parsed) else {}
        ts    = sofar.get("sofar_timestamp")
        if ts is None:
            try:
                ts = datetime.strptime(path.stem, "telegram_%Y-%m-%d_%H-%M")
            except ValueError:
                continue

        if i < len(p1_parsed) and p1_parsed[i]:
            p1_rows.append({"timestamp": ts, **p1_parsed[i]})

        # sofar_timestamp is de gedeelde sleutel — niet opnemen als eigen kolom in de SOFAR-CSV
        sofar_data = {k: v for k, v in sofar.items() if k != "sofar_timestamp"}
        if sofar_data:
            sofar_rows.append({"timestamp": ts, **sofar_data})

    # Commando-blokken: ======== SOFAR COMMAND : <actie> ========
    cmd_pattern = re.compile(
        r"={5,}\s*SOFAR COMMAND\s*:\s*(.+?)\s*={5,}(.*?)(?=={5,}|$)",
        re.DOTALL,
    )
    command_rows = []
    for m in cmd_pattern.finditer(text):
        action = m.group(1).strip()
        body   = [l.strip() for l in m.group(2).splitlines() if l.strip() and l.strip() != "!"]
        cmd    = _parse_command_block(body, action)
        if cmd:
            # Hernoem sofar_command_time → timestamp voor consistentie in de CSV
            if "sofar_command_time" in cmd:
                cmd["timestamp"] = cmd.pop("sofar_command_time")
            command_rows.append(cmd)

    return p1_rows, sofar_rows, command_rows


def save_day_csv(datum: date, data_dir: Path | None = None) -> tuple[Path, Path, Path]:
    """
    Verwerk alle telegrambestanden voor één dag en sla op als 3 aparte CSV-bestanden.

    De CSV-bestanden worden opgeslagen in de dagmap (data_dir/YYYY-MM-DD/):
      - YYYY-MM-DD_p1.csv      : P1-meterdata per meting (~1/seconde)
      - YYYY-MM-DD_sofar.csv   : SOFAR Modbus-data per meting (~1/seconde)
      - YYYY-MM-DD_commando.csv: SOFAR-besturingscommando's (~1/5 seconden)

    Elk bestand bevat een timestamp-kolom als eerste kolom.

    Args:
        datum    (date):      De dag om te verwerken.
        data_dir (Path|None): Bovenliggende map van de datumsmappen (YYYY-MM-DD/).
                              Standaard: config.SOLAR_DIR.parent / "OwnDev".

    Returns:
        tuple[Path, Path, Path]: Paden naar de geschreven P1-, SOFAR- en commando-CSV.

    Raises:
        FileNotFoundError: Als de dagmap niet bestaat.
    """
    data_dir = data_dir or (config.SOLAR_DIR.parent / "OwnDev")
    dag_dir  = data_dir / datum.strftime("%Y-%m-%d")
    if not dag_dir.exists():
        raise FileNotFoundError(f"Geen telegrambestanden gevonden voor {datum} in {dag_dir}")

    all_p1    = []
    all_sofar = []
    all_cmds  = []

    for txt in sorted(dag_dir.rglob("telegram_*.txt")):
        p1, sofar, cmds = _parse_file_split(txt)
        all_p1.extend(p1)
        all_sofar.extend(sofar)
        all_cmds.extend(cmds)

    p1_path, sofar_path, cmd_path = _csv_paths(datum, data_dir)

    # P1-CSV: één rij per P1-telegram (~1/seconde)
    pd.DataFrame(all_p1).sort_values("timestamp").reset_index(drop=True).to_csv(
        p1_path, index=False
    )

    # SOFAR-CSV: één rij per Modbus-uitlezing (~1/seconde)
    pd.DataFrame(all_sofar).sort_values("timestamp").reset_index(drop=True).to_csv(
        sofar_path, index=False
    )

    # Commando-CSV: één rij per besturingscommando (~1/5 seconden)
    if all_cmds:
        pd.DataFrame(all_cmds).sort_values("timestamp").reset_index(drop=True).to_csv(
            cmd_path, index=False
        )
    else:
        # Schrijf leeg bestand met kolomhoofden zodat load_day_minutes weet dat er geen commando's waren
        pd.DataFrame(columns=["timestamp", "sofar_action", "sofar_command_w"]).to_csv(
            cmd_path, index=False
        )

    return p1_path, sofar_path, cmd_path


def _parse_file(path: Path) -> tuple[list[dict], list[dict]]:
    """
    Parseer één minuutbestand.
    Retourneert (meetrijen, commandorijen):
      - meetrijen: één dict per P1+SOFAR cyclus (~1/seconde)
      - commandorijen: één dict per SOFAR COMMAND blok (~1/5 seconden)
    """
    text = path.read_text(encoding="utf-8", errors="ignore")

    # ── Meetrijen: P1 + SOFAR gekoppeld op volgorde ───────────────────────
    # Splits op blokgrenzen: scheiders zijn rijen met ≥5 =-tekens rond de bloknaam
    p1_blocks    = re.split(r"={5,}\s*P1 TELEGRAM\s*={5,}", text)
    sofar_blocks = re.split(r"={5,}\s*SOFAR ME3000SP\s*={5,}", text)

    p1_parsed    = [_parse_p1_block(b.splitlines()) for b in p1_blocks if b.strip()]
    sofar_parsed = [_parse_sofar_block(b.splitlines()) for b in sofar_blocks if b.strip()]

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

    # ── Commandorijen: SOFAR COMMAND blokken (elke 5 cycli) ──────────────
    # Patroon: ======== SOFAR COMMAND : <actie> ========
    # Gevolgd door: Measurement time, optioneel vermogen in W, afsluitende !
    cmd_pattern = re.compile(
        r"={5,}\s*SOFAR COMMAND\s*:\s*(.+?)\s*={5,}(.*?)(?=={5,}|$)",
        re.DOTALL,
    )
    command_rows = []
    for m in cmd_pattern.finditer(text):
        action = m.group(1).strip()
        # Verwijder de afsluit-! en lege regels uit de blokinhoud
        body = [l.strip() for l in m.group(2).splitlines() if l.strip() and l.strip() != "!"]
        cmd = _parse_command_block(body, action)
        if cmd:
            command_rows.append(cmd)

    return rows, command_rows


def load_day_minutes(datum: date, data_dir: Path | None = None) -> pd.DataFrame | None:
    """
    Laad alle minuut-voor-minuut metingen voor één dag uit de OwnDev-telegrambestanden.

    Leest alle telegram_*.txt bestanden onder data_dir/YYYY-MM-DD/,
    koppelt SOFAR-commando's aan meetrijen via merge_asof en berekent nettovermogen.

    Args:
        datum    (date):      De dag om te laden.
        data_dir (Path|None): Bovenliggende map van de datumsmappen (YYYY-MM-DD/).
                              Standaard: config.SOLAR_DIR.parent / "OwnDev".

    Returns:
        pd.DataFrame: Gesorteerd op timestamp, met kolommen:
                      - timestamp           (datetime): tijdstip van de meting (~1/seconde).
                      - verbruik_kw         (float):    huidig verbruik van het net in kW.
                      - levering_kw         (float):    huidige teruglevering aan het net in kW.
                      - battery_power_kw    (float):    netto batterijvermogen in kW.
                      - battery_charge_kw   (float):    laadvermogen in kW.
                      - battery_discharge_kw(float):    ontlaadvermogen in kW.
                      - battery_soc_pct     (float):    State of Charge in %.
                      - gas_m3              (float):    gasafname in m³.
                      - water_m3            (float):    waterverbruik in m³.
                      - piek_maand_kw       (float):    maandpiek in kW.
                      - gemiddeld_15min_kw  (float):    gemiddeld vermogen afgelopen 15 min in kW.
                      - net_power_kw        (float):    nettovermogen (verbruik − levering − batterij).
                      - sofar_action        (str):      meest recente SOFAR-actienaam (indien aanwezig).
                      - sofar_command_w     (float):    opgedragen vermogen in W (indien aanwezig).
        None: Als de dagmap niet bestaat of geen telegrambestanden bevat.
    """
    data_dir = data_dir or (config.SOLAR_DIR.parent / "OwnDev")
    p1_path, sofar_path, cmd_path = _csv_paths(datum, data_dir)

    # ── Voorkeur: inlezen uit CSV (sneller dan ruwe telegrams herverwerken) ──
    if p1_path.exists() and sofar_path.exists():
        df_p1    = pd.read_csv(p1_path,    parse_dates=["timestamp"])
        df_sofar = pd.read_csv(sofar_path, parse_dates=["timestamp"])

        # Koppel P1 en SOFAR op exact overeenkomende timestamp (beide komen uit dezelfde cyclus)
        df = (
            pd.merge(df_p1, df_sofar, on="timestamp", how="outer")
            .sort_values("timestamp")
            .reset_index(drop=True)
        )

        # Voeg SOFAR-commando's toe via merge_asof als het commando-CSV bestaat en niet leeg is
        if cmd_path.exists():
            df_cmd = pd.read_csv(cmd_path, parse_dates=["timestamp"])
            df_cmd = df_cmd.dropna(subset=["timestamp"]).sort_values("timestamp")
            if not df_cmd.empty:
                cmd_cols = ["timestamp", "sofar_action"] + [
                    c for c in ["sofar_command_w"] if c in df_cmd.columns
                ]
                df = pd.merge_asof(
                    df,
                    df_cmd[cmd_cols],
                    on="timestamp",
                    direction="backward",
                )

        # Nettovermogen herberekenen na de merge
        df["net_power_kw"] = (
            df.get("verbruik_kw",        pd.Series(0.0, index=df.index)).fillna(0)
            - df.get("levering_kw",      pd.Series(0.0, index=df.index)).fillna(0)
            - df.get("battery_power_kw", pd.Series(0.0, index=df.index)).fillna(0)
        )
        return df

    # ── Fallback: verwerk ruwe telegrambestanden (CSV nog niet aangemaakt) ───
    dag_dir = data_dir / datum.strftime("%Y-%m-%d")
    if not dag_dir.exists():
        return None

    rows = []
    command_rows = []
    for txt in sorted(dag_dir.rglob("telegram_*.txt")):
        m_rows, c_rows = _parse_file(txt)
        rows.extend(m_rows)
        command_rows.extend(c_rows)

    if not rows:
        return None

    df = pd.DataFrame(rows).sort_values("timestamp").reset_index(drop=True)

    # Nettovermogen: positief = afname van net, negatief = injectie naar net
    # Formule gelijk aan BatMgmtV3: net_power = verbruik - levering - battery_power
    df["net_power_kw"] = (
        df.get("verbruik_kw",        pd.Series(0.0, index=df.index)).fillna(0)
        - df.get("levering_kw",      pd.Series(0.0, index=df.index)).fillna(0)
        - df.get("battery_power_kw", pd.Series(0.0, index=df.index)).fillna(0)
    )

    # Koppel het meest recente SOFAR commando aan elke meting via dichtstbijzijnde timestamp
    # (commando's komen elke 5 cycli, meetrijen elke ~1 seconde)
    if command_rows:
        cmd_df = pd.DataFrame(command_rows)
        if "sofar_command_time" in cmd_df.columns:
            cmd_df = (
                cmd_df.dropna(subset=["sofar_command_time"])
                .rename(columns={"sofar_command_time": "timestamp"})
                .sort_values("timestamp")
                [["timestamp", "sofar_action", "sofar_command_w"]]
            )
            if not cmd_df.empty:
                # merge_asof koppelt elke meting aan het meest recente commando (backward)
                df = pd.merge_asof(
                    df,
                    cmd_df,
                    on="timestamp",
                    direction="backward",
                )

    return df


def load_day_hourly(datum: date, data_dir: Path | None = None) -> pd.DataFrame | None:
    """
    Aggregeer minuutdata naar uurdata, vergelijkbaar met het SolarLogs-formaat.

    Energie per uur wordt geschat als: gemiddeld vermogen (kW) × (aantal metingen / 60).
    Dit is een benadering waarbij het aantal metingen de werkelijk gemeten duur in uren schat.

    Args:
        datum    (date):      De dag om te aggregeren.
        data_dir (Path|None): Bovenliggende map van de datumsmappen (YYYY-MM-DD/).
                              Standaard: config.SOLAR_DIR.parent / "OwnDev".

    Returns:
        pd.DataFrame: Geïndexeerd op uur (0–23), met kolommen:
                      - injectie              (float): kWh geïnjecteerd in het net dat uur.
                      - afname                (float): kWh afgenomen van het net dat uur.
                      - battery_soc_pct       (float): SOC (%) aan het einde van het uur.
                      - battery_charge_kw     (float): gemiddeld laadvermogen in kW.
                      - battery_discharge_kw  (float): gemiddeld ontlaadvermogen in kW.
                      - battery_charge_kwh    (float): geschatte geladen energie in kWh.
                      - battery_discharge_kwh (float): geschatte ontladen energie in kWh.
                      - net_power_kwh         (float): geschat nettovermogen in kWh.
                      - sofar_action          (str):   dominante SOFAR-actie dat uur (indien aanwezig).
                      - sofar_command_kw      (float): gemiddeld opgedragen vermogen in kW (indien aanwezig).
                      Uren zonder metingen krijgen NaN.
        None: Als er geen minuutdata beschikbaar is voor de gevraagde datum.
    """
    df = load_day_minutes(datum, data_dir)
    if df is None or df.empty:
        return None

    df["uur"] = df["timestamp"].dt.hour

    # kWh = gemiddeld kW × (aantal metingen / 60)  — metingen zijn ±1/minuut
    # Formule: energie (kWh) ≈ gemiddeld vermogen (kW) × gemeten duur (uur)
    # "aantal metingen / 60" schat de werkelijk gemeten duur in uren
    agg = df.groupby("uur").agg(
        injectie             =("levering_kw",        lambda x: x.mean() * len(x) / 60),
        afname               =("verbruik_kw",         lambda x: x.mean() * len(x) / 60),
        # SOC aan het einde van elk uur (laatste meting geeft de eindtoestand)
        battery_soc_pct      =("battery_soc_pct",     "last"),
        battery_charge_kw    =("battery_charge_kw",   "mean"),
        battery_discharge_kw =("battery_discharge_kw","mean"),
        # kWh via zelfde formule: gemiddeld vermogen × geschatte gemeten duur in uren
        battery_charge_kwh   =("battery_charge_kw",   lambda x: x.mean() * len(x) / 60),
        battery_discharge_kwh=("battery_discharge_kw",lambda x: x.mean() * len(x) / 60),
        net_power_kwh        =("net_power_kw",        lambda x: x.mean() * len(x) / 60),
    ).reindex(range(24))  # Alle 24 uren garanderen, ook uren zonder metingen (→ NaN)

    # Dominante SOFAR actie per uur: de meest voorkomende actie in dat uur
    if "sofar_action" in df.columns:
        agg["sofar_action"] = (
            df.groupby("uur")["sofar_action"]
            .agg(lambda x: x.dropna().mode().iat[0] if not x.dropna().empty else None)
            .reindex(range(24))
        )

    # Gemiddeld opgedragen vermogen per uur (W → kW)
    if "sofar_command_w" in df.columns:
        agg["sofar_command_kw"] = (
            df.groupby("uur")["sofar_command_w"].mean().reindex(range(24)) / 1000
        )

    return agg


def process_missing_csvs(
    data_dir: Path | None = None,
) -> tuple[list[date], dict[date, str]]:
    """
    Loop door alle datumsmappen en maak ontbrekende CSV-rapporten aan.

    Voor elke dagmap (YYYY-MM-DD) controleert de functie of de drie CSV-bestanden
    (p1, sofar, commando) aanwezig zijn.  Ontbreekt er minstens één, dan worden
    alle drie opnieuw aangemaakt via :func:`save_day_csv`.

    Args:
        data_dir (Path|None): Bovenliggende map van de datumsmappen (YYYY-MM-DD/).
                              Standaard: config.SOLAR_DIR.parent / "OwnDev".

    Returns:
        tuple[list[date], dict[date, str]]:
            - verwerkt: lijst van datums waarvoor nieuwe CSV's zijn aangemaakt.
            - fouten:   dict {datum: foutmelding} voor datums die mislukten.
    """
    data_dir = data_dir or (config.SOLAR_DIR.parent / "OwnDev")
    verwerkt: list[date] = []
    fouten: dict[date, str] = {}

    for dag_dir in sorted(data_dir.iterdir()):
        if not dag_dir.is_dir():
            continue
        try:
            datum = datetime.strptime(dag_dir.name, "%Y-%m-%d").date()
        except ValueError:
            continue

        p1_path, sofar_path, cmd_path = _csv_paths(datum, data_dir)

        # Alleen verwerken als minstens één CSV ontbreekt
        if p1_path.exists() and sofar_path.exists() and cmd_path.exists():
            continue

        try:
            save_day_csv(datum, data_dir)
            verwerkt.append(datum)
        except Exception as exc:
            fouten[datum] = str(exc)

    return verwerkt, fouten


def available_dates(data_dir: Path | None = None) -> list[date]:
    """
    Geef een gesorteerde lijst van alle datums waarvoor een OwnDev-dagmap bestaat.

    Args:
        data_dir (Path|None): Bovenliggende map van de datumsmappen (YYYY-MM-DD/).
                              Standaard: config.SOLAR_DIR.parent / "OwnDev".

    Returns:
        list[date]: Gesorteerde lijst van date-objecten. Leeg als de map niet bestaat.
    """
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
