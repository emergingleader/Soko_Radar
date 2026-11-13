# SokoRadar dashboard (Streamlit)

A Streamlit front end for the frozen handover models. It **imports** `notebooks/handover/sokoradar_forecast.py` and
`notebooks/handover/alerts/sokoradar_alerts.py` and calls their functions; no existing file in the repo is changed.

| File | Purpose |
|---|---|
| `streamlit_app.py` | The app |
| `requirements.txt` | Python packages (model packages pinned to the MODEL_CARD versions) |
| `packages.txt` | System library LightGBM needs on Streamlit Community Cloud (`libgomp1`) |
| `raw_data/` | The three driver files the forecast script needs (`counties.csv`, `county_climate_chirps_ndvi.csv`, `national_drivers_2006_2024.csv`) and the county boundaries for the map (`ken_counties.geojson`) |

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
