# Energie Dashboard — Vilvoorde

Een lokaal Streamlit-dashboard voor het opvolgen van energieverbruik, zonnepanelen, thuisbatterij en gasafname van een Belgische woning in Vilvoorde. De data is afkomstig van een P1 slimme meter, een SOFAR ME3000SP omvormer/batterij en het SolarLogs telemetrieplatform.

---

## Wat doet de applicatie?

De app biedt vier pagina's:

| Pagina | Omschrijving |
|---|---|
| **📊 Dag Grafiek** | Injectie naar het net, afname van het net en batterij-laadtoestand (SOC) per uur voor een gekozen dag. Zonneschijn en instraling op de panelen worden op een vierde grafiek getoond. Ondersteunt twee databronnen: SolarLogs API (uurdata) en OwnDev minuutbestanden. |
| **⬇️ Data Ophalen** | Download nieuwe solar meter-, batterij- en weerdata van de respectievelijke API's en sla ze lokaal op. |
| **📈 Analyse** | Placeholder voor toekomstige langetermijn analyses, maandoverzichten en verbruiksvoorspellingen. |
| **📋 Dagelijkse Totalen** | Overzichtstabel met dagelijkse totalen voor injectie, afname, batterij geladen en ontladen. Filterbaar op periode. |

---

## Projectstructuur

```
V1Eindwerk/
├── app.py                        # Streamlit startpagina (streamlit run app.py)
├── .env                          # Configuratievariabelen (paden, coördinaten, API-URLs)
├── requirements.txt              # Python-afhankelijkheden
├── setup_secrets.py              # Hulpscript om secrets eenmalig op te slaan
│
├── scripts/
│   ├── config.py                 # Laden van .env en secrets uit Windows Credential Manager
│   ├── solar_logs.py             # SolarLogs API: ophalen en inlezen van meterwaarden
│   ├── battery.py                # SolarBattery API: ophalen en inlezen van batterijdata
│   ├── weather.py                # Open-Meteo API + pvlib POA-berekening
│   └── owndev.py                 # Parser voor lokale OwnDev P1+SOFAR telegram-bestanden
│
├── pages/
│   ├── 1_📊_Dag_Grafiek.py       # Uur-voor-uur grafiek per dag
│   ├── 2_⬇️_Data_Ophalen.py      # Download-interface voor API-data
│   ├── 3_📈_Analyse.py           # Analyse (in opbouw)
│   └── 4_📋_Dagelijkse_Totalen.py # Dagelijkse samenvattingstabel
│
├── Source Data/
│   ├── SolarLogs/                # JSON-bestanden per dag: YYYYMMDD - solar.json  (nov 2024 – heden)
│   ├── SolarBattery/             # JSON-bestanden per dag: YYYYMMDD - solar.json  (nov 2024 – heden)
│   ├── OwnDev/                   # Minuutbestanden: YYYY-MM-DD/HH/telegram_*.txt  (jan 2026)
│   ├── MijnOpstelling/           # Installatiegegevens per dag                    (jan 2026)
│   ├── Pricing.csv               # Elektriciteitsprijzen
│   ├── ResultSolarLogs.xlsx      # Verwerkte SolarLogs exportresultaten
│   ├── Verbruikshistoriek_elektriciteit.csv  # Historisch verbruik van het net
│   └── vilvoorde_zonneschijn.csv # Weerdata met POA-instraling (gegenereerd door weather.py)
│
├── FYI/                          # Achtergrondinfo en referentiemateriaal
├── GetDatab.ipynb                # Notebook voor handmatig data ophalen
├── DagGrafiek.ipynb              # Notebook versie van de daggrafiek
└── AnalyseZonneschijn.ipynb      # Notebook voor zonneschijnanalyse
```

---

## Installatie

### 1. Python-omgeving opzetten

```bash
pip install -r requirements.txt
```

De applicatie vereist Python 3.10 of hoger (vanwege `X | Y` type-annotaties en walrus-operator).

### 2. `.env` configureren

Kopieer `.env` en pas de paden aan naar jouw installatie:

```dotenv
# Paden naar lokale dataopslag
SOLAR_DIR=C:\pad\naar\Source Data\SolarLogs
BATTERY_DIR=C:\pad\naar\Source Data\SolarBattery
WEATHER_CSV=C:\pad\naar\Source Data\vilvoorde_zonneschijn.csv

# Installatie-ID's (geen secrets — staan in .env)
SOLAR_ADRESID=<jouw adresid>
BATTERY_SN=<serienummer batterij>

# GPS-coördinaten voor weerdata en pvlib-berekeningen
LAT=50.9281
LON=4.4191

# Paneeloriëntatie
PANEL_TILT=35          # Helling in graden (0=horizontaal, 90=verticaal)
PANEL_AZIMUTH=292.5    # Kompasbearing: 0=Noord, 90=Oost, 180=Zuid, 270=West, WNW=292.5

# API-eindpunten
SOLAR_API_URL=https://www.solarlogs.be/API/dm_api.php
BATTERY_API_URL=https://www.solarlogs.be/API/ilucharge_api.php
WEATHER_API_URL=https://archive-api.open-meteo.com/v1/archive
```

### 3. API-secrets opslaan in Windows Credential Manager

De authenticatiesleutels voor de SolarLogs en SolarBattery API worden **niet** in `.env` opgeslagen maar in de Windows Credential Manager via `keyring`. Voer dit eenmalig uit in een terminal:

```python
python -c "
import keyring
keyring.set_password('V1Eindwerk', 'solar_auth_key', '<jouw solar sleutel>')
keyring.set_password('V1Eindwerk', 'battery_auth_key', '<jouw battery sleutel>')
"
```

Of gebruik het meegeleverde hulpscript:

```bash
python setup_secrets.py
```

De secrets worden daarna automatisch opgehaald door `scripts/config.py` bij elke API-aanroep.

---

## Applicatie starten

```bash
streamlit run app.py
```

De app opent automatisch in de standaardbrowser op `http://localhost:8501`.

---

## Databronnen

### SolarLogs API (`scripts/solar_logs.py`)
- **Endpoint:** `https://www.solarlogs.be/API/dm_api.php`
- **Authenticatie:** `AUTH_key` header, opgeslagen in Windows Credential Manager
- **Data:** uurlijkse meterwaarden per dag — injectie (kWh), afname (kWh) en nettoteller
- **Lokale opslag:** `Source Data/SolarLogs/YYYYMMDD - solar.json`

### SolarBattery API (`scripts/battery.py`)
- **Endpoint:** `https://www.solarlogs.be/API/ilucharge_api.php`
- **Authenticatie:** `AUTH_key` header, opgeslagen in Windows Credential Manager
- **Data per uur:** `soc` (%), `charged` (kWh geladen), `decharged` (kWh ontladen)
- **Dagelijkse totalen:** geladen/ontladen in kWh + kost laden (€) en opbrengst ontladen (€)
- **Lokale opslag:** `Source Data/SolarBattery/YYYYMMDD - solar.json`
- **Retry-mechanisme:** de API retourneert soms een leeg antwoord bij snelle opeenvolgende aanvragen; de module herprobeert automatisch tot 10 keer met een pauze van 2,5 s per poging.

### Open-Meteo (`scripts/weather.py`)
- **Endpoint:** `https://archive-api.open-meteo.com/v1/archive`
- **Authenticatie:** geen — gratis publieke API
- **Data:** GHI, DNI, DHI (W/m²) en zonneschijnduur (s/uur)
- **POA-berekening:** De instraling op het paneeloppervlak (Plane of Array) wordt **lokaal** berekend via `pvlib` met het Hay-Davies model, op basis van `PANEL_TILT` en `PANEL_AZIMUTH` uit `.env`.
- **Lokale opslag:** één CSV-bestand (`WEATHER_CSV` in `.env`)

### OwnDev P1 + SOFAR (`scripts/owndev.py`)
- **Bron:** lokale tekstbestanden gegenereerd door een OwnDev-apparaat
- **Bestandsstructuur:** `OwnDev/YYYY-MM-DD/HH/telegram_YYYY-MM-DD_HH-MM.txt`
- **Data:** minuut-voor-minuut P1-telegramgegevens (verbruik kW, levering kW, gas m³, water m³) gecombineerd met SOFAR Modbus-registers (batterijvermogen kW, SOC %)
- **Aggregatie:** `load_day_hourly()` aggregeert de minuutdata naar uurdata (kWh via gemiddeld vermogen × gemeten duur)

---

## Paneeloriëntatie en POA-berekening

De zonnepanelen zijn georiënteerd op **WNW (West-Noord-West)** met een helling van **35°**:

- `PANEL_AZIMUTH = 292.5°` (kompasbearing, 0=Noord)
- `PANEL_TILT = 35°` (helling t.o.v. horizontaal)

`pvlib` gebruikt de **pvlib-azimutconventie** (0=Noord, 90=Oost, 180=Zuid, 270=West), wat overeenkomt met de kompasbearing. Het **Hay-Davies** diffuus-stralingsmodel wordt gebruikt omdat het beter presteert voor niet-zuidgerichte en hellende vlakken dan het isotropisch model.

De POA-instraling wordt op 0 gezet wanneer de zenithoek van de zon groter is dan 85° (zon dicht bij of onder de horizon), omdat het model daar onbetrouwbaar wordt.

---

## Lokale ontwikkeling

- Alle lokale bestandspaden staan in `.env` — de app werkt ook als de databestanden ergens anders staan, zolang `.env` correct is ingesteld.
- De `scripts/`-map is een Python-package (`__init__.py` vereist indien niet aanwezig).
- Streamlit laadt `pages/` automatisch als subpagina's op basis van bestandsnaam en volgorde.
