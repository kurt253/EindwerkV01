"""
voorbereiding.py
================
Voert alle datavoobereidingsstappen uit in de juiste volgorde en bouwt
daarna ``data/Final/overall.csv``.

GEBRUIK
-------
    # Als module (vanuit notebook of ander script):
    from scripts.voorbereiding import voorbereiding
    voorbereiding()

    # Als zelfstandig script:
    python scripts/voorbereiding.py

STAPPEN
-------
    0a  SolarLogs        — download via iLumen API (incrementeel)
    0b  Batterijdata     — download via iLumen API (incrementeel)
    0c  Weerdata         — ophalen via Open-Meteo + POA herberekenen
    0d  Fluvius          — lokale CSV-exports verwerken (incrementeel)
    0e  EV-laadsessies   — iLuCharge CSV-exports verwerken
    0f  OwnDev           — telegrammen verwerken naar seconde-CSV
    0g  EPEX             — xlsx importeren + kwartierconversie
    1   Overall          — alle bronnen samenvoegen naar overall.csv

PARAMETERS
----------
    van : date | str | None
        Eerste dag voor API-downloads (YYYY-MM-DD of datetime.date).
        Standaard: dag na de laatste beschikbare dag per bron.
    tot : date | str | None
        Laatste dag voor API-downloads.
        Standaard: gisteren.
    overschrijf_bat : bool
        Als True: batterijbestanden die al aanwezig zijn, worden opnieuw
        gedownload. Standaard False.
    force_epex : bool
        Als True: EPEX-xlsx altijd opnieuw importeren, ook als de cache
        actueel is. Standaard False.
    stappen : set[str] | None
        Subset van stappen om uit te voeren, bv. {'0a', '0g', '1'}.
        Standaard None = alle stappen.

RETURNWAARDE
------------
    dict met per stap een korte statusregel.
"""

from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

# Zorg dat de projectroot op het pad staat als dit script direct wordt uitgevoerd
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from scripts import battery, fluvius, owndev, solarcharge, solar_logs, weather
from scripts import epex, epex_kwartier, overall
from scripts.config import INTERMEDIATE_DIR
from scripts.epex import XLSX_SOURCE
from scripts.owndev import OVERALL_FILE


def voorbereiding(
    van: date | str | None = None,
    tot: date | str | None = None,
    overschrijf_bat: bool = False,
    force_epex: bool = False,
    stappen: set[str] | None = None,
) -> dict[str, str]:
    """
    Voer alle datavoobereidingsstappen uit en bouw overall.csv.

    Parameters
    ----------
    van : date | str | None
        Eerste dag voor API-downloads. Standaard: dag na laatste beschikbare dag.
    tot : date | str | None
        Laatste dag voor API-downloads. Standaard: gisteren.
    overschrijf_bat : bool
        Batterijbestanden opnieuw downloaden als ze al bestaan.
    force_epex : bool
        EPEX-cache opnieuw opbouwen ook als die actueel is.
    stappen : set[str] | None
        Subset van uit te voeren stappen {'0a','0b','0c','0d','0e','0f','0g','1'}.
        None = alle stappen.

    Returns
    -------
    dict[str, str]
        Per stap een statusregel.
    """
    alle_stappen = {'0a', '0b', '0c', '0d', '0e', '0f', '0g', '1'}
    actief = stappen if stappen is not None else alle_stappen

    gisteren = date.today() - timedelta(days=1)
    if isinstance(tot, str):
        tot = date.fromisoformat(tot)
    tot = tot or gisteren

    resultaat: dict[str, str] = {}

    # ── 0a  SolarLogs ────────────────────────────────────────────────────────
    if '0a' in actief:
        print("0a  SolarLogs downloaden …")
        beschikbaar = solar_logs.available_dates()
        van_solar = (
            date.fromisoformat(van) if isinstance(van, str) else van
        ) or (
            beschikbaar[-1] + timedelta(days=1) if beschikbaar else date(2024, 11, 1)
        )
        if van_solar > tot:
            resultaat['0a'] = "al up-to-date"
            print("    → al up-to-date")
        else:
            opgeslagen = solar_logs.download_range(van_solar, tot)
            resultaat['0a'] = f"{len(opgeslagen)} dag(en) opgeslagen ({van_solar} → {tot})"
            print(f"    → {resultaat['0a']}")

    # ── 0b  Batterijdata ─────────────────────────────────────────────────────
    if '0b' in actief:
        print("0b  Batterijdata downloaden …")
        beschikbaar_bat = battery.available_dates()
        van_bat = (
            date.fromisoformat(van) if isinstance(van, str) else van
        ) or (
            beschikbaar_bat[-1] + timedelta(days=1) if beschikbaar_bat else date(2024, 11, 1)
        )
        if van_bat > tot and not overschrijf_bat:
            resultaat['0b'] = "al up-to-date"
            print("    → al up-to-date")
        else:
            opgeslagen, fouten = battery.download_range(
                van_bat, tot, overschrijven=overschrijf_bat
            )
            status = f"{len(opgeslagen)} dag(en) opgeslagen ({van_bat} → {tot})"
            if fouten:
                status += f", {len(fouten)} mislukt"
                for dag, fout in fouten.items():
                    print(f"      ⚠ {dag}: {fout}")
            resultaat['0b'] = status
            print(f"    → {status}")

    # ── 0c  Weerdata ─────────────────────────────────────────────────────────
    if '0c' in actief:
        print("0c  Weerdata ophalen + POA herberekenen …")
        van_weer = (
            van if isinstance(van, str) else (van or date(2024, 11, 1)).strftime("%Y-%m-%d")
        )
        tot_weer = tot.strftime("%Y-%m-%d")
        pad_weer = weather.fetch_and_save(van_weer, tot_weer)
        weather.recalculate_poa()
        resultaat['0c'] = f"opgeslagen: {pad_weer.name}"
        print(f"    → {resultaat['0c']}")

    # ── 0d  Fluvius ──────────────────────────────────────────────────────────
    if '0d' in actief:
        print("0d  Fluvius CSV-exports verwerken …")
        pad_fl, n_fl = fluvius.verwerk()
        resultaat['0d'] = (
            f"{n_fl:,} nieuwe kwartieren → {pad_fl.name}" if n_fl
            else "al up-to-date"
        )
        print(f"    → {resultaat['0d']}")

    # ── 0e  EV-laadsessies ───────────────────────────────────────────────────
    if '0e' in actief:
        print("0e  EV-laadsessies verwerken …")
        pad_ev, n_ev = solarcharge.save_sessions()
        resultaat['0e'] = f"{n_ev:,} kwartierrijen → {pad_ev.name}"
        print(f"    → {resultaat['0e']}")

    # ── 0f  OwnDev ───────────────────────────────────────────────────────────
    if '0f' in actief:
        print("0f  OwnDev telegrammen verwerken …")
        pad_od, n_od = owndev.verwerk()
        resultaat['0f'] = (
            f"{n_od:,} nieuwe meetpunten → {pad_od.name}" if n_od
            else "al up-to-date"
        )
        print(f"    → {resultaat['0f']}")

    # ── 0g  EPEX ─────────────────────────────────────────────────────────────
    if '0g' in actief:
        print("0g  EPEX importeren + kwartierconversie …")
        if not XLSX_SOURCE.exists():
            resultaat['0g'] = f"OVERGESLAGEN — {XLSX_SOURCE.name} niet gevonden"
            print(f"    ⚠ {resultaat['0g']}")
        else:
            epex.importeer_xlsx(force=force_epex)
            epex_kwartier.converteer()
            df_kw = epex_kwartier.laad()
            resultaat['0g'] = (
                f"{len(df_kw)} kwartieren "
                f"({df_kw.index.min().date()} → {df_kw.index.max().date()})"
            )
            print(f"    → {resultaat['0g']}")

    # ── 1   Overall samenvoegen ───────────────────────────────────────────────
    if '1' in actief:
        print("1   overall.csv bouwen …")
        df_overall, pad_overall = overall.bouw()
        resultaat['1'] = (
            f"{len(df_overall):,} kwartieren → {pad_overall}"
        )
        print(f"    → {resultaat['1']}")

    print("\nKlaar.")
    return resultaat


# ── Zelfstandige uitvoering ──────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Voer alle datavoobereidingsstappen uit en bouw overall.csv."
    )
    parser.add_argument("--van",  default=None, help="Startdatum YYYY-MM-DD")
    parser.add_argument("--tot",  default=None, help="Einddatum YYYY-MM-DD (standaard: gisteren)")
    parser.add_argument("--overschrijf-bat", action="store_true",
                        help="Batterijbestanden opnieuw downloaden")
    parser.add_argument("--force-epex", action="store_true",
                        help="EPEX-cache opnieuw opbouwen")
    parser.add_argument("--stappen", nargs="*", default=None,
                        metavar="STAP",
                        help="Subset van stappen (bv. 0a 0g 1). Standaard: alle.")
    args = parser.parse_args()

    voorbereiding(
        van=args.van,
        tot=args.tot,
        overschrijf_bat=args.overschrijf_bat,
        force_epex=args.force_epex,
        stappen=set(args.stappen) if args.stappen else None,
    )
