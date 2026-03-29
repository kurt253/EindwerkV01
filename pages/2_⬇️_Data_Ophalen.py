"""
Data Ophalen: download solar, batterij en weerdata via de API's.
"""

from datetime import date, timedelta

import streamlit as st

from scripts import battery, solar_logs, weather

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
        progress = st.progress(0)
        dagen = (solar_end - solar_start).days + 1
        status = st.empty()
        try:
            dag = solar_start
            for i in range(dagen):
                status.text(f"Ophalen {dag} ({i+1}/{dagen})…")
                solar_logs.fetch_day(dag.year, dag.month, dag.day)
                # sla op via download_range per dag
                from scripts.config import SOLAR_DIR
                import json
                # Tweede aanroep fetch_day: de API heeft geen caching, dus dit is een echte tweede call
                data = solar_logs.fetch_day(dag.year, dag.month, dag.day)
                path = SOLAR_DIR / f"{dag.strftime('%Y%m%d')} - solar.json"
                path.write_text(json.dumps(data, indent=4), encoding="utf-8")
                dag += timedelta(days=1)
                # Voortgangsbalk bijwerken: waarde loopt van 0.0 tot 1.0
                progress.progress((i + 1) / dagen)
            st.success(f"✅ {dagen} dag(en) opgeslagen in {SOLAR_DIR}")
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
        progress2 = st.progress(0)
        dagen = (bat_end - bat_start).days + 1
        status2 = st.empty()
        try:
            dag = bat_start
            for i in range(dagen):
                status2.text(f"Ophalen {dag} ({i+1}/{dagen})…")
                from scripts.config import BATTERY_DIR
                import json
                data = battery.fetch_day(dag.year, dag.month, dag.day, max_retries=5, delay=0)
                path = BATTERY_DIR / f"{dag.strftime('%Y%m%d')} - solar.json"
                path.write_text(json.dumps(data, indent=4), encoding="utf-8")
                dag += timedelta(days=1)
                progress2.progress((i + 1) / dagen)
            st.success(f"✅ {dagen} dag(en) opgeslagen in {BATTERY_DIR}")
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
