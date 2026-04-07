"""
owndev.py
=========
Verwerk OwnDev P1+SOFAR telegrambestanden naar een seconde-tijdreeks,
aangevuld met de actieve SOFAR-commando's per seconde.

STRUCTUUR VAN DE BRONBESTANDEN
-------------------------------
Map: data/Source Data/OwnDev/YYYY-MM-DD/HH/telegram_YYYY-MM-DD_HH-MM.txt

Elk bestand bevat meerdere meetparen per seconde:

    ===== P1 TELEGRAM =====
    1-0:1.7.0(XX.XXX*kW)      ← huidig verbruik van het net (afname)
    1-0:2.7.0(XX.XXX*kW)      ← huidige terugave naar het net
    !END P1

    ===== SOFAR ME3000SP =====
    Metingsmoment: YYYY-MM-DD HH:MM:SS
    Reg 525: NNNNN             ← batterijvermogen (signed int16, ×0.01 kW)
    Reg 528: NN                ← State of Charge (%)
    !END SOFAR

Commando's staan in aparte CSV per datum:
    data/Source Data/OwnDev/YYYY-MM-DD/YYYY-MM-DD_commando.csv
    Kolommen: sofar_action, timestamp, sofar_command_w (W, NaN voor stoppen)

OUTPUTFORMAAT (CSV in INTERMEDIATE_DIR)
----------------------------------------
    tijdstip        datetime  seconde-precisie van de SOFAR-meting
    afname_kw       float     huidig verbruik van het net (kW)
    terugave_kw     float     huidige terugave naar het net (kW)
    bat_laden_kw    float     batterijvermogen laden (kW, ≥ 0)
    bat_ontladen_kw float     batterijvermogen ontladen (kW, ≥ 0)
    soc             int       State of Charge (%)
    sofar_action    str       actief SOFAR-commando op deze seconde
    commando_kw     float     gevraagd vermogen (kW): + laden, − ontladen, 0 stoppen

COMMANDO-TOEWIJZINGSLOGICA
---------------------------
1. Elk commando wordt gekoppeld aan de log-seconde op of net vóór het commando-
   tijdstip (merge_asof achterwaarts).
2. Is het commando-tijdstip meer dan 10 seconden na de gekoppelde log-seconde
   (bv. door een logging-pauze), dan krijgt het commando de waarde 'Onbekend'.
3. Op elke log-seconde die volgt na een gat van > 10 seconden in de logs wordt
   de commando-status gereset naar 'Onbekend', totdat een nieuw commando volgt.
4. De commando-status wordt voorwaarts ingevuld (forward-fill) over alle seconden.

INCREMENTEEL BIJWERKEN
-----------------------
- Nieuwe telegram-bestanden: enkel seconden na de laatste tijdstempel worden
  toegevoegd.
- Na het toevoegen van nieuwe seconden worden de commando-kolommen voor de
  VOLLEDIGE dataset opnieuw berekend (goedkoop: alleen pandas-operaties).
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

import pandas as pd

from scripts.config import INTERMEDIATE_DIR, OWNDEV_DIR

# ── Paden ─────────────────────────────────────────────────────────────────
OUTPUT_FILE: Path = INTERMEDIATE_DIR / "owndev_seconden.csv"

# Reguliere expressies voor parsing
_RE_AFNAME   = re.compile(r'1-0:1\.7\.0\((\d+\.\d+)\*kW\)')
_RE_TERUGAVE = re.compile(r'1-0:2\.7\.0\((\d+\.\d+)\*kW\)')
_RE_MOMENT   = re.compile(r'Metingsmoment:\s*(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})')
_RE_REG525   = re.compile(r'Reg 525:\s*(-?\d+)')
_RE_REG528   = re.compile(r'Reg 528:\s*(\d+)')
_RE_BESTAND  = re.compile(r'telegram_(\d{4}-\d{2}-\d{2})_(\d{2})-(\d{2})\.txt')

# Acties met positief vermogen (laden) of negatief (ontladen)
_LADEN_ACTIES   = {"laden tot voorziene level", "laden door zon"}
_ONTLADEN_ACTIES = {"ontladen tot voorziene level", "overschot ontladen tot voorziene level"}

# Maximale gap (seconden) waarna de commando-status 'Onbekend' wordt
_MAX_GAP_S: int = 10


# ═══════════════════════════════════════════════════════════════════════════
# TELEGRAM PARSING
# ═══════════════════════════════════════════════════════════════════════════

def _signed16(waarde: int) -> int:
    """Zet unsigned 16-bit integer om naar signed (-32768 … 32767)."""
    return waarde - 65536 if waarde > 32767 else waarde


def _parse_blok(p1_tekst: str, sofar_tekst: str) -> dict | None:
    """
    Extraheer één meetpaar (P1 + SOFAR) uit de twee tekstblokken.

    Returns:
        dict met tijdstip, afname_kw, terugave_kw, bat_laden_kw,
        bat_ontladen_kw, soc — of None als parsing mislukt.
    """
    m_moment = _RE_MOMENT.search(sofar_tekst)
    if not m_moment:
        return None

    tijdstip    = datetime.strptime(m_moment.group(1), "%Y-%m-%d %H:%M:%S")
    m_afname    = _RE_AFNAME.search(p1_tekst)
    m_terugave  = _RE_TERUGAVE.search(p1_tekst)
    m_reg525    = _RE_REG525.search(sofar_tekst)
    m_reg528    = _RE_REG528.search(sofar_tekst)

    afname_kw   = float(m_afname.group(1))   if m_afname   else None
    terugave_kw = float(m_terugave.group(1)) if m_terugave else None

    bat_laden_kw = bat_ontladen_kw = None
    if m_reg525:
        bat_kw          = _signed16(int(m_reg525.group(1))) * 0.01
        bat_laden_kw    = round(max(0.0,  bat_kw), 3)
        bat_ontladen_kw = round(max(0.0, -bat_kw), 3)

    soc = int(m_reg528.group(1)) if m_reg528 else None

    return {
        "tijdstip":        tijdstip,
        "afname_kw":       afname_kw,
        "terugave_kw":     terugave_kw,
        "bat_laden_kw":    bat_laden_kw,
        "bat_ontladen_kw": bat_ontladen_kw,
        "soc":             soc,
    }


def _parse_bestand(pad: Path, na: datetime | None = None) -> list[dict]:
    """
    Lees één telegrambestand en geef alle meetparen terug.

    Meetparen met tijdstip ≤ `na` worden overgeslagen.
    """
    tekst = pad.read_text(encoding="utf-8", errors="ignore")
    delen = re.split(r'={5} P1 TELEGRAM ={5}', tekst)

    rijen: list[dict] = []
    for deel in delen[1:]:
        p1_einde = deel.find("!END P1")
        if p1_einde == -1:
            continue
        p1_tekst = deel[:p1_einde]

        sofar_start = deel.find("===== SOFAR ME3000SP =====", p1_einde)
        sofar_einde = deel.find("!END SOFAR", sofar_start)
        if sofar_start == -1 or sofar_einde == -1:
            continue
        sofar_tekst = deel[sofar_start:sofar_einde]

        resultaat = _parse_blok(p1_tekst, sofar_tekst)
        if resultaat is None:
            continue
        if na is not None and resultaat["tijdstip"] <= na:
            continue
        rijen.append(resultaat)

    return rijen


def _bestand_tijdstip(pad: Path) -> datetime | None:
    """Leid de minuuttijdstip af uit de bestandsnaam voor snelle filtering."""
    m = _RE_BESTAND.match(pad.name)
    if not m:
        return None
    try:
        return datetime.strptime(f"{m.group(1)} {m.group(2)}:{m.group(3)}", "%Y-%m-%d %H:%M")
    except ValueError:
        return None


# ═══════════════════════════════════════════════════════════════════════════
# COMMANDO PARSING
# ═══════════════════════════════════════════════════════════════════════════

def _commando_kw(actie: str, vermogen_w: float | None) -> float | None:
    """
    Bereken het gevraagde vermogen in kW met teken.

    Laden = positief, ontladen = negatief, stoppen = 0.0, onbekend = None.

    Args:
        actie       (str):        sofar_action label.
        vermogen_w  (float|None): sofar_command_w in Watt (NaN voor stoppen).

    Returns:
        float | None: vermogen in kW met teken.
    """
    if actie == "stoppen":
        return 0.0
    if actie in _LADEN_ACTIES:
        return round(vermogen_w / 1000, 3) if vermogen_w is not None else None
    if actie in _ONTLADEN_ACTIES:
        return round(-abs(vermogen_w) / 1000, 3) if vermogen_w is not None else None
    return None  # Onbekend of toekomstige nieuwe actie


def _laad_commando_csvs(owndev_dir: Path) -> pd.DataFrame:
    """
    Laad alle YYYY-MM-DD_commando.csv bestanden en combineer ze.

    Returns:
        pd.DataFrame met kolommen: timestamp (datetime), sofar_action (str),
        commando_kw (float). Gesorteerd op timestamp.
    """
    frames = []
    for csv_pad in sorted(owndev_dir.glob("*/*_commando.csv")):
        try:
            df = pd.read_csv(csv_pad, parse_dates=["timestamp"])
            frames.append(df)
        except Exception:
            continue

    if not frames:
        return pd.DataFrame(columns=["timestamp", "sofar_action", "commando_kw"])

    df = pd.concat(frames, ignore_index=True)
    df = df.dropna(subset=["timestamp"]).sort_values("timestamp").reset_index(drop=True)

    # Bereken commando_kw met teken
    df["commando_kw"] = df.apply(
        lambda r: _commando_kw(r["sofar_action"], r.get("sofar_command_w")),
        axis=1,
    )
    return df[["timestamp", "sofar_action", "commando_kw"]]


# ═══════════════════════════════════════════════════════════════════════════
# COMMANDO-KOLOMMEN TOEWIJZEN
# ═══════════════════════════════════════════════════════════════════════════

def _voeg_commando_toe(df_sec: pd.DataFrame, df_cmd: pd.DataFrame) -> pd.DataFrame:
    """
    Voeg sofar_action en commando_kw toe aan de seconde-tijdreeks.

    Logica (zie module-docstring):
      1. Koppel elk commando aan de log-seconde op of net vóór het commando.
      2. Gap tussen commando en log-seconde > 10s → actie wordt 'Onbekend'.
      3. Log-seconden na een logging-gat van > 10s worden gereset naar 'Onbekend'.
      4. Forward-fill over alle seconden.

    Args:
        df_sec (pd.DataFrame): Gesorteerde seconde-tijdreeks (kolom 'tijdstip').
        df_cmd (pd.DataFrame): Commando's (kolommen 'timestamp', 'sofar_action',
                               'commando_kw').

    Returns:
        pd.DataFrame: df_sec aangevuld met 'sofar_action' en 'commando_kw'.
    """
    df = df_sec.sort_values("tijdstip").copy()

    if df_cmd.empty:
        df["sofar_action"] = None
        df["commando_kw"]  = None
        return df

    # ── Stap 1: koppel elk commando aan de dichtstbijzijnde log-seconde ────
    matched = pd.merge_asof(
        df_cmd.sort_values("timestamp"),
        df[["tijdstip"]].rename(columns={"tijdstip": "log_ts"}),
        left_on="timestamp",
        right_on="log_ts",
        direction="backward",
    )

    # Commando's waarbij de gap > 10s of geen log-seconde gevonden → Onbekend
    gap_s = (matched["timestamp"] - matched["log_ts"]).dt.total_seconds()
    onbekend_mask = matched["log_ts"].isna() | (gap_s > _MAX_GAP_S)
    matched.loc[onbekend_mask, "sofar_action"] = "Onbekend"
    matched.loc[onbekend_mask, "commando_kw"]  = None

    # Eén event per log_ts: bij meerdere commando's op dezelfde log-seconde
    # wint het laatste commando (meest recent in de tijd)
    cmd_events = (
        matched.dropna(subset=["log_ts"])
        .sort_values("timestamp")
        .drop_duplicates(subset=["log_ts"], keep="last")
        [["log_ts", "sofar_action", "commando_kw"]]
        .rename(columns={"log_ts": "tijdstip"})
    )

    # ── Stap 2: gaten in de log → reset-events ────────────────────────────
    df["_gap"] = df["tijdstip"].diff().dt.total_seconds().fillna(0)
    gap_resets = df[df["_gap"] > _MAX_GAP_S][["tijdstip"]].copy()
    gap_resets["sofar_action"] = "Onbekend"
    gap_resets["commando_kw"]  = None

    # ── Stap 3: combineer events ───────────────────────────────────────────
    # Gap-resets komen eerst; commando's daarna → commando overschrijft reset
    # op hetzelfde tijdstip (als de Pi net na een gat opnieuw opstart en
    # meteen een commando rapporteert).
    events = (
        pd.concat([gap_resets, cmd_events])
        .sort_values(["tijdstip", "sofar_action"])  # commando voor Onbekend → keep='last'
        .drop_duplicates(subset=["tijdstip"], keep="last")
    )

    # ── Stap 4: merge op df en forward-fill ───────────────────────────────
    df = df.merge(events, on="tijdstip", how="left")
    df["sofar_action"] = df["sofar_action"].ffill()
    df["commando_kw"]  = df["commando_kw"].ffill()
    df = df.drop(columns=["_gap"])

    return df


# ═══════════════════════════════════════════════════════════════════════════
# PUBLIEKE FUNCTIES
# ═══════════════════════════════════════════════════════════════════════════

def verwerk(owndev_dir: Path | None = None) -> tuple[Path, int]:
    """
    Verwerk alle OwnDev-telegrambestanden en schrijf (of verleng) het outputbestand.

    Na het toevoegen van nieuwe seconden worden de commando-kolommen voor de
    volledige dataset opnieuw berekend vanuit de commando-CSV's.

    Args:
        owndev_dir (Path|None): Map met de datumsub-mappen.
                                Standaard: OWNDEV_DIR (uit config).

    Returns:
        tuple[Path, int]: Pad naar het outputbestand en aantal nieuwe seconden.

    Raises:
        FileNotFoundError: Als owndev_dir niet bestaat.
    """
    owndev_dir = owndev_dir or OWNDEV_DIR
    if not owndev_dir.exists():
        raise FileNotFoundError(f"OwnDev-map niet gevonden: {owndev_dir}")

    INTERMEDIATE_DIR.mkdir(parents=True, exist_ok=True)

    # ── Stap 1: nieuwe seconden inlezen ───────────────────────────────────
    laatste: datetime | None = None
    df_bestaand = pd.DataFrame()

    if OUTPUT_FILE.exists():
        df_bestaand = pd.read_csv(OUTPUT_FILE, parse_dates=["tijdstip"])
        if not df_bestaand.empty:
            laatste = df_bestaand["tijdstip"].max().to_pydatetime()

    alle_bestanden = sorted(owndev_dir.rglob("telegram_*.txt"))
    alle_rijen: list[dict] = []
    for pad in alle_bestanden:
        bestand_ts = _bestand_tijdstip(pad)
        if laatste is not None and bestand_ts is not None:
            if bestand_ts.timestamp() + 60 <= laatste.timestamp():
                continue
        alle_rijen.extend(_parse_bestand(pad, na=laatste))

    n_nieuw = 0
    if alle_rijen:
        df_nieuw = (
            pd.DataFrame(alle_rijen)
            .sort_values("tijdstip")
            .drop_duplicates(subset=["tijdstip"])
            .reset_index(drop=True)
        )
        n_nieuw = len(df_nieuw)

        # Combineer met bestaande seconden (zonder commando-kolommen)
        sec_kolommen = ["tijdstip", "afname_kw", "terugave_kw",
                        "bat_laden_kw", "bat_ontladen_kw", "soc"]
        if not df_bestaand.empty:
            df_sec = pd.concat(
                [df_bestaand[[c for c in sec_kolommen if c in df_bestaand.columns]],
                 df_nieuw[sec_kolommen]],
                ignore_index=True,
            ).drop_duplicates(subset=["tijdstip"]).sort_values("tijdstip")
        else:
            df_sec = df_nieuw[sec_kolommen]
    else:
        if df_bestaand.empty:
            return OUTPUT_FILE, 0
        # Geen nieuwe seconden maar we heralculeren de commando-kolommen
        sec_kolommen = ["tijdstip", "afname_kw", "terugave_kw",
                        "bat_laden_kw", "bat_ontladen_kw", "soc"]
        df_sec = df_bestaand[[c for c in sec_kolommen if c in df_bestaand.columns]]

    # ── Stap 2: commando-kolommen toewijzen (volledige dataset) ───────────
    df_cmd = _laad_commando_csvs(owndev_dir)
    df_volledig = _voeg_commando_toe(df_sec, df_cmd)

    # ── Stap 3: wegschrijven ───────────────────────────────────────────────
    df_volledig.to_csv(OUTPUT_FILE, index=False, date_format="%Y-%m-%d %H:%M:%S")

    return OUTPUT_FILE, n_nieuw


def laad() -> pd.DataFrame:
    """
    Lees het verwerkte outputbestand in als DataFrame.

    Returns:
        pd.DataFrame gesorteerd op tijdstip, met kolommen:
            tijdstip, afname_kw, terugave_kw, bat_laden_kw, bat_ontladen_kw,
            soc, sofar_action, commando_kw.
        Leeg DataFrame als het bestand niet bestaat.
    """
    if not OUTPUT_FILE.exists():
        return pd.DataFrame(columns=[
            "tijdstip", "afname_kw", "terugave_kw",
            "bat_laden_kw", "bat_ontladen_kw", "soc",
            "sofar_action", "commando_kw",
        ])
    df = pd.read_csv(OUTPUT_FILE, parse_dates=["tijdstip"])
    return df.sort_values("tijdstip").reset_index(drop=True)
