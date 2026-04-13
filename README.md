# Energie Dashboard — Vilvoorde

Lokaal Python-project voor het opvolgen, verwerken en analyseren van het energieverbruik
van een Belgische woning in Vilvoorde. Data is afkomstig van vijf bronnen: de Fluvius
digitale meter, een OwnDev Raspberry Pi-logger (P1 + SOFAR Modbus), de iLumen SolarLogs
API, de iLuCharge EV-laad-API en de Open-Meteo weerarchief-API.

---

## Doelstellingen

### 1. Datavoorbereiding — `notebooks/data_voorbereiding.ipynb`

Alle ruwe brondata ophalen, verwerken en samenvoegen tot één consistent kwartierbestand
(`data/Final/overall.csv`) dat als basis dient voor alle verdere analyses.

- Uurlijkse zonne- en netstroom ophalen via de iLumen SolarLogs API
- Batterijdata (SOC, geladen/ontladen) ophalen via de iLumen SolarBattery API
- Weerdata en POA-instraling ophalen via Open-Meteo + pvlib
- Fluvius kwartiertotalen verwerken vanuit lokale CSV-exports
- EV-laadsessies uitspreiden over kwartieren
- OwnDev seconde-telegrammen (P1 + SOFAR Modbus) verwerken
- EPEX dag-vooruit-prijzen importeren vanuit lokaal Excel-bestand en omzetten naar kwartierwaarden
- Batterij-responsanalyse: nauwkeurigheid van de SOFAR ME3000SP ten opzichte van gegeven commando's

### 2. Kwartieranalyse — `notebooks/kwartier_analyse.ipynb`

Inzicht in het werkelijke huisverbruik en de PV-opbrengst op basis van kwartierdata.

- Energiebalans per kwartier: huisverbruik corrigeren voor EV-lading, batterijflows en zonne-energie
- Weekpatroon: gemiddeld verbruik per kwartier per weekdag
- PV-opbrengst schatten via energiebalans (geen aparte productiemeter):
  `PV = basis_verbruik + ev + injectie + bat_laden − bat_ontladen − afname`
- Correlatie PV-opbrengst versus POA-instraling (regressie per dag)

### 3. Tariefvergelijking — `notebooks/tarief_vergelijking.ipynb`

Vergelijking van een vast DATS24-tarief met een dynamisch EPEX-tarief, met en zonder
batterijoptimalisatie via lineair programmeren.

- **Scenario A** — Vast tarief (DATS24) vs. dynamisch tarief (EPEX), zonder batterij
- **Scenario B** — Dynamisch tarief met LP-geoptimaliseerde batterijdispatch
- Maandoverzicht en top-10 dagen met grootste tariefverschil per scenario
- Per-dag analyse: kosten per kwartier naast de tariefsevolutie
- Samenvatting: totale besparing, jaarextrapolatie en terugverdientijd batterij

---

## Projectstructuur

```
V1Eindwerk/
│
├── app.py                              # Streamlit-dashboard (streamlit run app.py)
├── setup_secrets.py                    # Eenmalig: API-sleutels opslaan in Credential Manager
├── requirements.txt                    # Python-afhankelijkheden (pip)
├── environment.yml                     # Conda-omgevingsbestand
├── .env                                # Lokale paden + instellingen (niet in git)
│
├── config/
│   └── telegram_mapping.json           # OBIS-codes + Modbus-registers → kolomnamen
│
├── scripts/
│   ├── config.py                       # Centrale configuratie: paden, secrets, .env
│   ├── voorbereiding.py                # Volledige datavoorbereiding in één functieaanroep
│   ├── solar_logs.py                   # iLumen API — uurlijkse zon- en netstroom
│   ├── battery.py                      # iLumen API — uurlijkse batterijdata
│   ├── fluvius.py                      # Fluvius CSV-exports — kwartiertotalen meter
│   ├── owndev.py                       # OwnDev Raspberry Pi — P1 + SOFAR seconde-CSV
│   ├── solarcharge.py                  # iLuCharge CSV — EV-laadsessies per kwartier
│   ├── weather.py                      # Open-Meteo + pvlib — weerdata en POA-instraling
│   ├── epex.py                         # EPEX xlsx importeren → epex_be.csv
│   ├── epex_kwartier.py                # Kubische spline: uurprijzen → kwartierwaarden
│   └── overall.py                      # Alle bronnen samenvoegen → overall.csv
│
├── notebooks/
│   ├── data_voorbereiding.ipynb        # Doelstelling 1
│   ├── kwartier_analyse.ipynb          # Doelstelling 2
│   └── tarief_vergelijking.ipynb       # Doelstelling 3
│
└── data/
    ├── Source Data/
    │   ├── SolarLogs/                  # YYYYMMDD - solar.json (per dag)
    │   ├── SolarBattery/               # YYYYMMDD - solar.json (per dag)
    │   ├── OwnDev/                     # Telegrambestanden + commando-CSV per dag
    │   ├── Fluvius/                    # Semikolon-gescheiden Fluvius-exports
    │   ├── Solarcharge/                # iLuCharge CSV-exports
    │   └── epex.xlsx                   # EPEX dag-vooruit-prijzen (handmatig aangeleverd)
    ├── intermediate results/
    │   ├── epex_be.csv                 # Gegenereerd vanuit epex.xlsx
    │   ├── epex_kwartieren.csv         # Kwartierwaarden via kubische spline
    │   ├── owndev_seconden.csv         # Verwerkte seconde-tijdreeks
    │   └── commando_respons.csv        # Batterij-responsanalyse
    └── Final/
        ├── overall.csv                 # Alle bronnen per kwartier
        ├── overall_verrijkt.csv        # overall.csv + afgeleide verbruikskolommen
        ├── weekpatroon.csv             # Gem. verbruik per kwartier per weekdag
        └── pv_opbrengst_analyse.csv    # Dagelijkse PV-opbrengst en rendement
```

---

## Installatie

### Python-omgeving

**pip:**
```bash
pip install -r requirements.txt
```

**conda:**
```bash
conda env create -f environment.yml
conda activate v1eindwerk
```

Vereist Python ≥ 3.10.

| Pakket | Gebruik |
|---|---|
| `pandas`, `numpy` | DataFrames, tijdreeksen, numerieke berekeningen |
| `scipy` | Kubische spline (EPEX-conversie) + LP-optimalisatie (batterij) |
| `pvlib` | POA-instraling op basis van paneeloriëntatie |
| `plotly`, `ipywidgets` | Interactieve grafieken en widgets in notebooks |
| `matplotlib` | Statische grafieken |
| `streamlit` | Web-dashboard |
| `requests`, `openpyxl` | API-aanroepen en Excel-bestanden lezen |
| `python-dotenv`, `keyring` | Configuratie en secrets |

### `.env` aanmaken

```dotenv
# Paden naar lokale dataopslag
SOLAR_DIR=C:\pad\naar\SolarLogs
BATTERY_DIR=C:\pad\naar\SolarBattery
WEATHER_CSV=C:\pad\naar\vilvoorde_zonneschijn.csv

# Installatie-ID's
SOLAR_ADRESID=<adresid>
BATTERY_SN=<serienummer>

# GPS-coördinaten
LAT=50.9281
LON=4.4191

# Paneeloriëntatie
PANEL_TILT=35
PANEL_AZIMUTH=292.5

# API-eindpunten
SOLAR_API_URL=https://www.solarlogs.be/API/dm_api.php
BATTERY_API_URL=https://www.solarlogs.be/API/ilucharge_api.php
WEATHER_API_URL=https://archive-api.open-meteo.com/v1/archive
```

### API-secrets opslaan

Authenticatiesleutels worden opgeslagen in de Windows Credential Manager (niet in `.env`):

```python
import keyring
keyring.set_password('V1Eindwerk', 'solar_auth_key',   '<sleutel>')
keyring.set_password('V1Eindwerk', 'battery_auth_key', '<sleutel>')
```

Of via het hulpscript:
```bash
python setup_secrets.py
```

### EPEX-bronbestand

Plaats het handmatig aangeleverde Excel-bestand in `data/Source Data/epex.xlsx`.

Vereiste kolommen:

| Kolom | Formaat | Voorbeeld |
|---|---|---|
| `Date` | `DD/MM/YYYY` | `15/11/2024` |
| `Time` | `Xu` (uur, Belgische lokale tijd) | `0u` · `13u` · `23u` |
| `Euro` | float (€/MWh) | `82.45` |

---

## Gebruik

### Volledige datavoorbereiding in één aanroep

```python
from scripts.voorbereiding import voorbereiding

voorbereiding()                                        # alle stappen, incrementeel
voorbereiding(van='2025-01-01', tot='2025-03-31')      # specifieke periode
voorbereiding(stappen={'0g', '1'})                     # enkel EPEX + overall.csv
voorbereiding(force_epex=True, overschrijf_bat=True)   # alles herberekenen
```

Als script:
```bash
python scripts/voorbereiding.py
python scripts/voorbereiding.py --van 2025-01-01 --stappen 0g 1
```

| Stap | Module | Actie |
|---|---|---|
| `0a` | `solar_logs` | SolarLogs downloaden |
| `0b` | `battery` | Batterijdata downloaden |
| `0c` | `weather` | Weerdata + POA herberekenen |
| `0d` | `fluvius` | Fluvius CSV-exports verwerken |
| `0e` | `solarcharge` | EV-laadsessies verwerken |
| `0f` | `owndev` | OwnDev telegrammen verwerken |
| `0g` | `epex` + `epex_kwartier` | xlsx importeren + kwartierconversie |
| `1` | `overall` | Alle bronnen samenvoegen naar `overall.csv` |

### Volgorde bij eerste gebruik

```
1. .env aanmaken
2. API-secrets opslaan
3. epex.xlsx plaatsen in data/Source Data/
4. voorbereiding()  →  of data_voorbereiding.ipynb stap voor stap
5. kwartier_analyse.ipynb
6. tarief_vergelijking.ipynb
```

---

## Scripts

### `scripts/epex.py` — EPEX uurprijzen importeren

Leest `epex.xlsx` en schrijft `epex_be.csv`. Slimme bijwerkdetectie op basis van
bestandstijdstempels: import wordt overgeslagen als de cache actueel is.

DST-behandeling: `ambiguous='infer'` bij wintertijdovergang (25 uur),
`nonexistent='shift_forward'` bij zomertijdovergang (23 uur).

### `scripts/epex_kwartier.py` — Kubische spline

Converteert 24 uurprijzen naar 96 kwartierwaarden via een antiderivaat-preserverende
kubische spline. Mean-preservation is wiskundig gegarandeerd:

```
Stap 1  E[h] = som van p[0]…p[h-1]           (antiderivaat op uurgrenzen)
Stap 2  S(t) = CubicSpline door (h, E[h])     (not-a-knot randcondities)
Stap 3  q[k] = (S((k+1)·0.25) − S(k·0.25)) / 0.25

Bewijs:  Σ q[k] voor k=4h…4h+3
       = S(h+1) − S(h) = E[h+1] − E[h] = p[h]  ✓
```

### `scripts/overall.py` — Centrale samenvoeging

Combineert alle bronnen via left-joins op de Fluvius-kwartierdata als basis:

```
Fluvius → OwnDev → SolarLogs + Battery + Weather (op uur) → Solarcharge → overall.csv
```

### `scripts/owndev.py` — OwnDev P1 + SOFAR

Verwerkt seconde-telegrammen van de Raspberry Pi-logger. Elke seconde bevat
een P1-meting (afname/terugave kW) en een SOFAR Modbus-lezing
(register 525 = batterijvermogen, register 528 = SOC).

Batterij-responsanalyse via `analyseer_commando_respons()`: slaat de 5 seconden
na elk nieuw commando op en berekent de afwijking `bat_kw − commando_kw`.

### `scripts/weather.py` — Open-Meteo + pvlib

Haalt uurlijkse GHI/DNI/DHI-stralingsdata op via Open-Meteo en berekent de
instraling op het paneeloppervlak (POA) via het pvlib Hay-Davies-model:

- Azimut: 292,5° (WNW) — Helling: 35°
- POA = 0 bij zenithoek > 85° (zon onder de horizon)

---

## Tariefvergelijking — technische details

### Netkosten (Fluvius, Vilvoorde 2025)

- **Capaciteitstarief**: maandelijkse piek van de 15-minutenafname (min. 2,5 kW)
- **Variabele nettarieven**: afzonderlijk per kWh afname en injectie

### LP-batterijoptimalisatie (Scenario B)

Per dag worden 480 variabelen geoptimaliseerd over 96 kwartieren:

```
Minimaliseer:  Σ (koop_dyn[k] · import[k] − verkoop_dyn[k] · export[k])

Beperkingen:
  SOC[k] = SOC[k-1] + η_c · charge[k] − discharge[k] / η_d
  SOC ∈ [SOC_min, SOC_max]
  charge, discharge ∈ [0, P_max]
  import[k] = base_load[k] + charge[k] − discharge[k]
```

De SOC aan het einde van dag d wordt doorgegeven als begintoestand van dag d+1.

### Waarom lijkt dynamisch tarief goedkoper?

1. **Gemiddelde EPEX < vast tarief** — leveranciers bouwen marge in op vaste prijzen
2. **Negatieve EPEX-prijzen** — bij surplus hernieuwbare energie daalt de prijs tot
   nul of negatief; bij dynamisch profiteer je hiervan rechtstreeks
3. **Batterijoptimalisatie** — laden tijdens goedkope uren, ontladen tijdens dure uren
4. **Vaste maandkosten niet meegeteld** — dynamische contracten rekenen hogere vaste
   fees; die zijn niet opgenomen in de variabele kostenvergelijking
5. **Selectie-effect top-10** — de getoonde dagen zijn de extremen; het maandoverzicht
   geeft een vollediger beeld

---

## Streamlit-dashboard

```bash
streamlit run app.py
```

Opent op `http://localhost:8501`.
