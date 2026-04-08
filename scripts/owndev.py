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


RESPONS_FILE: Path = INTERMEDIATE_DIR / "commando_respons.csv"

# Gesigneerde outputkolommen per seconde na het commando:
#   net_kw = afname_kw − terugave_kw        (+ afname van net, − injectie naar net)
#   bat_kw = bat_laden_kw − bat_ontladen_kw (+ laden batterij, − ontladen batterij)
_RESPONS_KOLOMMEN = ["net_kw", "bat_kw"]

# Aantal seconden na het commando dat we volgen
_N_SECONDEN = 5


def detecteer_nuttige_commando_s(df: pd.DataFrame) -> pd.DataFrame:
    """
    Detecteer rijen waarop het gevraagde batterijvermogen effectief wijzigt.

    Een 'nuttig commando' is een seconde waarop ``commando_kw`` verschilt van
    de onmiddellijk voorgaande waarde. Dit filtert herhalingen weg (het
    commando wordt elke ~7 seconden herhaald, ook als er niets verandert).

    Seconden met sofar_action == 'Onbekend' worden overgeslagen omdat we dan
    geen betrouwbaar commando kennen.

    Args:
        df (pd.DataFrame): Volledige seconde-tijdreeks, gesorteerd op tijdstip,
                           met kolommen ``sofar_action`` en ``commando_kw``.

    Returns:
        pd.DataFrame: Subset van df met enkel de rijen waarop een echte
                      vermogenswijziging optrad, gesorteerd op tijdstip.
    """
    df = df.sort_values("tijdstip").copy()

    # Verwijder rijen zonder gekend commando
    df_bekend = df[df["sofar_action"] != "Onbekend"].copy()

    # Detecteer wijzigingen: vergelijk commando_kw met de vorige rij
    # fillna zodat NaN → NaN geen false positive geeft
    vorig = df_bekend["commando_kw"].shift(1)
    gewijzigd = df_bekend["commando_kw"].ne(vorig) | (
        df_bekend["commando_kw"].isna() & vorig.notna()
    )

    return df_bekend[gewijzigd].reset_index(drop=True)


def analyseer_commando_respons(
    df: pd.DataFrame | None = None,
) -> tuple[pd.DataFrame, Path]:
    """
    Bouw een DataFrame met voor elk nuttig commando de respons in de volgende
    5 seconden, en sla het op als CSV.

    STRUCTUUR VAN HET OUTPUTBESTAND
    ---------------------------------
    Eén rij per nuttig commando. Kolommen:

        tijdstip        datetime  seconde waarop het commando gegeven werd
        sofar_action    str       naam van het commando
        commando_kw     float     gevraagd vermogen (kW): + laden, − ontladen

        Voor elke seconde n = 1 … 5 na het commando:
            net_kw_sN        float  P1 nettovermogen (kW): + afname van net, − injectie
            bat_kw_sN        float  Batterijvermogen (kW): + laden,          − ontladen
            afwijking_kw_sN  float  bat_kw_sN − commando_kw; cirkelt rond 0

        soc  int  State of Charge (%) op het moment van het commando

    Ontbrekende seconden (gat in de log) krijgen NaN.

    IMPLEMENTATIE
    -------------
    1. Laad de volledige seconde-tijdreeks als gesorteerde integer-index.
    2. Detecteer nuttige commando's via ``detecteer_nuttige_commando_s``.
    3. Zoek voor elk commando de positie in de tijdreeks en pak de volgende
       _N_SECONDEN rijen op via positionele indexering (handelt gaten af).
    4. Breid het commando-record uit tot één brede rij met suffix _s1 … _s5.

    Args:
        df (pd.DataFrame | None): Gesorteerde seconde-tijdreeks. Wordt
                                  ingeladen via ``laad()`` als None.

    Returns:
        tuple[pd.DataFrame, Path]: Het resultaat-DataFrame en het pad naar
                                   de geschreven CSV.
    """
    if df is None:
        df = laad()

    if df.empty:
        leeg = pd.DataFrame()
        leeg.to_csv(RESPONS_FILE, index=False)
        return leeg, RESPONS_FILE

    # Gesorteerde tijdreeks met reset index zodat positie == index
    df_vol = df.sort_values("tijdstip").reset_index(drop=True)

    # Maak een snelle lookup: tijdstip → rij-index
    ts_naar_idx: dict = {ts: i for i, ts in enumerate(df_vol["tijdstip"])}

    nuttige = detecteer_nuttige_commando_s(df_vol)

    rijen: list[dict] = []
    for _, cmd in nuttige.iterrows():
        commando_kw = cmd["commando_kw"]
        rij: dict = {
            "tijdstip":     cmd["tijdstip"],
            "sofar_action": cmd["sofar_action"],
            "commando_kw":  commando_kw,
        }

        # Positie van dit commando in de volledige tijdreeks
        pos = ts_naar_idx.get(cmd["tijdstip"])
        if pos is None:
            # Tijdstip niet teruggevonden (zou niet mogen) → alles NaN
            for n in range(1, _N_SECONDEN + 1):
                rij[f"net_kw_s{n}"]      = None
                rij[f"bat_kw_s{n}"]      = None
                rij[f"afwijking_kw_s{n}"] = None
            rij["soc"] = None
            rijen.append(rij)
            continue

        # Haal de volgende _N_SECONDEN rijen op (kunnen er minder zijn aan einde)
        volgende = df_vol.iloc[pos + 1 : pos + 1 + _N_SECONDEN]

        for n in range(1, _N_SECONDEN + 1):
            if n - 1 < len(volgende):
                seconde = volgende.iloc[n - 1]
                # net_kw: afname positief (verbruik van net), terugave negatief
                afname   = seconde.get("afname_kw")       or 0.0
                terugave = seconde.get("terugave_kw")     or 0.0
                # bat_kw: laden positief, ontladen negatief
                laden    = seconde.get("bat_laden_kw")    or 0.0
                ontladen = seconde.get("bat_ontladen_kw") or 0.0
                bat_kw   = round(laden - ontladen, 3)
                rij[f"net_kw_s{n}"] = round(afname - terugave, 3)
                rij[f"bat_kw_s{n}"] = bat_kw
                # Afwijking = geleverd − gevraagd; cirkelt rond 0 bij goede opvolging
                rij[f"afwijking_kw_s{n}"] = (
                    round(bat_kw - commando_kw, 3)
                    if commando_kw is not None else None
                )
            else:
                # Niet genoeg rijen beschikbaar (einde dataset of groot gat)
                rij[f"net_kw_s{n}"]       = None
                rij[f"bat_kw_s{n}"]       = None
                rij[f"afwijking_kw_s{n}"] = None

        # SOC éénmalig: waarde op het moment van het commando zelf
        rij["soc"] = cmd.get("soc")

        rijen.append(rij)

    df_respons = pd.DataFrame(rijen)

    INTERMEDIATE_DIR.mkdir(parents=True, exist_ok=True)
    df_respons.to_csv(RESPONS_FILE, index=False, date_format="%Y-%m-%d %H:%M:%S")

    return df_respons, RESPONS_FILE


def afwijking_per_commando(df_respons: pd.DataFrame | None = None) -> pd.DataFrame:
    """
    Bereken per commando-type de gemiddelde en maximale afwijking per seconde.

    De afwijking (``afwijking_kw_sN``) is het verschil tussen het geleverde
    batterijvermogen en het gevraagde vermogen:
        afwijking = bat_kw_sN − commando_kw

    Een waarde dicht bij 0 betekent dat de batterij de opdracht goed opvolgde.

    Args:
        df_respons (pd.DataFrame | None): Uitvoer van ``analyseer_commando_respons``.
                                          Wordt ingeladen uit RESPONS_FILE als None.

    Returns:
        pd.DataFrame: Één rij per (sofar_action, seconde) met kolommen:
            - sofar_action  (str):   naam van het commando
            - seconde       (int):   seconde na het commando (1 … _N_SECONDEN)
            - gem_afwijking (float): gemiddelde afwijking over alle commando's (kW)
            - max_afwijking (float): maximale absolute afwijking (kW)
            - n             (int):   aantal commando's waarop het gemiddelde gebaseerd is
    """
    if df_respons is None:
        if not RESPONS_FILE.exists():
            return pd.DataFrame(columns=[
                "sofar_action", "seconde", "gem_afwijking", "max_afwijking", "n"
            ])
        df_respons = pd.read_csv(RESPONS_FILE, parse_dates=["tijdstip"])

    # Bouw een lang formaat: één rij per (commando, seconde)
    rijen: list[dict] = []
    for n in range(1, _N_SECONDEN + 1):
        kol = f"afwijking_kw_s{n}"
        if kol not in df_respons.columns:
            continue
        # Groepeer per commando-type en bereken statistieken
        groep = (
            df_respons[["sofar_action", kol]]
            .dropna(subset=[kol])
            .groupby("sofar_action")[kol]
        )
        stats = groep.agg(
            gem_afwijking="mean",
            max_afwijking=lambda x: x.abs().max(),
            n="count",
        ).reset_index()
        stats["seconde"] = n
        rijen.append(stats)

    if not rijen:
        return pd.DataFrame(columns=[
            "sofar_action", "seconde", "gem_afwijking", "max_afwijking", "n"
        ])

    df = pd.concat(rijen, ignore_index=True)
    df["gem_afwijking"] = df["gem_afwijking"].round(4)
    df["max_afwijking"] = df["max_afwijking"].round(4)
    return df[["sofar_action", "seconde", "gem_afwijking", "max_afwijking", "n"]]


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
