"""
Energie Dashboard — Vilvoorde
Start met: streamlit run app.py
"""

import json
from datetime import date, timedelta
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

from scripts import battery, fluvius, owndev, solar_logs, solarcharge, weather
from scripts.config import BATTERY_DIR, SOLAR_DIR, SOURCE_DIR, WEATHER_CSV
from scripts.fluvius import OUTPUT_FILE as FLUVIUS_OUTPUT
from scripts.owndev import OUTPUT_FILE as OWNDEV_OUTPUT

st.set_page_config(page_title="Energie Dashboard", page_icon="⚡", layout="wide")
st.title("⚡ Energie Dashboard — Vilvoorde")

# ═══════════════════════════════════════════════════════════════════════════
# STATUS (altijd zichtbaar bovenaan)
# ═══════════════════════════════════════════════════════════════════════════
try:
    solar_dates   = solar_logs.available_dates()
    battery_dates = battery.available_dates()
    ev_sessions   = solarcharge.available_sessions()
    df_fluvius    = fluvius.laad()
    owndev_ok     = OWNDEV_OUTPUT.exists()

    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.metric("Solarlogs",   f"{len(solar_dates)} dagen",
              delta=f"t/m {solar_dates[-1]}" if solar_dates else None)
    c2.metric("Batterij",    f"{len(battery_dates)} dagen",
              delta=f"t/m {battery_dates[-1]}" if battery_dates else None)
    c3.metric("EV sessies",  len(ev_sessions) if ev_sessions is not None else "—")
    c4.metric("Fluvius",     f"{len(df_fluvius):,} kwartieren" if not df_fluvius.empty else "—")
    c5.metric("Weerdata",    "✓" if WEATHER_CSV.exists() else "✗")
    c6.metric("OwnDev",      "✓ verwerkt" if owndev_ok else "✗ ontbreekt")
except Exception as e:
    st.error(f"Status ophalen mislukt: {e}")

st.divider()

# ═══════════════════════════════════════════════════════════════════════════
# TABS
# ═══════════════════════════════════════════════════════════════════════════
tab_grafieken, tab_beheer = st.tabs(["📊 Grafieken", "⬇️ Beheer"])


# ───────────────────────────────────────────────────────────────────────────
# TAB 1 — GRAFIEKEN
# ───────────────────────────────────────────────────────────────────────────
with tab_grafieken:
    bron = st.radio(
        "Databron",
        ["Solarlogs & Batterij", "Fluvius", "EV Laadsessies", "Weer"],
        horizontal=True,
    )

    # ── Solarlogs & Batterij ────────────────────────────────────────────────
    if bron == "Solarlogs & Batterij":
        solar_dates = solar_logs.available_dates()
        if not solar_dates:
            st.warning("Geen Solarlogs-data. Download eerst via Beheer.")
        else:
            gekozen = st.date_input(
                "Dag",
                value=solar_dates[-1],
                min_value=solar_dates[0],
                max_value=solar_dates[-1],
                key="dag_solar",
            )

            df_solar = solar_logs.load_day(gekozen)
            df_bat   = battery.load_day(gekozen)

            # Voeg productie toe uit ruwe JSON
            if df_solar is not None:
                raw_path = SOLAR_DIR / f"{gekozen.strftime('%Y%m%d')} - solar.json"
                if raw_path.exists():
                    raw = json.loads(raw_path.read_text(encoding="utf-8"))
                    prod_map = {
                        pd.to_datetime(r["valueDate"]).hour: float(r.get("production", 0) or 0)
                        for r in raw["data"]
                    }
                    df_solar["productie"] = df_solar.index.map(prod_map).fillna(0)

            col_s, col_b = st.columns(2)

            with col_s:
                st.subheader("Verbruik & Productie")
                if df_solar is None:
                    st.info(f"Geen data voor {gekozen}.")
                else:
                    kolommen = ["afname", "injectie"] + (["productie"] if "productie" in df_solar.columns else [])
                    df_sl = df_solar[kolommen].reset_index().melt(id_vars="uur", var_name="type", value_name="kWh")
                    kleur_s = alt.Scale(
                        domain=["afname", "injectie", "productie"],
                        range=["#e05c5c", "#5c9be0", "#f5a623"],
                    )
                    st.altair_chart(
                        alt.Chart(df_sl).mark_bar(width=16).encode(
                            x=alt.X("uur:O", title="Uur", axis=alt.Axis(labelAngle=0)),
                            y=alt.Y("kWh:Q"),
                            color=alt.Color("type:N", scale=kleur_s, legend=alt.Legend(title="")),
                            xOffset="type:N",
                            tooltip=["uur:O", "type:N", alt.Tooltip("kWh:Q", format=".3f")],
                        ).properties(height=280),
                        use_container_width=True,
                    )

            with col_b:
                st.subheader("Batterij")
                if df_bat is None:
                    st.info(f"Geen batterijdata voor {gekozen}.")
                else:
                    df_bl = df_bat[["geladen", "ontladen"]].reset_index().melt(id_vars="uur", var_name="type", value_name="kWh")
                    kleur_b = alt.Scale(domain=["geladen", "ontladen"], range=["#2ca02c", "#ff7f0e"])
                    bars = alt.Chart(df_bl).mark_bar(width=20).encode(
                        x=alt.X("uur:O", title="Uur", axis=alt.Axis(labelAngle=0)),
                        y=alt.Y("kWh:Q"),
                        color=alt.Color("type:N", scale=kleur_b, legend=alt.Legend(title="")),
                        xOffset="type:N",
                        tooltip=["uur:O", "type:N", alt.Tooltip("kWh:Q", format=".3f")],
                    ).properties(height=220)
                    soc_line = alt.Chart(df_bat[["soc"]].reset_index()).mark_line(
                        point=True, color="#9467bd", strokeWidth=2,
                    ).encode(
                        x=alt.X("uur:O"),
                        y=alt.Y("soc:Q", title="SOC %", scale=alt.Scale(domain=[0, 100])),
                        tooltip=["uur:O", "soc:Q"],
                    )
                    st.altair_chart(bars, use_container_width=True)
                    st.caption("State of Charge (%)")
                    st.altair_chart(soc_line.properties(height=120), use_container_width=True)

            # POA
            if WEATHER_CSV.exists():
                df_weer = weather.load()
                dag_start = pd.Timestamp(gekozen)
                df_dw = df_weer[(df_weer.index >= dag_start) & (df_weer.index < dag_start + timedelta(days=1))].copy()
                if not df_dw.empty and "poa_irradiance" in df_dw.columns:
                    df_dw = df_dw.reset_index()
                    df_dw["uur"] = df_dw["time"].dt.hour
                    st.subheader("Instraling (POA)")
                    st.altair_chart(
                        alt.Chart(df_dw).mark_area(opacity=0.5, color="#f5c518", line={"color": "#d4a800"}).encode(
                            x=alt.X("uur:O", title="Uur", axis=alt.Axis(labelAngle=0)),
                            y=alt.Y("poa_irradiance:Q", title="W/m²"),
                            tooltip=["uur:O", alt.Tooltip("poa_irradiance:Q", format=".0f", title="POA W/m²")],
                        ).properties(height=160),
                        use_container_width=True,
                    )

    # ── Fluvius ─────────────────────────────────────────────────────────────
    elif bron == "Fluvius":
        df_fl = fluvius.laad()
        if df_fl.empty:
            st.warning("Geen Fluvius-data. Verwerk eerst de exports via Beheer.")
        else:
            df_fl["afname_totaal"]   = df_fl["afname_dag"]   + df_fl["afname_nacht"]
            df_fl["injectie_totaal"] = df_fl["injectie_dag"] + df_fl["injectie_nacht"]

            datum_min = df_fl["kwartier"].min().date()
            datum_max = df_fl["kwartier"].max().date()
            van, tot = st.date_input(
                "Periode",
                value=(datum_min, datum_max),
                min_value=datum_min,
                max_value=datum_max,
                key="fluvius_periode",
            )
            df_sel = df_fl[(df_fl["kwartier"].dt.date >= van) & (df_fl["kwartier"].dt.date <= tot)]

            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Afname totaal",   f"{df_sel['afname_totaal'].sum():.1f} kWh")
            c2.metric("Injectie totaal", f"{df_sel['injectie_totaal'].sum():.1f} kWh")
            c3.metric("Afname dag",      f"{df_sel['afname_dag'].sum():.1f} kWh")
            c4.metric("Afname nacht",    f"{df_sel['afname_nacht'].sum():.1f} kWh")

            col_links, col_rechts = st.columns([3, 1])
            with col_links:
                granulariteit = st.radio("Per", ["Dag", "Week", "Maand"], horizontal=True, key="fl_gran")
            with col_rechts:
                dag_nacht = st.toggle("Dag/nacht", key="fl_dn")

            freq = {"Dag": "D", "Week": "W-MON", "Maand": "ME"}[granulariteit]
            df_agg = (
                df_sel.set_index("kwartier")
                [["afname_dag", "afname_nacht", "injectie_dag", "injectie_nacht"]]
                .resample(freq).sum()
                .reset_index()
            )
            df_agg["afname_totaal"]   = df_agg["afname_dag"]   + df_agg["afname_nacht"]
            df_agg["injectie_totaal"] = df_agg["injectie_dag"] + df_agg["injectie_nacht"]

            kleur_dn = alt.Scale(domain=["Dag", "Nacht"], range=["#e05c5c", "#9b4dca"])

            def _fl_grafiek(df, kolom_totaal, kolom_dag, kolom_nacht, kleur_enkel, titel):
                st.subheader(titel)
                if dag_nacht:
                    df_m = df[["kwartier", kolom_dag, kolom_nacht]].melt(id_vars="kwartier", var_name="tarief", value_name="kWh")
                    df_m["tarief"] = df_m["tarief"].map({kolom_dag: "Dag", kolom_nacht: "Nacht"})
                    ch = alt.Chart(df_m).mark_bar().encode(
                        x=alt.X("kwartier:T", title=""),
                        y=alt.Y("kWh:Q"),
                        color=alt.Color("tarief:N", scale=kleur_dn, legend=alt.Legend(title="")),
                        tooltip=["kwartier:T", "tarief:N", alt.Tooltip("kWh:Q", format=".3f")],
                    )
                else:
                    ch = alt.Chart(df).mark_bar(color=kleur_enkel).encode(
                        x=alt.X("kwartier:T", title=""),
                        y=alt.Y(f"{kolom_totaal}:Q", title="kWh"),
                        tooltip=["kwartier:T", alt.Tooltip(f"{kolom_totaal}:Q", format=".3f", title="kWh")],
                    )
                st.altair_chart(ch.properties(height=260), use_container_width=True)

            _fl_grafiek(df_agg, "afname_totaal",   "afname_dag",   "afname_nacht",   "#e05c5c", "Afname")
            _fl_grafiek(df_agg, "injectie_totaal", "injectie_dag", "injectie_nacht", "#5c9be0", "Injectie")

            with st.expander("Ruwe kwartierdata"):
                st.dataframe(
                    df_sel[["kwartier", "afname_dag", "afname_nacht", "injectie_dag", "injectie_nacht"]]
                    .sort_values("kwartier", ascending=False),
                    use_container_width=True, hide_index=True,
                )

    # ── EV Laadsessies ──────────────────────────────────────────────────────
    elif bron == "EV Laadsessies":
        @st.cache_data(show_spinner="Laadsessies laden…")
        def _laad_ev():
            df = solarcharge.available_sessions()
            return df if df is not None else solarcharge.load_all_sessions()

        df_ev = _laad_ev()
        if df_ev is None or df_ev.empty:
            st.warning("Geen laadsessiedata. Verwerk eerst via Beheer.")
        else:
            sess = df_ev.drop_duplicates(subset=["from_dt", "to_dt", "user"])
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Sessies",          len(sess))
            c2.metric("Totaal geladen",   f"{sess['sessie_kwh'].sum():.1f} kWh")
            c3.metric("Gemiddeld/sessie", f"{sess['sessie_kwh'].mean():.1f} kWh")
            c4.metric("Grootste sessie",  f"{sess['sessie_kwh'].max():.1f} kWh")

            datum_min = df_ev["from_dt"].min().date()
            datum_max = df_ev["to_dt"].max().date()
            van_ev, tot_ev = st.date_input(
                "Periode",
                value=(datum_min, datum_max),
                min_value=datum_min,
                max_value=datum_max,
                key="ev_periode",
            )
            df_ev_sel = df_ev[(df_ev["from_dt"].dt.date >= van_ev) & (df_ev["to_dt"].dt.date <= tot_ev)]

            st.subheader("Laadvermogen per kwartier")
            st.altair_chart(
                alt.Chart(df_ev_sel).mark_bar(color="#2ca02c").encode(
                    x=alt.X("kwartier:T", title=""),
                    y=alt.Y("gem_vermogen_kw:Q", title="kW"),
                    tooltip=["kwartier:T", alt.Tooltip("gem_vermogen_kw:Q", format=".2f", title="kW"),
                             alt.Tooltip("energie_kwh:Q", format=".3f", title="kWh"), "user:N"],
                ).properties(height=260),
                use_container_width=True,
            )

            st.subheader("Sessies")
            tabel = (
                sess[(sess["from_dt"].dt.date >= van_ev) & (sess["to_dt"].dt.date <= tot_ev)]
                .sort_values("from_dt", ascending=False)
                [["from_dt", "to_dt", "user", "sessie_kwh"]]
                .rename(columns={"from_dt": "Start", "to_dt": "Einde", "user": "Gebruiker", "sessie_kwh": "kWh"})
            )
            st.dataframe(tabel, use_container_width=True, hide_index=True)

    # ── Weer ────────────────────────────────────────────────────────────────
    elif bron == "Weer":
        if not WEATHER_CSV.exists():
            st.warning("Geen weerdata. Download eerst via Beheer.")
        else:
            @st.cache_data(show_spinner="Weerdata laden…")
            def _laad_weer():
                return weather.load()

            df_w = _laad_weer()
            datum_min = df_w.index.min().date()
            datum_max = df_w.index.max().date()
            van_w, tot_w = st.date_input(
                "Periode",
                value=(datum_min, datum_max),
                min_value=datum_min,
                max_value=datum_max,
                key="weer_periode",
            )
            df_ws = df_w[(df_w.index.date >= van_w) & (df_w.index.date <= tot_w)].copy()

            c1, c2, c3 = st.columns(3)
            c1.metric("Gem. POA", f"{df_ws['poa_irradiance'].mean():.0f} W/m²")
            c2.metric("Max POA",  f"{df_ws['poa_irradiance'].max():.0f} W/m²")
            if "sunshine_min_per_hour" in df_ws.columns:
                c3.metric("Zonneschijn", f"{df_ws['sunshine_min_per_hour'].sum()/60:.0f} uur")

            df_wp = df_ws.reset_index().rename(columns={"time": "tijdstip"})

            st.subheader("Instraling op panelen (POA)")
            st.altair_chart(
                alt.Chart(df_wp).mark_line(color="#f5c518", strokeWidth=1.5).encode(
                    x=alt.X("tijdstip:T", title=""),
                    y=alt.Y("poa_irradiance:Q", title="W/m²"),
                    tooltip=["tijdstip:T", alt.Tooltip("poa_irradiance:Q", format=".0f", title="POA W/m²")],
                ).properties(height=240),
                use_container_width=True,
            )

            if "sunshine_min_per_hour" in df_wp.columns and "shortwave_radiation" in df_wp.columns:
                col_a, col_b = st.columns(2)
                with col_a:
                    st.subheader("Zonneschijn (min/uur)")
                    st.altair_chart(
                        alt.Chart(df_wp).mark_bar(color="#ffcc44").encode(
                            x=alt.X("tijdstip:T", title=""),
                            y=alt.Y("sunshine_min_per_hour:Q", title="min"),
                            tooltip=["tijdstip:T", alt.Tooltip("sunshine_min_per_hour:Q", format=".0f")],
                        ).properties(height=200),
                        use_container_width=True,
                    )
                with col_b:
                    st.subheader("Globale straling GHI (W/m²)")
                    st.altair_chart(
                        alt.Chart(df_wp).mark_line(color="#5c9be0", strokeWidth=1.2).encode(
                            x=alt.X("tijdstip:T", title=""),
                            y=alt.Y("shortwave_radiation:Q", title="W/m²"),
                            tooltip=["tijdstip:T", alt.Tooltip("shortwave_radiation:Q", format=".0f")],
                        ).properties(height=200),
                        use_container_width=True,
                    )


# ───────────────────────────────────────────────────────────────────────────
# TAB 2 — BEHEER
# ───────────────────────────────────────────────────────────────────────────
with tab_beheer:

    def _datumkiezer(label: str, default_van: date, default_tot: date, key: str):
        if default_van > default_tot:
            default_van = default_tot
        return st.date_input(
            label,
            value=(default_van, default_tot),
            min_value=date(2024, 1, 1),
            max_value=date.today(),
            key=key,
        )

    def _range(sel):
        if isinstance(sel, (list, tuple)) and len(sel) == 2:
            return sel
        return sel, sel

    # ── Solarlogs ────────────────────────────────────────────────────────────
    with st.expander("☀️ Solarlogs downloaden", expanded=True):
        solar_dates = solar_logs.available_dates()
        if solar_dates:
            st.caption(f"Aanwezig: {solar_dates[0]} t/m {solar_dates[-1]} ({len(solar_dates)} dagen)")
        van_s, tot_s = _range(_datumkiezer(
            "Periode",
            (solar_dates[-1] + timedelta(days=1)) if solar_dates else date(2024, 11, 1),
            date.today() - timedelta(days=1),
            key="beh_solar",
        ))
        if st.button("▶ Download Solarlogs"):
            with st.spinner(f"Downloaden {van_s} t/m {tot_s}…"):
                try:
                    saved = solar_logs.download_range(van_s, tot_s)
                    st.success(f"{len(saved)} bestand(en) opgeslagen.")
                except Exception as e:
                    st.error(f"Fout: {e}")

    # ── Batterij ─────────────────────────────────────────────────────────────
    with st.expander("🔋 Batterijdata downloaden", expanded=True):
        battery_dates = battery.available_dates()
        if battery_dates:
            st.caption(f"Aanwezig: {battery_dates[0]} t/m {battery_dates[-1]} ({len(battery_dates)} dagen)")
        van_b, tot_b = _range(_datumkiezer(
            "Periode",
            (battery_dates[-1] + timedelta(days=1)) if battery_dates else date(2024, 11, 1),
            date.today() - timedelta(days=1),
            key="beh_bat",
        ))
        overschrijf_b = st.checkbox("Bestaande bestanden overschrijven", key="overschrijf_bat")
        if st.button("▶ Download Batterijdata"):
            with st.spinner(f"Downloaden {van_b} t/m {tot_b}…"):
                try:
                    opgeslagen, fouten = battery.download_range(van_b, tot_b, overschrijven=overschrijf_b)
                    st.success(f"{len(opgeslagen)} bestand(en) opgeslagen.")
                    if fouten:
                        st.warning(f"{len(fouten)} dag(en) mislukt:")
                        for d, err in fouten.items():
                            st.caption(f"  {d}: {err}")
                except Exception as e:
                    st.error(f"Fout: {e}")

    # ── Weerdata ──────────────────────────────────────────────────────────────
    with st.expander("🌤 Weerdata ophalen"):
        if WEATHER_CSV.exists():
            st.caption(f"Lokaal bestand: `{WEATHER_CSV}`")
        van_w, tot_w = _range(_datumkiezer(
            "Periode",
            date(2024, 11, 1),
            date.today() - timedelta(days=1),
            key="beh_weer",
        ))
        col_w1, col_w2 = st.columns(2)
        if col_w1.button("▶ Haal weerdata op"):
            with st.spinner("Ophalen via Open-Meteo…"):
                try:
                    pad = weather.fetch_and_save(str(van_w), str(tot_w))
                    st.cache_data.clear()
                    st.success(f"Opgeslagen: `{pad}`")
                except Exception as e:
                    st.error(f"Fout: {e}")
        if col_w2.button("↻ Herbereken POA"):
            with st.spinner("Bezig…"):
                weather.recalculate_poa()
                st.cache_data.clear()
                st.success("POA herberekend.")

    # ── Fluvius ───────────────────────────────────────────────────────────────
    with st.expander("⚡ Fluvius verwerken"):
        if FLUVIUS_OUTPUT.exists():
            df_fl_info = fluvius.laad()
            if not df_fl_info.empty:
                st.caption(
                    f"Al verwerkt: {df_fl_info['kwartier'].min().date()} t/m "
                    f"{df_fl_info['kwartier'].max().date()} ({len(df_fl_info):,} kwartieren)"
                )
        else:
            st.caption("Nog geen verwerkte data.")
        st.markdown("Scant alle Fluvius CSV-exports. Enkel nieuwe kwartieren worden toegevoegd.")
        if st.button("▶ Verwerk Fluvius-exports"):
            with st.spinner("Bezig…"):
                try:
                    pad, n = fluvius.verwerk()
                    st.cache_data.clear()
                    if n:
                        st.success(f"{n:,} nieuwe kwartieren toegevoegd.")
                    else:
                        st.info("Geen nieuwe kwartieren — al up-to-date.")
                except Exception as e:
                    st.error(f"Fout: {e}")

    # ── EV Laadsessies ────────────────────────────────────────────────────────
    with st.expander("🔌 EV Laadsessies verwerken"):
        st.markdown("Scant alle iLuCharge CSV-bestanden en spreidt energie over kwartiersloten.")
        if st.button("▶ Verwerk laadsessies"):
            with st.spinner("Bezig…"):
                try:
                    pad, n = solarcharge.save_sessions()
                    st.cache_data.clear()
                    st.success(f"{n} kwartierrijen opgeslagen naar `{pad}`")
                except FileNotFoundError as e:
                    st.error(str(e))

    # ── OwnDev ────────────────────────────────────────────────────────────────
    with st.expander("📡 OwnDev telegrammen verwerken"):
        if OWNDEV_OUTPUT.exists():
            df_od_info = pd.read_csv(OWNDEV_OUTPUT, usecols=["tijdstip"], parse_dates=["tijdstip"])
            if not df_od_info.empty:
                st.caption(
                    f"Al verwerkt: {df_od_info['tijdstip'].min().date()} t/m "
                    f"{df_od_info['tijdstip'].max().date()} ({len(df_od_info):,} meetpunten)"
                )
        else:
            st.caption("Nog geen verwerkte data.")
        st.markdown(
            "Leest alle P1+SOFAR telegrambestanden in de OwnDev-map. "
            "Enkel nieuwe meetpunten (na de laatste tijdstempel) worden toegevoegd."
        )
        if st.button("▶ Verwerk OwnDev telegrammen"):
            voortgang = st.empty()
            with st.spinner("Bezig — dit kan enkele minuten duren bij eerste keer…"):
                try:
                    pad, n = owndev.verwerk()
                    st.cache_data.clear()
                    if n:
                        st.success(f"{n:,} nieuwe meetpunten toegevoegd aan `{pad}`")
                    else:
                        st.info("Geen nieuwe meetpunten — al up-to-date.")
                except Exception as e:
                    st.error(f"Fout: {e}")
