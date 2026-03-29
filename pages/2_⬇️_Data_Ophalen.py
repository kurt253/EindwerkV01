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
                data = solar_logs.fetch_day(dag.year, dag.month, dag.day)
                path = SOLAR_DIR / f"{dag.strftime('%Y%m%d')} - solar.json"
                path.write_text(json.dumps(data, indent=4), encoding="utf-8")
                dag += timedelta(days=1)
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
