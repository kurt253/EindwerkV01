# Energie Dashboard — Vilvoorde

Een lokaal Python-project voor het opvolgen, verwerken en analyseren van energieverbruik, zonnepanelen, thuisbatterij, EV-laden en gasafname van een Belgische woning in Vilvoorde. De data is afkomstig van vijf databronnen: een Fluvius digitale meter (P1-poort), een OwnDev Raspberry Pi-logger (P1 + SOFAR Modbus), de iLumen SolarLogs API, de iLuCharge laad­sessie-API en de Open-Meteo weerarchief-API.

---

## Projectdoelstelling

Het project heeft twee hoofddoelstellingen:

1. **Data­voorbereiding**: Alle brondata samenvoegen tot consistente tussenresultaten (CSV) die klaar zijn voor analyse. Dit gebeurt in `notebooks/data_voorbereiding.ipynb`.
2. **Batterij-respons­analyse**: De nauwkeurigheid meten waarmee de SOFAR ME3000SP batterij­omvormer SOFAR-commando's opvolgt — per commando­type, per seconde na het commando.

---

## Projectstructuur

```
V1Eindwerk/
│
├── app.py                            # Streamlit startpagina (streamlit run app.py)
├── setup_secrets.py                  # Eenmalig hulpscript om API-sleutels op te slaan
├── requirements.txt                  # Python-afhankelijkheden
├── .env                              # Paden, coördinaten en API-instellingen (niet in git)
│
├── config/
│   └── telegram_mapping.json         # Mapping van OBIS-codes en Modbus-registers
│                                     # naar leesbare kolomnamen (P1 + SOFAR)
│
├── scripts/                          # Verwerkings- en laadmodules per databron
│   ├── __init__.py
│   ├── config.py                     # Paden, secrets en instellingen laden vanuit .env
│   ├── solar_logs.py                 # iLumen API — uurlijkse zon- en netstroom
│   ├── battery.py                    # iLumen API — uurlijkse batterijdata (SOC, geladen, ontladen)
│   ├── fluvius.py                    # Fluvius CSV-export — kwartiertotalen digitale meter
│   ├── owndev.py                     # OwnDev Raspberry Pi — seconde-telegrammen P1 + SOFAR
│   ├── solarcharge.py                # iLuCharge API — EV laadsessies uitgespreid per kwartier
│   └── weather.py                    # Open-Meteo + pvlib — uurlijks weer en POA-instraling
│
├── notebooks/
│   └── data_voorbereiding.ipynb      # Hoofd-notebook: data inladen, verwerken en analyseren
│
├── Data/                             # Alle lokale data (niet in git via .gitignore)
│   ├── Source Data/
│   │   ├── SolarLogs/                # JSON per dag: YYYYMMDD - solar.json
│   │   ├── SolarBattery/             # JSON per dag: YYYYMMDD - solar.json
│   │   ├── OwnDev/                   # Telegrambestanden per uur + commando-CSV per dag
│   │   │   ├── YYYY-MM-DD/
│   │   │   │   ├── HH/
│   │   │   │   │   └── telegram_YYYY-MM-DD_HH-MM.txt
│   │   │   │   └── YYYY-MM-DD_commando.csv
│   │   ├── Fluvius/                  # Semikolon-gescheiden Fluvius-exports + outputbestand
│   │   ├── Solarcharge/              # iLuCharge CSV-exports
│   │   └── vilvoorde_zonneschijn.csv # Gegenereerd door weather.py (Open-Meteo + pvlib)
│   └── intermediate results/
│       ├── owndev_seconden.csv       # Verwerkte OwnDev seconde-tijdreeks
│       └── commando_respons.csv      # Commando-respons­analyse per nuttig commando
│
└── FYI/
    └── BatMgmtV3.py                  # Referentie: het Raspberry Pi-script dat de
                                      # commando-CSV's aanmaakt en de telegrammen schrijft
```

---

## Databronnen en scripts

### 1. SolarLogs API — `scripts/solar_logs.py`

| Eigenschap | Waarde |
|---|---|
| Endpoint | `SOLAR_API_URL` (in `.env`) |
| Authenticatie | `AUTH_key`-header, opgeslagen in Windows Credential Manager |
| Tijdresolutie | per uur |
| Data | injectie (kWh), afname (kWh), nettoteller |
| Lokale opslag | `Data/Source Data/SolarLogs/YYYYMMDD - solar.json` |
| Functies | `available_dates()`, `laad_dag(datum)`, `verwerk()` |

Het script downloadt dagbestanden van de iLumen SolarLogs API en slaat ze lokaal op als JSON. Bij heruitvoeren worden bestaande bestanden overgeslagen.

---

### 2. SolarBattery API — `scripts/battery.py`

| Eigenschap | Waarde |
|---|---|
| Endpoint | `BATTERY_API_URL` (in `.env`) |
| Authenticatie | `AUTH_key`-header, opgeslagen in Windows Credential Manager |
| Tijdresolutie | per uur |
| Data | `soc` (%), `charged` (kWh geladen), `decharged` (kWh ontladen), dagtotalen + kosten/opbrengst (€) |
| Lokale opslag | `Data/Source Data/SolarBattery/YYYYMMDD - solar.json` |
| Retry | automatisch tot 10 pogingen met 2,5 s pauze (API geeft soms leeg antwoord) |

---

### 3. Fluvius digitale meter — `scripts/fluvius.py`

| Eigenschap | Waarde |
|---|---|
| Bron | Handmatig geëxporteerde CSV's van de Fluvius-klantenportaal |
| Tijdresolutie | per kwartier (15 minuten) |
| Data | afname dag (kWh), afname nacht (kWh), injectie dag (kWh), injectie nacht (kWh) |
| Lokale opslag | `Data/Source Data/Fluvius/fluvius_kwartieren.csv` |

**Bronformaat:** De Fluvius-exports zijn semikolon-gescheiden bestanden met twee rijen per kwartier (één per register: "Afname Dag", "Afname Nacht", "Injectie Dag", "Injectie Nacht"). Het script pivoteert deze naar één brede rij per kwartier.

**Incrementeel bijwerken:** Het script leest de hoogste al verwerkte `kwartier`-tijdstempel uit het outputbestand en voegt alleen nieuwere kwartieren toe. Bestaande bestanden hoeven niet opnieuw verwerkt te worden.

---

### 4. OwnDev P1 + SOFAR — `scripts/owndev.py`

Dit is de meest uitgebreide module. Een OwnDev-apparaat (Raspberry Pi) logt élke seconde een P1-telegram van de Fluvius slimme meter gecombineerd met een Modbus-lezing van de SOFAR ME3000SP batterijomvormer.

#### 4a. Telegrambestanden

**Bestandsstructuur:**
```
Data/Source Data/OwnDev/YYYY-MM-DD/HH/telegram_YYYY-MM-DD_HH-MM.txt
```

Elk bestand bevat meerdere meetparen per seconde. Elk paar bestaat uit:

```
===== P1 TELEGRAM =====
1-0:1.7.0(XX.XXX*kW)      ← huidig verbruik van het net (afname)
1-0:2.7.0(XX.XXX*kW)      ← huidige terugave naar het net
!END P1

===== SOFAR ME3000SP =====
Metingsmoment: YYYY-MM-DD HH:MM:SS
Reg 525: NNNNN             ← batterijvermogen (signed int16, × 0.01 kW)
Reg 528: NN                ← State of Charge (%)
!END SOFAR
```

**Register 525:** positieve waarde = laden, negatieve waarde = ontladen. Het script converteert de unsigned 16-bit integer naar signed en berekent `bat_laden_kw` en `bat_ontladen_kw` als gescheiden kolommen (beide ≥ 0).

#### 4b. Commando-CSV's

De Raspberry Pi schrijft ook per dag een commando-logbestand:

```
Data/Source Data/OwnDev/YYYY-MM-DD/YYYY-MM-DD_commando.csv
Kolommen: sofar_action, timestamp, sofar_command_w
```

`sofar_command_w` is het gevraagde vermogen in Watt (NaN voor het commando "stoppen"). Gekende commando-types:

| sofar_action | Beschrijving | Teken commando_kw |
|---|---|---|
| `stoppen` | Batterij stopt — geen lading of ontlading | 0 kW |
| `laden tot voorziene level` | Laden op basis van een gepland doelvermogen | positief (+kW) |
| `laden door zon` | Laden op basis van actuele PV-productie | positief (+kW) |
| `ontladen tot voorziene level` | Ontladen op basis van gepland doelvermogen | negatief (−kW) |
| `overschot ontladen tot voorziene level` | Ontladen via PV-overschot | negatief (−kW) |

#### 4c. Verwerking en outputformaat

`owndev.verwerk()` leest alle telegrambestanden en schrijft het resultaat naar:

```
Data/intermediate results/owndev_seconden.csv
```

Kolommen van het outputbestand:

| Kolom | Type | Beschrijving |
|---|---|---|
| `tijdstip` | datetime | Seconde-precisie van de SOFAR-meting |
| `afname_kw` | float | Huidig verbruik van het net (kW) |
| `terugave_kw` | float | Huidige terugave naar het net (kW) |
| `bat_laden_kw` | float | Batterijvermogen laden (kW, ≥ 0) |
| `bat_ontladen_kw` | float | Batterijvermogen ontladen (kW, ≥ 0) |
| `soc` | int | State of Charge (%) |
| `sofar_action` | str | Actief SOFAR-commando op deze seconde |
| `commando_kw` | float | Gevraagd vermogen in kW (+laden, −ontladen, 0 stoppen) |

**Incrementeel bijwerken:** Bestanden waarvan de bestandsnaam-tijdstempel + 60 seconden ≤ de laatste al verwerkte tijdstempel zijn worden overgeslagen. Na het toevoegen van nieuwe seconden worden de commando-kolommen voor de **volledige** dataset opnieuw berekend (goedkope pure pandas-operatie).

#### 4d. Commando-toewijzingslogica

De commando-CSV en de seconde-tijdreeks worden samengevoegd via `pd.merge_asof` (achterwaartse koppeling):

1. Elk commando wordt gekoppeld aan de log-seconde op of net vóór het commando-tijdstip.
2. Is de tijdkloof tussen commando en log-seconde > 10 seconden (door een logging-pauze), dan wordt de actie ingesteld op `'Onbekend'`.
3. Op elke log-seconde die volgt na een gat van > 10 seconden in de logs zelf wordt de status gereset naar `'Onbekend'` totdat een nieuw commando volgt.
4. De commando-status wordt vervolgens voorwaarts ingevuld (forward-fill) over alle tussenliggende seconden.

#### 4e. Batterij-respons­analyse

`owndev.analyseer_commando_respons()` zoekt naar **nuttige commando's**: seconden waarop `commando_kw` verandert ten opzichte van de vorige waarde. Voor elk nuttig commando worden de **5 seconden erna** opgeslagen als brede rij:

```
Data/intermediate results/commando_respons.csv
```

Kolommen per seconde n = 1…5:

| Kolom | Beschrijving |
|---|---|
| `net_kw_sN` | Nettovermogen uit het net (afname − terugave, kW). Positief = afname. |
| `bat_kw_sN` | Batterijvermogen (laden − ontladen, kW). Positief = laden. |
| `afwijking_kw_sN` | `bat_kw_sN − commando_kw` — idealiter ≈ 0 |

Plus de eenmalige kolommen `soc` (op het moment van het commando) en `sofar_action`, `commando_kw`.

`owndev.afwijking_per_commando()` groepeert de respons­data per `(sofar_action, seconde)` en berekent de gemiddelde afwijking, maximale absolute afwijking en het aantal meetpunten.

---

### 5. Solarcharge EV-lading — `scripts/solarcharge.py`

| Eigenschap | Waarde |
|---|---|
| Bron | iLuCharge CSV-exports |
| Tijdresolutie | per kwartier (15 minuten, uitgespreid) |
| Data | Laadsessies met start, einde, gebruiker en energie (kWh) |
| Lokale opslag | `Data/Source Data/Solarcharge/solarcharge_sessies.csv` |

Het script spreidt elke laadsessie uit over alle kwartieren die ze overlapt, op basis van een constant verondersteld laadvermogen (`sessie_kWh / sessie_duur_uur`). De overlappende energie per kwartier wordt berekend als `vermogen_kW × overlap_uur`.

---

### 6. Open-Meteo + pvlib — `scripts/weather.py`

| Eigenschap | Waarde |
|---|---|
| Endpoint | `https://archive-api.open-meteo.com/v1/archive` |
| Authenticatie | geen — gratis publieke API |
| Tijdresolutie | per uur |
| Data | GHI, DNI, DHI (W/m²), zonneschijnduur (s/uur) |
| POA-berekening | pvlib Hay-Davies model op basis van `PANEL_TILT` en `PANEL_AZIMUTH` |
| Lokale opslag | `WEATHER_CSV` (pad in `.env`) |

De instraling op het **paneeloppervlak** (Plane of Array, POA) wordt lokaal berekend via `pvlib`. De POA wordt op 0 gezet wanneer de zenithoek van de zon > 85° (zon dicht bij of onder de horizon).

---

## Notebook: `notebooks/data_voorbereiding.ipynb`

Het hoofd-notebook verwerkt en analyseert alle databronnen in vijf secties:

| Sectie | Inhoud |
|---|---|
| **1. Beschikbare data per bron** | Overzicht van periodes en aantallen rijen per bron |
| **2. OwnDev — telegrammen verwerken** | Aanroep van `owndev.verwerk()` — incrementeel bijwerken van `owndev_seconden.csv` |
| **3. OwnDev — nuttige commando's** | Aanroep van `owndev.analyseer_commando_respons()` — bouw en opslaan van `commando_respons.csv` |
| **4. Gemiddelde en maximale afwijking** | Gegroepeerde staafgrafiek: gemiddelde en maximale `afwijking_kw` per commando-type per seconde |
| **5. Outliers in de afwijking** | Strip-plot met outlier-markering (drempel = gemiddelde ± 2 × std) + overzichtstabel |

---

## Installatie

### 1. Python-omgeving opzetten

De applicatie vereist **Python 3.10 of hoger** (vanwege `X | Y` type-annotaties).

```bash
pip install -r requirements.txt
```

Geïnstalleerde pakketten:

| Pakket | Doel |
|---|---|
| `streamlit` | Interactief web-dashboard |
| `pandas` | DataFrames, CSV-verwerking, tijdreeksen |
| `matplotlib` | Grafieken in de notebook |
| `requests` | HTTP-aanroepen naar API's |
| `python-dotenv` | Inlezen van `.env`-bestand |
| `keyring` | Ophalen van secrets uit Windows Credential Manager |
| `openpyxl` | Lezen van Excel-bestanden (`.xlsx`) |
| `pvlib` | POA-instraling berekenen op basis van paneeloriëntatie |

### 2. `.env` configureren

Maak een `.env`-bestand in de projectroot (of kopieer het template) en pas de paden aan:

```dotenv
# ── Paden naar lokale dataopslag ──────────────────────────────────────────
SOLAR_DIR=C:\pad\naar\Data\Source Data\SolarLogs
BATTERY_DIR=C:\pad\naar\Data\Source Data\SolarBattery
WEATHER_CSV=C:\pad\naar\Data\Source Data\vilvoorde_zonneschijn.csv

# ── Installatie-ID's (geen secrets — staan in .env) ───────────────────────
SOLAR_ADRESID=<jouw adresid>
BATTERY_SN=<serienummer batterij>

# ── GPS-coördinaten voor weerdata en pvlib-berekeningen ───────────────────
LAT=50.9281
LON=4.4191

# ── Paneeloriëntatie ──────────────────────────────────────────────────────
PANEL_TILT=35           # Helling in graden (0=horizontaal, 90=verticaal)
PANEL_AZIMUTH=292.5     # Kompasbearing: 0=Noord, 90=Oost, 180=Zuid, 270=West

# ── API-eindpunten ────────────────────────────────────────────────────────
SOLAR_API_URL=https://www.solarlogs.be/API/dm_api.php
BATTERY_API_URL=https://www.solarlogs.be/API/ilucharge_api.php
WEATHER_API_URL=https://archive-api.open-meteo.com/v1/archive
```

### 3. API-secrets opslaan in Windows Credential Manager

De authenticatiesleutels voor de SolarLogs en SolarBattery API worden **niet** in `.env` opgeslagen maar veilig bewaard in de Windows Credential Manager via `keyring`. Voer dit **eenmalig** uit:

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

`scripts/config.py` haalt de secrets automatisch op via `keyring.get_password('V1Eindwerk', naam)` bij elke API-aanroep. Als een secret ontbreekt, gooit het script een duidelijke `RuntimeError` met instructies.

---

## Applicatie starten

```bash
streamlit run app.py
```

De app opent automatisch in de standaardbrowser op `http://localhost:8501`.

---

## Paneeloriëntatie en POA-berekening

De zonnepanelen zijn georiënteerd op **WNW (West-Noord-West)** met een helling van **35°**:

- `PANEL_AZIMUTH = 292.5°` — kompasbearing, 0 = Noord, kloksgewijs
- `PANEL_TILT = 35°` — helling ten opzichte van het horizontale vlak

`pvlib` gebruikt dezelfde azimutconventie (0 = Noord, 90 = Oost, 180 = Zuid, 270 = West) als de kompasbearing in `.env`, dus geen conversie nodig.

Het **Hay-Davies**-model wordt gebruikt voor de diffuse stralingscomponent. Dit model presteert beter dan het isotropisch model voor niet-zuidgerichte en hellende vlakken omdat het rekening houdt met de anisotrope hemeldistributie van diffuus licht.

De POA-instraling wordt op 0 gezet wanneer de zeniths­hoek van de zon groter is dan 85° (zon dicht bij of onder de horizon), omdat het model daar numeriek onbetrouwbaar wordt.

---

## OwnDev — technische achtergrond

De OwnDev-logger is een Raspberry Pi die het Python-script `FYI/BatMgmtV3.py` uitvoert. Dit script:

1. Leest elke seconde een P1-telegram van de slimme meter via de seriële poort.
2. Leest gelijktijdig de SOFAR ME3000SP batterijomvormer via Modbus TCP (register 525 = batterijvermogen, register 528 = SOC).
3. Schrijft elk paar naar het telegrambestand van de lopende minuut.
4. Stuurt via een SOFAR Modbus-schrijfopdracht het gevraagde lad/ontlaad-commando op basis van de actuele situatie (PV-productie, netprijzen, geplande levels).
5. Logt elk nieuw commando naar de dagelijkse `YYYY-MM-DD_commando.csv`.

De telegrambestanden zijn de ruwe logging-output; de commando-CSV's zijn het besturing­logboek. `scripts/owndev.py` combineert beide tot een geïntegreerde seconde-tijdreeks.

---

## Lokale ontwikkeling

- Alle lokale bestandspaden staan in `.env` — het project werkt op elke machine zolang `.env` correct is ingesteld.
- `scripts/` is een Python-package (`__init__.py` aanwezig).
- De notebook gebruikt `sys.path.insert(0, "..")` om de `scripts/`-map te vinden vanuit de `notebooks/`-submap.
- Streamlit laadt `pages/` automatisch als subpagina's op basis van bestandsnaam en volgorde.
- `.gitignore` sluit `Data/` en alle notebooks uit behalve `notebooks/data_voorbereiding.ipynb`.
