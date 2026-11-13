# SokoRadar app (Streamlit)

A simple price forecast for non-technical users: choose a county and a food, and see the expected price for each of
the next 3 months, a likely range, a warning when a jump above 15% is more likely than usual, a cheaper nearby county
(and whether the trip is worth it), and a map of where prices may jump.

It **imports** the team's frozen handover scripts and calls their functions; no existing file in the repo is changed.

| File | Purpose |
|---|---|
| `streamlit_app.py` | The app |
| `transport.py` | "Is the trip worth it?": the transport costs of notebook 05 (road distances, government hire rates, county fuel prices from `data/`), unchanged |
| `requirements.txt` | Python packages (model packages pinned to the MODEL_CARD versions) |
| `packages.txt` | System library LightGBM needs on Streamlit Community Cloud (`libgomp1`) |
| `raw_data/` | The driver files the forecast script needs (`counties.csv`, `county_climate_chirps_ndvi.csv`, `national_drivers_2006_2024.csv`), the county boundaries for the map (`ken_counties.geojson`) and the newer county prices (`prices_2025_2026.csv`) |
| `build_prices_2025_2026.py` | Rebuilds `prices_2025_2026.csv` with the team's own pipeline (only its end month changed) and joins it to `data/` without changing 2006-2024 |

How the app follows the repo: prices from the pipeline (`data/` plus the newer months), forecasts, jump warnings and
where to buy from notebook 02's handover script, the likely range and seasonal level from notebook 07's alerts script
("one alert, one label, one range"), and transport costs from notebook 05.

## Keeping it up to date

The app forecasts 3 months from the latest month of prices: now **September 2026 → October to December 2026**. The
models are unchanged (trained on answers up to Dec 2024). Tested on Jan 2025 to Jun 2026 recorded prices, which they
had not seen: forecast error 8.9 / 10.6 / 12.4 % at 1 / 2 / 3 months (2015-2024 backtest: 9.0 / 12.3 / 14.5 %),
price jumps caught 56 / 46 / 35 % (48 / 45 / 34 %), recorded prices inside the range 81 / 87 / 88 % (78 / 80 / 82 %).

When newer raw prices arrive (WFP, MoA bulletin), refresh the file and push:

```
python app/build_prices_2025_2026.py <path to sokoradar_pipeline.py> <raw data folder> <latest month, e.g. 2026-12>
```

## Run locally

```
pip install -r app/requirements.txt
streamlit run app/streamlit_app.py
```

## Deploy on Streamlit Community Cloud

1. Merge this branch into `main`.
2. Go to <https://share.streamlit.io>, choose **Create app → Deploy a public app from GitHub**.
3. Repository `emergingleader/Soko_Radar`, branch `main`, main file path `app/streamlit_app.py`.
4. Under **Advanced settings**, pick Python **3.12**.
5. Deploy.

The first visit runs the models (about 2 to 3 minutes); results are then cached.
