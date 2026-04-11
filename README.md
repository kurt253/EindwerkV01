# Energie Dashboard — Vilvoorde

Lokaal Python-project voor het opvolgen, verwerken en analyseren van energieverbruik,
zonnepanelen, thuisbatterij, EV-laden en gasafname van een Belgische woning in Vilvoorde.

Data is afkomstig van vijf bronnen: Fluvius digitale meter (P1-poort), OwnDev
Raspberry Pi-logger (P1 + SOFAR Modbus), iLumen SolarLogs API, iLuCharge laadsessie-API
en de Open-Meteo weerarchief-API.

---

## Inhoudstafel

1. [Projectdoelstelling](#projectdoelstelling)
2. [Projectstructuur](#projectstructuur)
3. [Installatie](#installatie)
4. [Databronnen en scripts](#databronnen-en-scripts)
5. [Notebooks](#notebooks)
6. [Technische achtergrond](#technische-achtergrond)

---

## Projectdoelstelling

Het project heeft twee hoofddoelstellingen:

1. **Datavoorbereiding** — Alle brondata samenvoegen tot consistente tussenresultaten (CSV)
   die klaar zijn voor analyse. Dit gebeurt in `notebooks/data_voorbereiding.ipynb`.

2. **Analyse en optimalisatie** — Batterij-responsanalyse (nauwkeurigheid SOFAR ME3000SP
   ten opzichte van commando's), kwartieranalyse van verbruik en PV-productie, en een
   vergelijking van vast DATS24-tarief versus dynamisch EPEX-tarief met optionele
   LP-batterijoptimalisatie.

---

## Projectstructuur

```
V1Eindwerk/
│
├── app.py                              # Streamlit startpagina (streamlit run app.py)
├── setup_secrets.py                    # Eenmalig hulpscript om API-sleutels op te slaan
├── requirements.txt                    # Python-afhankelijkheden (pip)
├── environment.yml                     # Conda-omgevingsbestand
├── .env                                # Paden, coördinaten en API-instellingen (niet in git)
│
├── config/
│   └── telegram_mapping.json           # Mapping OBIS-codes + Modbus-registers naar kolomnamen
│
├── scripts/                            # Verwerkings- en laadmodules per databron
│   ├── __init__.py
│   ├── config.py                       # Paden, secrets en instellingen vanuit .env
│   ├── solar_logs.py                   # iLumen API — uurlijkse zon- en netstroom
│   ├── battery.py                      # iLumen API — uurlijkse batterijdata (SOC, in/uit)
│   ├── fluvius.py                      # Fluvius CSV-export — kwartiertotalen digitale meter
│   ├── owndev.py                       # OwnDev Raspberry Pi — seconde-telegrammen P1 + SOFAR
│   ├── solarcharge.py                  # iLuCharge API — EV-laadsessies per kwartier
│   ├── weather.py                      # Open-Meteo + pvlib — weerdata en POA-instraling
│   ├── overall.py                      # Samenvoegen alle bronnen tot overall.csv
│   ├── epex.py                         # Leest uurlijkse EPEX SPOT Belgium dag-vooruit-prijzen
│   └── epex_kwartier.py                # Kubische spline — uurprijzen → kwartierwaarden
│
├── notebooks/
│   ├── data_voorbereiding.ipynb        # Alle bronnen inladen + EPEX-conversie + batterijrespons
│   ├── kwartier_analyse.ipynb          # Verbruik, weekpatroon, PV-zonrelatie
│   └── tarief_vergelijking.ipynb       # Vast (DATS24) vs dynamisch (EPEX) + LP-optimalisatie
│
├── data/                               # Alle lokale data (niet in git via .gitignore)
│   ├── Source Data/
│   │   ├── SolarLogs/                  # JSON per dag: YYYYMMDD - solar.json
│   │   ├── SolarBattery/               # JSON per dag: YYYYMMDD - solar.json
│   │   ├── OwnDev/                     # Telegrambestanden per uur + commando-CSV per dag
│   │   │   └── YYYY-MM-DD/
│   │   │       ├── HH/
│   │   │       │   └── telegram_YYYY-MM-DD_HH-MM.txt
│   │   │       └── YYYY-MM-DD_commando.csv
│   │   ├── Fluvius/                    # Semikolon-gescheiden Fluvius-exports
│   │   ├── Solarcharge/                # iLuCharge CSV-exports
│   │   └── vilvoorde_zonneschijn.csv   # Gegenereerd door weather.py
│   ├── intermediate results/
│   │   ├── owndev_seconden.csv         # Verwerkte OwnDev seconde-tijdreeks
│   │   ├── commando_respons.csv        # Commando-responsanalyse per nuttig commando
│   │   ├── epex_be.csv                 # EPEX SPOT Belgium uurprijzen (extern aangeleverd)
│   │   └── epex_kwartieren.csv         # EPEX kwartierwaarden via kubische spline
│   └── Final/
│       ├── overall.csv                 # Alle bronnen per kwartier (ruwe combinatie)
│       ├── overall_verrijkt.csv        # overall.csv + afgeleide verbruikskolommen
│       ├── weekpatroon.csv             # Gem. verbruik per kwartier per weekdag (96 × 7)
│       ├── dag_zon_analyse.csv         # Dagelijkse injectie + zonneschijn + POA
│       └── dag_zon_met_verhoudingen.csv # Subset met injectie/zon-verhoudingen (trainingsdata)
│
└── FYI/
    └── BatMgmtV3.py                    # Referentie: Raspberry Pi-script dat commando-CSV's
                                        # aanmaakt en telegrammen schrijft
```

---

## Installatie

### 1. Python-omgeving opzetten

**Optie A — pip:**

```bash
pip install -r requirements.txt
```

**Optie B — conda:**

```bash
conda env create -f environment.yml
conda activate v1eindwerk
```

Vereist Python 3.10 of hoger (vanwege `X | Y` type-annotaties).

| Pakket | Doel |
|---|---|
| `pandas` | DataFrames, CSV-verwerking, tijdreeksen |
| `numpy` | Numerieke berekeningen (spline-interpolatie, LP) |
| `scipy` | Kubische spline-interpolatie + lineair programmeren (LP-optimalisatie batterij) |
| `pvlib` | POA-instraling berekenen op basis van paneeloriëntatie |
| `matplotlib` | Statische grafieken in de notebooks |
| `plotly` | Interactieve grafieken in `tarief_vergelijking.ipynb` |
| `ipywidgets` | Datumkiezer-widget in `tarief_vergelijking.ipynb` |
| `jupyter` | Notebook-runtime |
| `streamlit` | Interactief web-dashboard |
| `requests` | HTTP-aanroepen naar API's |
| `openpyxl` | Lezen van Excel-bestanden |
| `python-dotenv` | Inlezen van `.env`-bestand |
| `keyring` | Ophalen van secrets uit Windows Credential Manager |

### 2. `.env` configureren

Maak een `.env`-bestand in de projectroot en pas de paden aan:

```dotenv
# ── Paden naar lokale dataopslag ──────────────────────────────────────────
SOLAR_DIR=C:\pad\naar\Data\Source Data\SolarLogs
BATTERY_DIR=C:\pad\naar\Data\Source Data\SolarBattery
WEATHER_CSV=C:\pad\naar\Data\Source Data\vilvoorde_zonneschijn.csv

# ── Installatie-ID's (geen secrets) ───────────────────────────────────────
SOLAR_ADRESID=<jouw adresid>
BATTERY_SN=<serienummer batterij>

# ── GPS-coördinaten voor weerdata en pvlib-berekeningen ───────────────────
LAT=50.9281
LON=4.4191

# ── Paneeloriëntatie ──────────────────────────────────────────────────────
PANEL_TILT=35           # Helling in graden (0=horizontaal, 90=verticaal)
PANEL_AZIMUTH=292.5     # 0=Noord, 90=Oost, 180=Zuid, 270=West

# ── API-eindpunten ────────────────────────────────────────────────────────
SOLAR_API_URL=https://www.solarlogs.be/API/dm_api.php
BATTERY_API_URL=https://www.solarlogs.be/API/ilucharge_api.php
WEATHER_API_URL=https://archive-api.open-meteo.com/v1/archive
```

### 3. API-secrets opslaan in Windows Credential Manager

Authenticatiesleutels worden **niet** in `.env` opgeslagen maar veilig bewaard
in de Windows Credential Manager via `keyring`. Voer dit **eenmalig** uit:

```python
python -c "
import keyring
keyring.set_password('V1Eindwerk', 'solar_auth_key',   '<jouw solar sleutel>')
keyring.set_password('V1Eindwerk', 'battery_auth_key', '<jouw battery sleutel>')
"
```

Of gebruik het meegeleverde hulpscript:

```bash
python setup_secrets.py
```

`scripts/config.py` haalt secrets automatisch op via `keyring.get_password('V1Eindwerk', naam)`
bij elke API-aanroep. Als een secret ontbreekt geeft het script een duidelijke `RuntimeError`.

### 4. Aanbevolen volgorde bij eerste gebruik

```
1. Pas .env aan (paden + coördinaten)
2. Sla API-secrets op (stap 3)
3. notebooks/data_voorbereiding.ipynb
       sectie 0a–0f  →  SolarLogs, Battery, Fluvius, OwnDev, Solarcharge, Weather
       sectie 0g     →  EPEX kwartierconversie (epex_be.csv → epex_kwartieren.csv)
4. notebooks/kwartier_analyse.ipynb    →  verbruik, weekpatroon, PV-analyse
5. notebooks/tarief_vergelijking.ipynb →  tariefvergelijking + LP-optimalisatie
```

**Opmerking:** `epex_be.csv` (uurlijkse EPEX-prijzen) moet extern aangeleverd worden
en in `data/intermediate results/` geplaatst worden vóór stap 3.

---

## Databronnen en scripts

### `scripts/solar_logs.py` — SolarLogs API

| Eigenschap | Waarde |
|---|---|
| Endpoint | `SOLAR_API_URL` (in `.env`) |
| Authenticatie | `solar_auth_key` uit Windows Credential Manager |
| Tijdresolutie | per uur |
| Data | injectie (kWh), afname (kWh), nettoteller |
| Lokale opslag | `Data/Source Data/SolarLogs/YYYYMMDD - solar.json` |
| Functies | `available_dates()`, `laad_dag(datum)`, `verwerk()` |

Het script downloadt dagbestanden en slaat ze lokaal op als JSON.
Bij heruitvoeren worden bestaande bestanden overgeslagen.

---

### `scripts/battery.py` — SolarBattery API

| Eigenschap | Waarde |
|---|---|
| Endpoint | `BATTERY_API_URL` (in `.env`) |
| Authenticatie | `battery_auth_key` uit Windows Credential Manager |
| Tijdresolutie | per uur |
| Data | `soc` (%), `charged` (kWh), `decharged` (kWh), dagtotalen + kosten/opbrengst (€) |
| Lokale opslag | `Data/Source Data/SolarBattery/YYYYMMDD - solar.json` |
| Retry | automatisch tot 10 pogingen met 2,5 s pauze (API geeft soms leeg antwoord) |

---

### `scripts/fluvius.py` — Fluvius digitale meter

| Eigenschap | Waarde |
|---|---|
| Bron | Handmatig geëxporteerde CSV's van het Fluvius-klantenportaal |
| Tijdresolutie | per kwartier (15 minuten) |
| Data | afname dag (kWh), afname nacht (kWh), injectie dag (kWh), injectie nacht (kWh) |
| Lokale opslag | `Data/Source Data/Fluvius/fluvius_kwartieren.csv` |

**Bronformaat:** Semikolon-gescheiden bestanden met twee rijen per kwartier
(één per register: "Afname Dag", "Afname Nacht", "Injectie Dag", "Injectie Nacht").
Het script pivoteert deze naar één brede rij per kwartier.

**Incrementeel bijwerken:** Enkel kwartieren na de hoogste al verwerkte tijdstempel
worden toegevoegd.

---

### `scripts/owndev.py` — OwnDev P1 + SOFAR Modbus

De meest uitgebreide module. Een OwnDev-apparaat (Raspberry Pi) logt elke seconde
een P1-telegram van de Fluvius slimme meter gecombineerd met een Modbus-lezing
van de SOFAR ME3000SP batterijomvormer.

#### Bestandsstructuur telegrammen

```
Data/Source Data/OwnDev/YYYY-MM-DD/HH/telegram_YYYY-MM-DD_HH-MM.txt
```

Elk bestand bevat meerdere meetparen per seconde. Elk paar:

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

Register 525: positief = laden, negatief = ontladen. Het script converteert
de unsigned 16-bit integer naar signed en splitst in `bat_laden_kw` en
`bat_ontladen_kw` (beide ≥ 0).

#### Commando-CSV's

```
Data/Source Data/OwnDev/YYYY-MM-DD/YYYY-MM-DD_commando.csv
Kolommen: sofar_action, timestamp, sofar_command_w
```

| sofar_action | Beschrijving | Teken commando_kw |
|---|---|---|
| `stoppen` | Batterij stopt | 0 kW |
| `laden tot voorziene level` | Laden op gepland doelvermogen | positief |
| `laden door zon` | Laden op basis van PV-productie | positief |
| `ontladen tot voorziene level` | Ontladen op gepland doelvermogen | negatief |
| `overschot ontladen tot voorziene level` | Ontladen via PV-overschot | negatief |

#### Uitvoerkolommen `owndev_seconden.csv`

| Kolom | Type | Beschrijving |
|---|---|---|
| `tijdstip` | datetime | Seconde-precisie van de SOFAR-meting |
| `afname_kw` | float | Huidig verbruik van het net (kW) |
| `terugave_kw` | float | Huidige terugave naar het net (kW) |
| `bat_laden_kw` | float | Batterijvermogen laden (kW, ≥ 0) |
| `bat_ontladen_kw` | float | Batterijvermogen ontladen (kW, ≥ 0) |
| `soc` | int | State of Charge (%) |
| `sofar_action` | str | Actief SOFAR-commando op deze seconde |
| `commando_kw` | float | Gevraagd vermogen (+laden, −ontladen, 0 stoppen) |

**Incrementeel bijwerken:** Bestanden waarvan tijdstempel + 60 s ≤ laatste verwerkte
tijdstempel worden overgeslagen.

#### Commando-toewijzingslogica

1. Commando's worden gekoppeld via `pd.merge_asof` (achterwaartse koppeling).
2. Tijdkloof > 10 s tussen commando en log-seconde → actie = `'Onbekend'`.
3. Na een loggingpauze > 10 s wordt status gereset tot een nieuw commando volgt.
4. Status wordt daarna voorwaarts ingevuld over alle tussenliggende seconden.

#### Batterij-responsanalyse

`owndev.analyseer_commando_respons()` detecteert **nuttige commando's**
(wijziging in `commando_kw`) en slaat de 5 seconden na elk commando op
als brede rij in `commando_respons.csv`:

| Kolom | Beschrijving |
|---|---|
| `net_kw_sN` | Nettovermogen (afname − terugave, kW). N = 1…5. |
| `bat_kw_sN` | Batterijvermogen (laden − ontladen, kW). Positief = laden. |
| `afwijking_kw_sN` | `bat_kw_sN − commando_kw` — idealiter ≈ 0 |
| `soc` | SOC (%) op het moment van het commando |
| `sofar_action` | Commandotype |
| `commando_kw` | Gevraagd vermogen (kW) |

`owndev.afwijking_per_commando()` groepeert per `(sofar_action, seconde)` en
berekent de gemiddelde afwijking, maximale absolute afwijking en het aantal punten.

---

### `scripts/solarcharge.py` — EV-lading (iLuCharge)

| Eigenschap | Waarde |
|---|---|
| Bron | iLuCharge CSV-exports |
| Tijdresolutie | per kwartier (uitgespreid uit sessiedata) |
| Data | Laadsessies met start, einde, gebruiker en energie (kWh) |
| Lokale opslag | `Data/Source Data/Solarcharge/solarcharge_sessies.csv` |

Elke laadsessie wordt uitgespreid over alle overlappende kwartieren via een
constant verondersteld laadvermogen (`sessie_kWh / sessie_duur_uur`).

---

### `scripts/weather.py` — Open-Meteo + pvlib

| Eigenschap | Waarde |
|---|---|
| Endpoint | `https://archive-api.open-meteo.com/v1/archive` |
| Authenticatie | geen — gratis publieke API |
| Tijdresolutie | per uur |
| Data | GHI, DNI, DHI (W/m²), zonneschijnduur (s/uur) |
| POA-berekening | pvlib Hay-Davies model op basis van `PANEL_TILT` en `PANEL_AZIMUTH` |
| Lokale opslag | `WEATHER_CSV` (pad in `.env`) |

De instraling op het paneeloppervlak (Plane of Array, POA) wordt lokaal berekend
via `pvlib`. De POA wordt op 0 gezet wanneer de zenithoek > 85°
(zon dicht bij of onder de horizon).

**Paneeloriëntatie (Vilvoorde):**
- `PANEL_AZIMUTH = 292,5°` — WNW (West-Noord-West)
- `PANEL_TILT = 35°` — helling ten opzichte van horizontaal

Het **Hay-Davies**-model wordt gebruikt voor de diffuse stralingscomponent.
Dit model presteert beter dan het isotropisch model voor niet-zuidgerichte
vlakken omdat het rekening houdt met de anisotrope hemeldistributie.

---

### `scripts/epex.py` — EPEX SPOT Belgium uurprijzen

| Eigenschap | Waarde |
|---|---|
| Bron | `data/intermediate results/epex_be.csv` (extern aangeleverd) |
| Tijdresolutie | per uur (dag-vooruit-prijzen) |
| Data | Dag-vooruit-prijs voor België (€/MWh) |
| Functies | `load()` |

Het script leest de uurlijkse EPEX SPOT Belgium dag-vooruit-prijzen in
vanuit het lokale tussenresultaatbestand. `epex_be.csv` moet aanwezig zijn
vóór de kwartierconversie gestart wordt.

---

### `scripts/epex_kwartier.py` — Kwartierconversie via kubische spline

| Eigenschap | Waarde |
|---|---|
| Invoer | `data/intermediate results/epex_be.csv` (uurprijzen) |
| Uitvoer | `data/intermediate results/epex_kwartieren.csv` (kwartierwaarden) |
| Methode | Antiderivaat-preserverende kubische spline |
| Functies | `converteer(force=False)`, `laad()`, `uur_naar_kwartier(uurprijzen)` |

#### Wiskundige omzettingsformule

De EPEX dag-vooruit-markt handelt in uurblokken: prijs `p[h]` geldt voor het
volledige uur `h`. Om 24 uurprijzen om te zetten naar 96 kwartierwaarden worden
drie stappen gevolgd.

**Stap 1 — Antiderivaat op uurgrenzen**

Definieer de cumulatieve energiesom `E` op de 25 grenzen van de 24 uurblokken:

```
E[0] = 0
E[h] = p[0] + p[1] + … + p[h-1]   voor h = 1 … 24
```

`E[h+1] − E[h] = p[h]` : de integrale van de prijsfunctie over uur `h` is de uurprijs.

**Stap 2 — Kubische spline S(t)**

Een kubische spline met `not-a-knot`-randcondities (scipy `CubicSpline`) wordt
aangepast door de 25 punten `(t, E[t])`. De spline is C²-continu, wat zorgt
voor een vloeiende overgang tussen opeenvolgende uren.

**Stap 3 — Kwartierprijs als integraalgemiddelde**

Kwartier `k` beslaat `[k·Δt, (k+1)·Δt]` met `Δt = 0,25 uur`:

```
q[k] = ( S((k+1)·Δt) − S(k·Δt) ) / Δt
```

**Bewijs van mean-preservation (energiebehoud):**

```
Σ q[k] voor k = 4h … 4h+3
  = (S(h+1) − S(h)) / 0.25 × 0.25   ← telescopische som
  = S(h+1) − S(h)
  = E[h+1] − E[h]
  = p[h]
```

Het gemiddelde van de 4 kwartierwaarden per uur is exact gelijk aan de uurprijs.
Energiebehoud is wiskundig gegarandeerd.

**Slimme bijwerkdetectie:** `converteer()` vergelijkt de bestandstijdstempels
van `epex_be.csv` en `epex_kwartieren.csv`. Conversie wordt alleen uitgevoerd
als het kwartierbestand ontbreekt of verouderd is.

**Zomertijd/wintertijd:**
- 23-uurse dag (zomertijd): uur 2 wordt gedupliceerd voor continuïteit.
- 25-uurse dag (wintertijd): het dubbele uur wordt verwijderd.

---

### `scripts/overall.py` — Centrale samenvoeging

`overall.py` combineert alle databronnen tot één kwartierbestand.
Het gebruikt de **Fluvius-data als basis** en verrijkt die met OwnDev,
SolarLogs, Battery, Solarcharge en weerdata via left-joins.

#### Gegevensstroom

```
Fluvius (basis) → afname_kwh, injectie_kwh, tarief (dag/nacht)
    ↓ left-join op kwartier
OwnDev → bat_laden_kw, bat_ontladen_kw, afname_kw, terugave_kw, soc_begin, soc_eind
    ↓ left-join op floor(kwartier, uur)
SolarLogs → sl_afname_kwh, sl_injectie_kwh, sl_productie_kwh
Battery   → bat_geladen_kwh, bat_ontladen_kwh, bat_soc_uur
Weather   → weer_poa_w_m2, weer_ghi_w_m2, weer_zon_min
    ↓ left-join op kwartier
Solarcharge → ev_energie_kwh, ev_vermogen_kw
    ↓
data/Final/overall.csv
```

Kwartieren zonder data van een bron krijgen `NaN` in de betreffende kolommen.

#### Tariefkolom

Per kwartier wordt bepaald of dag- of nachttarief actief was op basis van de
Fluvius-meting: als `afname_dag > 0` of `injectie_dag > 0` is het dagtarief,
anders nachttarief.

#### Gebruik

```python
from scripts.overall import bouw

df, pad = bouw()
df, pad = bouw(output_file=Path("mijn_pad.csv"))
```

---

## Notebooks

### `notebooks/data_voorbereiding.ipynb`

| Sectie | Inhoud |
|---|---|
| **0a–0f. Data ophalen** | Aanroepen van alle fetch-functies per bron (SolarLogs, Battery, Fluvius, OwnDev, Solarcharge, Weather) |
| **0g. EPEX kwartierconversie** | Uurprijzen uit `epex_be.csv` omzetten naar kwartierwaarden via kubische spline (`epex_kwartier.converteer`); verificatie van mean-preservation voor de eerste 5 uren |
| **1. Beschikbare data per bron** | Overzicht van periodes en aantallen rijen per bron |
| **2. OwnDev — telegrammen verwerken** | `owndev.verwerk()` — incrementeel bijwerken van `owndev_seconden.csv` |
| **3. OwnDev — nuttige commando's** | `owndev.analyseer_commando_respons()` — bouw en opslaan van `commando_respons.csv` |
| **4. Gemiddelde en maximale afwijking** | Gegroepeerde staafgrafiek: gemiddelde en maximale `afwijking_kw` per commando-type per seconde |
| **5. Outliers in de afwijking** | Strip-plot met outlier-markering (drempel = gemiddelde ± 2 × std) + overzichtstabel |

---

### `notebooks/kwartier_analyse.ipynb`

| Sectie | Inhoud | Outputbestand |
|---|---|---|
| **1. Bouw kwartierbestand** | `overall.bouw()` — maakt `overall.csv` | `data/Final/overall.csv` |
| **2. Structuur en statistieken** | Periode, tariefsplitsing, describe-tabel | — |
| **3. Beschikbare data per bron** | Meetdagen per bron, zonnedagen | — |
| **4a. Verbruiksberekening** | Energiebalans per kwartier, gecorrigeerd voor EV, zon en batterij | `data/Final/overall_verrijkt.csv` |
| **4b. Weekpatroon** | Gemiddeld verbruik per kwartier per weekdag (heatmap + lijnplot) | `data/Final/weekpatroon.csv` |
| **4c. Zon-injectieanalyse** | Correlatie POA/zonneschijn met injectie, regressie en scatterplots | `data/Final/dag_zon_analyse.csv`, `dag_zon_met_verhoudingen.csv` |
| **Conclusies** | Analytische samenvatting | — |

#### Verbruiksformule

Het gecorrigeerde huisverbruik per kwartier:

```
verbruik_kwh = afname_kwh
             + bat_ontladen_kwh     (batterij levert energie aan huis)
             - injectie_kwh         (zonneoverschot naar net)
             - ev_kwh               (wagenlading is geen huisverbruik)
             - bat_laden_kwh        (batterijlading is geen huisverbruik)
```

OwnDev-vermogens (kW) worden omgezet naar kWh via `× 0,25` (kwartier = ¼ uur).
Als OwnDev-data ontbreekt, wordt teruggevallen op iLumen-uurwaarden (`÷ 4`).

#### Weekpatroon

Door te groeperen op **(dag van de week, kwartier van de dag)** ontstaat een
gemiddeld dagprofiel per weekdag (96 × 7 = 672 gemiddelden). Dit profiel dient
als basisfeature voor verbruiksvoorspellingsmodellen.

#### Outputbestanden `data/Final/`

| Bestand | Beschrijving |
|---|---|
| `overall.csv` | Alle bronnen per kwartier, ruwe join |
| `overall_verrijkt.csv` | Idem + `ev_kwh`, `bat_*_kwh_kw`, `verbruik_kwh` |
| `weekpatroon.csv` | Gem. verbruik per kwartier per weekdag (96 rijen) |
| `dag_zon_analyse.csv` | Dagelijkse injectie + zonneschijn + POA |
| `dag_zon_met_verhoudingen.csv` | Subset met berekende verhoudingen (zonnige dagen) |

---

### `notebooks/tarief_vergelijking.ipynb`

Vergelijkt de totale elektriciteitskost voor twee tariefscenario's op basis
van de Fluvius kwartierdata en de EPEX dag-vooruit-prijzen.

#### Tariefparameters

**DATS24 vast tarief:**
- Dag: 0,1479 €/kWh
- Nacht: 0,1240 €/kWh
- Injectie: 0,0655 €/kWh

**Dynamisch EPEX-tarief:**
- Afname: EPEX-prijs + 0,0140 €/kWh opslag
- Injectie: EPEX-prijs − 0,005 €/kWh korting

**Netkosten (Fluvius, identiek voor beide scenario's):**
- Capaciteitstarief: maandelijks op basis van de 15-minutenpiek (min. 2,5 kW)
- Variabele nettarieven per kWh afname/injectie

#### Secties

| Sectie | Inhoud |
|---|---|
| **1. Tariefconfiguratie** | DATS24 parameters, Fluvius netkosten, dynamisch EPEX-tarief, batterijparameters |
| **2. Data laden** | `overall.csv` + kwartier-EPEX-prijzen met automatische bijwerkdetectie |
| **3. Kostenfuncties** | Variabele netkosten, capaciteitstarief, energiekostfuncties |
| **4. Scenario A — zonder batterij** | Reconstructie basisbelasting, kostenvergelijking vast vs dynamisch, maandtabel + staafdiagram |
| **5. Scenario B — LP-optimalisatie** | Lineair programma (scipy `linprog`) optimaliseert batterijdispatch om energiekost te minimaliseren; SOC-continuïteit over dagen |
| **6. Interactieve dagplot** | Plotly-figuur met ipywidgets DatePicker: EPEX-prijs, netbelasting voor/na optimalisatie, SOC-verloop |
| **7. Samenvatting** | Totaalbesparing dynamisch vs vast + batterijbesparing (€ en %) |

#### LP-optimalisatie (Scenario B)

Per dag worden 480 variabelen geoptimaliseerd (laden, ontladen, SOC, import,
export × 96 kwartieren) met 192 gelijkheidsbeperkingen. De SOC aan het einde
van de dag wordt als startwaarde doorgegeven naar de volgende dag.

#### Gegevensstroom

```
epex_be.csv (uurprijzen)
    ↓  epex_kwartier.converteer()   [kubische spline]
epex_kwartieren.csv (96 kwartierwaarden/dag)
    ↓  join op df['kwartier']
overall.csv + tariefparameters
    ↓
Scenario A: vast DATS24 vs dynamisch EPEX (zonder batterij)
    ↓
Scenario B: LP-optimalisatie batterijdispatch (dynamisch EPEX)
    ↓
Interactieve dagplot + maandoverzicht + samenvatting
```

---

## Technische achtergrond

### OwnDev — Raspberry Pi batterijbeheer

De OwnDev-logger voert het script `FYI/BatMgmtV3.py` uit. Dit script:

1. Leest elke seconde een P1-telegram via de seriële poort.
2. Leest gelijktijdig de SOFAR ME3000SP via Modbus TCP
   (register 525 = batterijvermogen, register 528 = SOC).
3. Schrijft elk paar naar het telegrambestand van de lopende minuut.
4. Stuurt via Modbus een lad/ontlaad-commando op basis van PV-productie,
   netprijzen en geplande levels.

### `scripts/config.py` — Configuratielaag

Alle paden en instellingen worden centraal beheerd. Secrets komen uit
Windows Credential Manager (`keyring`), paden en coördinaten uit `.env`.

```python
from scripts.config import (
    INTERMEDIATE_DIR,   # data/intermediate results/
    FINAL_DIR,          # data/Final/
    SOURCE_DIR,         # data/Source Data/
    SOLAR_DIR,          # pad uit .env
    BATTERY_DIR,        # pad uit .env
    WEATHER_CSV,        # pad uit .env
    LAT, LON,           # GPS-coördinaten
    PANEL_TILT,         # paneelhelling (°)
    PANEL_AZIMUTH,      # paneelazimut (°)
)
```

### Streamlit-dashboard

```bash
streamlit run app.py
```

Opent automatisch in de standaardbrowser op `http://localhost:8501`.
