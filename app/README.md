# SokoRadar dashboard (Streamlit)

A Streamlit front end for the frozen handover models. It **imports** `notebooks/handover/sokoradar_forecast.py` and
`notebooks/handover/alerts/sokoradar_alerts.py` and calls their functions; no existing file in the repo is changed.

| File | Purpose |
|---|---|
| `streamlit_app.py` | The app |
| `transport.py` | Where to buy after transport costs: the transport layer of notebook 05 (road distances, government hire card, county fuel prices from `data/`), unchanged |
| `requirements.txt` | Python packages (model packages pinned to the MODEL_CARD versions) |
| `packages.txt` | System library LightGBM needs on Streamlit Community Cloud (`libgomp1`) |
| `raw_data/` | The three driver files the forecast script needs (`counties.csv`, `county_climate_chirps_ndvi.csv`, `national_drivers_2006_2024.csv`) and the county boundaries for the map (`ken_counties.geojson`). `real_ledger.csv` holds the recorded WFP market prices (to Sep 2026) behind the Live markets tab; it is the handoff file saved by notebook 01 |

## Where each part of the app comes from

The app is the last step of the repo and draws on every earlier one, in order:

| App part | From |
|---|---|
| County price data (2006 to Dec 2024) | `00_sokoradar_pipeline_output` → `data/` |
| Insights tab: charts and findings | `01_eda_review_with_insights` (`reports/figures`), `03_baselines_leadlag` |
| Price forecast, spike alert, drivers, where to buy | `02_model_build` → `handover/sokoradar_forecast.py` |
| Where to buy **after transport** | `05_recommender` → `app/transport.py` |
| Live markets: recorded WFP prices to Sep 2026 and their seasonal label | `01` (`real_ledger.csv`), ALPS method of `06_alerts` |
| One alert, one label, one range; price ranges | `07_alerts_aligned` → `handover/alerts/sokoradar_alerts.py` |
| Does it work?: 2015-24 backtest and 2025-26 final tests | `02`, `05`, `07`; final tests of `03`, `04`, `06` |

The county data and the deployed models end in December 2024, as set in notebooks 00 and 02. 2025-26 is shown from
recorded WFP prices, as notebooks 03, 04 and 06 did. Testing the deployed models on 2025-26 is the group's Day 5 step.

## Run locally

```
pip install -r app/requirements.txt
streamlit run app/streamlit_app.py
```

## Deploy on Streamlit Community Cloud

1. Push this branch to GitHub (or merge it into `main`).
2. Go to <https://share.streamlit.io>, choose **Create app → Deploy a public app from GitHub**.
3. Repository `emergingleader/Soko_Radar`, branch `main` (or this branch), main file path `app/streamlit_app.py`.
4. Under **Advanced settings**, pick Python **3.12** (3.11 also works).
5. Deploy.

The first visit runs the models from the latest month (about 2 to 3 minutes); results are then cached. Each extra
origin month chosen in the sidebar costs one more run of the same length.
