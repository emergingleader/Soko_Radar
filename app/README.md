# SokoRadar app

A Streamlit app that shows food price forecasts for Kenyan counties. You choose a county and a food, and the app
shows the expected price for each of the next 3 months, a likely range, a warning when a rise above 15% is more
likely than usual, cheaper nearby counties (with a check on whether the trip is worth it) and a map of where prices
may jump.

Live app: https://sokoradar-priceforecasting.streamlit.app/

It imports `notebooks/handover/sokoradar_forecast.py` and `notebooks/handover/alerts/sokoradar_alerts.py` and
calls their functions.

| File | What it is |
|---|---|
| `streamlit_app.py` | The app |
| `transport.py` | Transport costs from notebook 05 (road distances, government hire rates and county fuel prices from `data/`) |
| `update_prices.py` | Downloads the latest WFP prices from HDX, runs the team's pipeline and writes `raw_data/prices_after_2024.csv` |
| `pipeline/sokoradar_pipeline.py` | The team's data pipeline (notebook 00), unchanged. It stores its own raw data |
| `raw_data/` | Files the forecast script needs (`counties.csv`, `county_climate_chirps_ndvi.csv`, `national_drivers_2006_2024.csv`), the county map (`ken_counties.geojson`) and the prices after 2024 (`prices_after_2024.csv`) |
| `requirements.txt` | Python packages, with the model packages pinned to the versions in the model card |
| `packages.txt` | A system library LightGBM needs on Streamlit Community Cloud |

Where each part comes from: prices from the pipeline (`data/` plus the months after 2024), the forecast, jump
warning and where-to-buy suggestion from notebook 02's handover script, the price range and seasonal label from
notebook 07's alerts script, and transport costs from notebook 05.

## Keeping the prices up to date

The app forecasts the 3 months after the latest month of prices. With prices up to October 2026, it shows November
2026 to January 2027. When newer prices are added, the months move on.

A GitHub Action (`.github/workflows/update-prices.yml`) does this on the 8th of every month. It downloads the latest
WFP Kenya prices from HDX, runs `update_prices.py` and pushes the new prices to `main` if they changed. Streamlit
Community Cloud then redeploys the app. You can also run it from the Actions tab (Update prices, then Run workflow).
If the prices fall more than 2 months behind, the app shows a note.

The MoA bulletin has no download link, so add a new bulletin by hand:

```
python app/update_prices.py --raw <folder with the new raw files>
```

The models are not retrained; they learned from data up to December 2024. On recorded prices from January 2025 to
June 2026, which they had not seen, the forecast error was 8.9%, 10.6% and 12.4% at 1, 2 and 3 months (2015 to 2024
backtest: 9.0%, 12.3% and 14.5%). The jump warning caught 56%, 46% and 35% of rises above 15% (backtest: 48%, 45%
and 34%), and 81%, 87% and 88% of prices fell inside the range (backtest: 78%, 80% and 82%).

## Run locally

```
pip install -r app/requirements.txt
streamlit run app/streamlit_app.py
```

## Deploy on Streamlit Community Cloud

1. Go to https://share.streamlit.io and choose Create app, then Deploy a public app from GitHub.
2. Use the repository `emergingleader/Soko_Radar`, branch `main` and main file `app/streamlit_app.py`.
3. Under Advanced settings, choose Python 3.12.
4. Deploy.

The first visit after the app starts runs the models. On Streamlit Community Cloud this takes about 6 to 7
minutes (2 to 3 minutes on a laptop). After that the results are cached, so later visits are quick.
