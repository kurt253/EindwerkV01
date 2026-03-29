"""
Hoofdpagina van de Streamlit applicatie.
Start met: streamlit run app.py
"""

import streamlit as st

st.set_page_config(
    page_title="Energie Dashboard",
    page_icon="⚡",
    layout="wide",
)

st.title("⚡ Energie Dashboard — Vilvoorde")
st.markdown(
    """
    Welkom! Navigeer via de zijbalk naar een pagina.

    | Pagina | Omschrijving |
    |---|---|
    | 📊 Dag Grafiek | Injectie, afname en batterij per uur voor een gekozen dag |
    | ⬇️ Data Ophalen | Download nieuwe data van de Solarlogs en weer API |
    | 📈 Analyse | *(in opbouw)* Langetermijn analyses en trends |
    """
)

st.divider()

# Snelle status: hoeveel lokale bestanden beschikbaar?
# Import binnen try-blok zodat een ontbrekende .env of secrets de startpagina niet crasht
try:
    from scripts import solar_logs, battery

    n_solar   = len(solar_logs.available_dates())
    n_battery = len(battery.available_dates())
    col1, col2 = st.columns(2)
    col1.metric("Solar log bestanden", n_solar)
    col2.metric("Batterij bestanden", n_battery)
except Exception as e:
    st.warning(f"Kon lokale data niet tellen: {e}")
