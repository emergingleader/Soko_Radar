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
| `raw_data/` | The driver files the forecast script needs (`counties.csv`, `county_climate_chirps_ndvi.csv`, `national_drivers_2006_2024.csv`) and the county boundaries for the map (`ken_counties.geojson`) |

How the app follows the repo: prices from the pipeline (`data/`), forecasts, jump warnings and where to buy from
notebook 02's handover script, the likely range and seasonal level from notebook 07's alerts script ("one alert, one
label, one range"), and transport costs from notebook 05. The county prices and the models end in December 2024, so
the forecast covers January to March 2025 until the data is updated.

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
