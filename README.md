# SokoRadar

**An early warning system for food price shocks in Kenyan markets.**
Group 10, Moringa School Data Science Capstone, 2026.

SokoRadar forecasts food prices in Kenyan counties 1 to 3 months ahead, warns when a sharp price rise is likely, and suggests where to buy more cheaply. It is built for county food security officers, NDMA, aid agencies, traders and farmers.

**Live app:** https://sokoradar-priceforecasting.streamlit.app/

## The problem

Food price spikes hit poor households, farmers and pastoralists hardest. Today's tools, such as WFP's ALPS and the Ministry of Agriculture's KAMIS, report prices after they have risen. Responses such as adjusting cash transfers or releasing reserves therefore come late.

SokoRadar asks one question: **can we see a price shock coming early enough to act?**

The full proposal is in [`docs/SokoRadar_Capstone_Proposal.pdf`](docs/SokoRadar_Capstone_Proposal.pdf). Since then, the plan was simplified: VAR, impulse responses and the spillover index moved to future work.

## What SokoRadar gives each user

| Output | Question it answers |
|---|---|
| **Price forecast** | Where is this price heading over the next 1 to 3 months? |
| **Price range** | How far could it be from the forecast? (80% range) |
| **Spike alert** | Is a rise above 15% more likely than usual? |
| **ALPS label** | Is the price high for the season right now? (Normal, Stress, Alert, Crisis) |
| **Drivers** | What is pushing the forecast up or down? |
| **Where to buy** | Which nearby county is cheaper right now? |

## Data

* A monthly county price panel, 2006 to 2024: 1,222 series (county, commodity, retail or wholesale).
* Only about 5% to 7% of prices were recorded in a market; the rest are estimates. **All results below are scored on recorded prices only.**
* WFP market prices (via HDX) for the first early warning study, including the 2011, 2017 and 2022 droughts.
* The panel is in `data/` (`SokoRadar_County_2006_2024_long.csv` and an Excel copy), with national prices in `national_prices_2006_2024.csv`.

## How we built it

1. **Data and EDA:** cleaned the panel, separated recorded from estimated prices, and explored seasonality, trends and how crops move together.
2. **Baselines and lead lag:** set the bar every model must beat ("next month = this month", "same month last year") and checked which crops lead others.
3. **Time series:** ARIMA models on log prices, one per series.
4. **Where to buy:** compares recorded prices across nearby counties, including the cost of transport (road distance, fuel and vehicle hire).
5. **The forecasting model:** ARIMA for the price forecast, plus a LightGBM classifier for the spike alert, with SHAP for the drivers.
6. **Alerts and explainability:** tested the spike alert on recorded prices, added the ALPS label and the price ranges.

Every result comes from a year by year backtest, 2015 to 2024: each year is predicted using only earlier years.

## Results (2015 to 2024, recorded prices only)

| Part | Result |
|---|---|
| Price forecast | Average error 9.0%, 12.3% and 14.5% at 1, 2 and 3 months, about level with "next month = this month" |
| Spike alert | Catches 48% of rises above 15% at 1 month; 22% of alerts are followed by a rise, about twice the normal rate |
| New seasonal alerts | Warned of 51% of markets moving into Alert, about 2 months ahead (the ALPS Stress label warned of 63%) |
| Price ranges | 78% to 82% of recorded prices fell inside, on years the ranges had not seen (target 75% to 85%) |
| Where to buy | Of 956 suggestions that could be checked a month later, the suggested county was really cheaper in 85%, saving about 20% before transport. After transport, a full lorry of 5 t or more still saves money in about two thirds of cases or more; small loads rarely do |

**Honest summary:** prices are hard to forecast from this data, but the spike alert and the where to buy suggestions add real value, especially for bulk buyers. An alert means higher risk, not a certain spike.

## Sealed test on 2025 to 2026 (real prices only)

The frozen models (trained on answers up to December 2024, settings unchanged) were run once on months they had never seen: forecasts from every month from January 2025 to August 2026, scored on 870 / 826 / 733 real WFP prices at 1 / 2 / 3 months in 135 series. The protocol was written before the test was opened. Details: notebook 02, section 12, and `notebooks/handover/MODEL_CARD.md`.

| Part | 2025-26 sealed test | 2015-24 backtest |
|---|---|---|
| Price forecast, average error at 1, 2 and 3 months | 10.8%, 12.8%, 13.6% | 9.0%, 12.3%, 14.5% |
| Rises above 15% caught by the spike alert | 51%, 42%, 38% | 48%, 45%, 34% |
| Alerts followed by a rise | 22%, 37%, 46% | 22%, 32%, 39% |
| Calm months with no alert | 68%, 83%, 90% | 80%, 81%, 86% |
| Where to buy, suggested county really cheaper | 8 of 10 checkable (too few to judge) | 85% of 956 |

2025-26 was a harder period: even "next month = this month" missed by 10.8% at 1 month. Against that, the forecast was level at 1 month and 2% to 3% better at 2 and 3 months, as in the backtest. The alert caught about half of sharp rises, with more false alarms at 1 month. The price range was checked in the backtest only.

## Repository layout

```
Soko_Radar/
├── README.md
├── docs/
│   └── SokoRadar_Capstone_Proposal.pdf
├── data/                                  county and national prices 2006 to 2024, plus road distance, fuel and vehicle hire data
├── notebooks/
│   ├── 00_sokoradar_pipeline_output.ipynb   builds the county price panel
│   ├── 01_eda_review_with_insights.ipynb    data exploration and chart insights
│   ├── 02_model_build.ipynb                 the forecasting model and spike alert
│   ├── 03_baselines_leadlag.ipynb           baselines and which crops lead
│   ├── 04_timeseries.ipynb                  ARIMA models
│   ├── 05_recommender.ipynb                 where to buy, with transport costs
│   ├── 06_alerts.ipynb                      ALPS early warning on WFP prices
│   ├── 07_alerts_aligned.ipynb              alert test, ALPS label, price ranges
│   └── handover/
│       ├── sokoradar_forecast.py, MODEL_CARD.md
│       └── alerts/   sokoradar_alerts.py, ALERTS_CARD.md
├── reports/figures/                       EDA charts
├── app/                                   the SokoRadar app (Streamlit), see app/README.md
│   ├── streamlit_app.py                     price forecast for the next 3 months, past prices, jump warnings, where to buy, map
│   ├── transport.py                         transport costs from notebook 05
│   ├── update_prices.py                     downloads the latest WFP prices and runs the pipeline
│   ├── pipeline/sokoradar_pipeline.py       the data pipeline (notebook 00), unchanged
│   └── raw_data/                            driver files, county map, prices after 2024
├── .streamlit/config.toml                 the app's theme
└── .github/workflows/update-prices.yml    monthly automatic price update
```

## How to run

1. Clone the repository and install the packages:
   ```
   git clone https://github.com/emergingleader/Soko_Radar.git
   cd Soko_Radar
   pip install numpy pandas statsmodels lightgbm shap
   ```
2. Make the forecasts (the drivers need the climate and national driver files in a folder passed with `--raw`):
   ```
   python notebooks/handover/sokoradar_forecast.py --data data/SokoRadar_County_2006_2024_long.csv --raw <raw folder>
   ```
3. Add the ALPS label and price ranges:
   ```
   python notebooks/handover/alerts/sokoradar_alerts.py --data data/SokoRadar_County_2006_2024_long.csv --forecasts sokoradar_forecasts.csv
   ```
4. Output CSV files are not committed to GitHub.
5. Run the app (it runs the same models on the latest prices and shows the next 3 months):
   ```
   pip install -r app/requirements.txt
   streamlit run app/streamlit_app.py
   ```
6. Update the prices: the GitHub Action `Update prices` does this on the 8th of every month (or run it from the Actions tab). By hand:
   ```
   python app/update_prices.py
   ```
   It downloads the latest WFP Kenya prices from HDX and rebuilds the months after 2024 with the pipeline; the 2006 to 2024 data in `data/` is not changed.

## Status

| Part | Status |
|---|---|
| Data panel and EDA | Done |
| Baselines, ARIMA, where to buy | Done |
| Forecasting model and spike alert | Done |
| Alerts, ALPS label, price ranges | Done |
| App (Streamlit) | Done: [live](https://sokoradar-priceforecasting.streamlit.app/), forecasts the 3 months after the latest prices, updated monthly |
| API, USSD and SMS | Planned |
| Test on 2025 to 2026 prices | Done (see above) |

## Limits

* Most prices in the panel are estimates; only recorded prices are used to score results.
* About half of spikes come without an alert, because many are caused by events the data cannot see (floods, conflict, policy changes).
* Where to buy needs recorded prices in both counties, so many alerts have no suggestion. Since January 2025 few markets record prices, so the app falls back to the Ministry county bulletin and marks those answers Indicative. Road distances are measured on today's roads for all 47 counties (OpenStreetMap, between the main county towns, not individual markets); the backtest above used the 1994 matrix of 41 counties. Transport costs use the government hire card with assumed fuel use. Choosing by the forecast adds nothing over today's cheapest nearby county.
* Prices after 2024 extend the panel with the pipeline's own rules. MoA daily prices end in January 2025, so later months follow the MoA bulletin (maize, beans, potatoes) and WFP prices; milk after early 2026 and dried fish are carried at their last value.
* The models are still trained on answers up to December 2024. Retraining on newer data is a decision for the group.

## Team

| Role | Member |
|---|---|
| Data engineer | Zainabu |
| Forecasting | Thande, Frank |
| Alerts and explainability | Siraji |
| Deployment | Tonny |
| Product and impact | Sam |

## Data credits

Ministry of Agriculture and Livestock Development (KAMIS), WFP via HDX (CC BY IGO), KNBS, Central Bank of Kenya, World Bank.
