"""
Analyse: detecteer commandowisselingen in de OwnDev SOFAR-logs.

Een wisseling treedt op wanneer de actie of het opgedragen vermogen verandert
t.o.v. het vorige commando binnen dezelfde dag.

Uitvoer: data/intermediate results/batterij_responstijd.csv
Kolommen: datum, command_timestamp, prev_action, new_action, command_w
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from scripts import config
from scripts.owndev import _csv_paths, available_dates

OWNDEV_DIR:  Path = config.SOLAR_DIR.parent / "OwnDev"
OUTPUT_DIR:  Path = config.SOLAR_DIR.parent.parent / "intermediate results"
OUTPUT_FILE: Path = OUTPUT_DIR / "batterij_responstijd.csv"

KOLOMMEN = ["datum", "command_timestamp", "prev_action", "new_action", "command_w"]


def _lees_commando(path: Path) -> pd.DataFrame:
    """Lees commando-CSV; vul ontbrekende sofar_command_w-kolom aan met NaN."""
    if not path.exists():
        return pd.DataFrame()
    df = pd.read_csv(path, parse_dates=["timestamp"])
    if df.empty or "sofar_action" not in df.columns:
        return pd.DataFrame()
    if "sofar_command_w" not in df.columns:
        df["sofar_command_w"] = float("nan")
    return df.sort_values("timestamp").reset_index(drop=True)


def detecteer_wisselingen(cmd: pd.DataFrame) -> pd.DataFrame:
    """
    Geef alle rijen waarbij actie of vermogen verandert t.o.v. de vorige rij.
    Eerste rij van de dag wordt altijd overgeslagen.
    """
    if len(cmd) < 2:
        return pd.DataFrame()

    prev = cmd[["sofar_action", "sofar_command_w"]].shift(1)
    cmd = cmd.copy()
    cmd["prev_action"] = prev["sofar_action"]
    cmd["prev_w"]      = prev["sofar_command_w"]

    actie_veranderd    = cmd["sofar_action"] != cmd["prev_action"]
    vermogen_veranderd = cmd["sofar_command_w"].fillna(-1) != cmd["prev_w"].fillna(-1)

    return cmd[cmd["prev_action"].notna() & (actie_veranderd | vermogen_veranderd)].copy()


def _verwerk_dag(datum) -> tuple[list[dict], list[str]]:
    """Verwerk één dag: laad commando's, detecteer wisselingen, bouw rijen."""
    _, _, cmd_path = _csv_paths(datum, OWNDEV_DIR)

    cmd = _lees_commando(cmd_path)
    if cmd.empty:
        return [], []

    wisselingen = detecteer_wisselingen(cmd)
    if wisselingen.empty:
        return [], []

    rijen:  list[dict] = []
    fouten: list[str]  = []

    for _, w in wisselingen.iterrows():
        try:
            rijen.append({
                "datum":             str(datum),
                "command_timestamp": w["timestamp"],
                "prev_action":       w["prev_action"],
                "new_action":        w["sofar_action"],
                "command_w":         int(w["sofar_command_w"]) if pd.notna(w["sofar_command_w"]) else None,
            })
        except Exception as exc:
            fouten.append(f"{w['timestamp']} – {exc}")

    return rijen, fouten


def run(data_dir: Path | None = None) -> tuple[Path, pd.DataFrame, list[str]]:
    """
    Verwerk alle OwnDev-dagmappen en schrijf batterij_responstijd.csv.

    Returns:
        tuple: outputpad, DataFrame met wisselingen, lijst van foutmeldingen.
    """
    owndev_dir  = data_dir or OWNDEV_DIR
    alle_rijen: list[dict] = []
    alle_fouten: list[str] = []

    for datum in available_dates(owndev_dir):
        rijen, fouten = _verwerk_dag(datum)
        alle_rijen.extend(rijen)
        alle_fouten.extend(f"{datum}: {f}" for f in fouten)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    if alle_rijen:
        df = pd.DataFrame(alle_rijen)[KOLOMMEN]
        df["command_timestamp"] = pd.to_datetime(df["command_timestamp"])
        df = df.sort_values("command_timestamp").reset_index(drop=True)
    else:
        df = pd.DataFrame(columns=KOLOMMEN)

    df.to_csv(OUTPUT_FILE, index=False)
    return OUTPUT_FILE, df, alle_fouten


if __name__ == "__main__":
    pad, df, fouten = run()
    print(f"Klaar: {len(df)} wisselingen -> {pad}")
    for f in fouten:
        print(f"  Fout: {f}")
