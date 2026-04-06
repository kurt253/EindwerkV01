"""
Data Ophalen: download solar, batterij en weerdata via de API's.
"""

from datetime import date, timedelta

import streamlit as st

from scripts import battery, owndev, solar_logs, solarcharge, weather

st.set_page_config(page_title="Data Ophalen", page_icon="⬇️", layout="wide")
st.title("⬇️ Data Ophalen")

# ── Solar logs ────────────────────────────────────────────────────────────
st.header("☀️ Solar meter data")

solar_dates = solar_logs.available_dates()
col1, col2 = st.columns(2)
with col1:
    solar_start = st.date_input(
        "Van",
        # Standaard de dag na de laatste lokale datum, zodat er geen overlap is
        value=solar_dates[-1] + timedelta(days=1) if solar_dates else date.today(),
        key="solar_start",
    )
with col2:
    solar_end = st.date_input("Tot", value=date.today(), key="solar_end")

if st.button("⬇️ Download solar data"):
    if solar_start > solar_end:
        st.error("Startdatum moet voor einddatum liggen.")
    else:
        dagen = (solar_end - solar_start).days + 1
        with st.spinner(f"{dagen} dag(en) ophalen en opslaan…"):
            try:
                # download_range haalt elke dag op via de API en schrijft direct naar
                # SOLAR_DIR/YYYYMMDD - solar.json — de grafieken lezen altijd uit die bestanden
                saved = solar_logs.download_range(solar_start, solar_end)
                st.success(f"✅ {len(saved)} dag(en) opgeslagen in {saved[0].parent}")
            except Exception as e:
                st.error(f"Fout: {e}")

# ── Batterij ──────────────────────────────────────────────────────────────
st.divider()
st.header("🔋 Batterij data")

bat_dates = battery.available_dates()
col3, col4 = st.columns(2)
with col3:
    bat_start = st.date_input(
        "Van",
        value=bat_dates[-1] + timedelta(days=1) if bat_dates else date.today(),
        key="bat_start",
    )
with col4:
    bat_end = st.date_input("Tot", value=date.today(), key="bat_end")

if st.button("⬇️ Download batterij data"):
    if bat_start > bat_end:
        st.error("Startdatum moet voor einddatum liggen.")
    else:
        dagen = (bat_end - bat_start).days + 1
        with st.spinner(f"{dagen} dag(en) ophalen en opslaan…"):
            try:
                # download_range haalt elke dag op via de API en schrijft direct naar
                # BATTERY_DIR/YYYYMMDD - solar.json — de grafieken lezen altijd uit die bestanden
                saved = battery.download_range(bat_start, bat_end)
                st.success(f"✅ {len(saved)} dag(en) opgeslagen in {saved[0].parent}")
            except Exception as e:
                st.error(f"Fout: {e}")

# ── Weerdata ──────────────────────────────────────────────────────────────
st.divider()
st.header("🌤️ Weerdata (Open-Meteo)")

from scripts.config import PANEL_TILT, PANEL_AZIMUTH

# Kompasrichting berekenen voor weergave
# Sleutels zijn kompasbearings (0=Noord, 90=Oost, 180=Zuid, 270=West) — zelfde conventie als .env
_compass = {
    0: "Noord", 22.5: "NNO", 45: "NO", 67.5: "ONO",
    90: "Oost", 112.5: "OZO", 135: "ZO", 157.5: "ZZO",
    180: "Zuid", 202.5: "ZZW", 225: "ZW", 247.5: "WZW",
    270: "West", 292.5: "WNW", 315: "NW", 337.5: "NNW", 360: "Noord",
}
# Zoek de dichtstbijzijnde kompaspunt op basis van absolute hoekafstand
kompas = min(_compass, key=lambda k: abs(k - PANEL_AZIMUTH))
st.info(
    f"Paneeloriëntatie: **{_compass[kompas]}** ({PANEL_AZIMUTH}° t.o.v. Zuid) · "
    f"Helling: **{PANEL_TILT}°** · "
    f"Aanpasbaar via `.env`"
)

col5, col6 = st.columns(2)
with col5:
    weer_start = st.date_input("Van", value=date(2024, 11, 1), key="weer_start")
with col6:
    weer_end = st.date_input("Tot", value=date.today() - timedelta(days=1), key="weer_end")

if st.button("⬇️ Download weerdata"):
    if weer_start > weer_end:
        st.error("Startdatum moet voor einddatum liggen.")
    else:
        with st.spinner("Weerdata ophalen…"):
            try:
                path = weather.fetch_and_save(
                    weer_start.strftime("%Y-%m-%d"),
                    weer_end.strftime("%Y-%m-%d"),
                )
                st.success(f"✅ Opgeslagen als {path}")
            except Exception as e:
                st.error(f"Fout: {e}")

# ── OwnDev telegrammen verwerken ──────────────────────────────────────────
st.divider()
st.header("📡 OwnDev telegrammen → CSV")

st.info(
    "Verwerk de ruwe P1 + SOFAR telegrambestanden naar CSV. "
    "Per dag worden 3 bestanden aangemaakt in de dagmap:\n"
    "- **YYYY-MM-DD_p1.csv** — P1-meterdata (verbruik, levering, gas, water, …)\n"
    "- **YYYY-MM-DD_sofar.csv** — SOFAR Modbus-data (batterijvermogen, SOC)\n"
    "- **YYYY-MM-DD_commando.csv** — Besturingscommando's (laden/ontladen/stoppen)\n\n"
    "De grafieken lezen daarna uit de CSV's — niet meer uit de ruwe telegrambestanden."
)

owndev_dates = owndev.available_dates()
if not owndev_dates:
    st.warning("Geen OwnDev-dagmappen gevonden.")
else:
    col_a, col_b = st.columns(2)
    owndev_start = col_a.date_input(
        "Van",
        value=owndev_dates[0],
        min_value=owndev_dates[0],
        max_value=owndev_dates[-1],
        key="owndev_start",
    )
    owndev_end = col_b.date_input(
        "Tot",
        value=owndev_dates[-1],
        min_value=owndev_dates[0],
        max_value=owndev_dates[-1],
        key="owndev_end",
    )

    # Toon per dag of de CSV al bestaat
    from scripts.config import SOLAR_DIR
    from scripts.owndev import _csv_paths
    overzicht = []
    for d in owndev_dates:
        if owndev_start <= d <= owndev_end:
            p1, sofar, cmd = _csv_paths(d, SOLAR_DIR.parent / "OwnDev")
            overzicht.append({
                "Datum":       d.strftime("%d/%m/%Y"),
                "P1 CSV":      "✅" if p1.exists()    else "❌",
                "SOFAR CSV":   "✅" if sofar.exists() else "❌",
                "Commando CSV":"✅" if cmd.exists()   else "❌",
            })
    if overzicht:
        import pandas as pd
        st.dataframe(pd.DataFrame(overzicht), hide_index=True, use_container_width=True)

    btn_col1, btn_col2 = st.columns(2)

    if btn_col1.button("⚙️ Verwerk telegrammen naar CSV"):
        if owndev_start > owndev_end:
            st.error("Startdatum moet voor einddatum liggen.")
        else:
            te_verwerken = [d for d in owndev_dates if owndev_start <= d <= owndev_end]
            progress = st.progress(0)
            status   = st.empty()
            fouten   = []
            for i, d in enumerate(te_verwerken):
                status.text(f"Verwerken {d} ({i+1}/{len(te_verwerken)})…")
                try:
                    owndev.save_day_csv(d)
                except Exception as e:
                    fouten.append(f"{d}: {e}")
                progress.progress((i + 1) / len(te_verwerken))
            status.empty()
            if fouten:
                st.warning(f"Klaar met {len(fouten)} fout(en):\n" + "\n".join(fouten))
            else:
                st.success(f"✅ {len(te_verwerken)} dag(en) verwerkt naar CSV")

    if btn_col2.button("🔍 Verwerk alle ontbrekende CSV's"):
        with st.spinner("Alle dagmappen controleren…"):
            verwerkt, fouten = owndev.process_missing_csvs()
        if fouten:
            st.warning(
                f"{len(verwerkt)} dag(en) aangemaakt, {len(fouten)} fout(en):\n"
                + "\n".join(f"{d}: {e}" for d, e in fouten.items())
            )
        elif verwerkt:
            st.success(f"✅ {len(verwerkt)} dag(en) aangemaakt: "
                       + ", ".join(d.strftime("%d/%m") for d in verwerkt))
        else:
            st.info("Alle CSV's waren al aanwezig, niets te doen.")

# ── iLuCharge laadsessies ─────────────────────────────────────────────────
st.divider()
st.header("⚡ iLuCharge laadsessies")

st.info(
    "Verwerk alle iLuCharge-exportbestanden in de Solarcharge-map naar één "
    "gededupliceerde CSV met gemiddeld verbruik per kwartier per sessie.\n\n"
    f"Outputbestand: `{solarcharge.OUTPUT_FILE}`"
)

# Toon huidige status van de outputfile
_sess_df = solarcharge.available_sessions()
if _sess_df is not None:
    n_kwartieren = len(_sess_df)
    n_sessies = _sess_df[["from_dt", "to_dt", "user"]].drop_duplicates().shape[0]
    st.caption(f"{n_sessies} sessies · {n_kwartieren} kwartierrijen opgeslagen")
    import pandas as pd
    weergave = _sess_df[["kwartier", "from_dt", "to_dt", "user",
                          "sessie_kwh", "overlap_min", "energie_kwh", "gem_vermogen_kw"]].copy()
    weergave.columns = ["Kwartier", "Van", "Tot", "Gebruiker",
                        "Sessie kWh", "Overlap (min)", "Energie (kWh)", "Gem. vermogen (kW)"]
    for col in ["Kwartier", "Van", "Tot"]:
        weergave[col] = pd.to_datetime(weergave[col]).dt.strftime("%d/%m/%Y %H:%M")
    st.dataframe(weergave, hide_index=True, use_container_width=True)
else:
    st.warning("Nog geen sessie-CSV aangemaakt. Klik op de knop hieronder.")

if st.button("⚙️ Verwerk iLuCharge-bestanden"):
    with st.spinner("Laadsessies inlezen en samenvoegen…"):
        try:
            path, n = solarcharge.save_sessions()
            st.success(f"✅ {n} sessies opgeslagen in {path}")
            st.rerun()
        except Exception as e:
            st.error(f"Fout: {e}")

# ── Analyse: batterij-responsietijd ──────────────────────────────────────
st.divider()
st.header("📈 Analyse: batterij-responsietijd")

from scripts import analyse_response

st.info("Detecteert commandowisselingen in alle OwnDev-logs en bewaart de batterij- en netstroom op 0–5 s erna. Resultaten zijn zichtbaar op de pagina **Analyse**.")

if st.button("🔬 Analyseer batterij-respons"):
    with st.spinner("Alle OwnDev-logs doorzoeken…"):
        try:
            path, df_res, fouten = analyse_response.run()
            st.success(f"{len(df_res)} wisselingen opgeslagen in {path.name}")
            if fouten:
                st.warning(f"{len(fouten)} fout(en):\n" + "\n".join(fouten[:10]))
        except Exception as e:
            st.error(f"Fout: {e}")
