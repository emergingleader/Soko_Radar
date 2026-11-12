# SokoRadar alerts: card

For the deployment and dashboard team. Built and tested in `notebooks/07_alerts_aligned.ipynb` (the spike alert tested on real prices, the ALPS label and the price ranges) and `notebooks/06_alerts.ipynb` (the first ALPS early warning study on WFP market prices).

## One alert, one label, one range

| What | Question it answers | Where it comes from |
|---|---|---|
| **Spike alert** | Is a rise above 15% more likely than usual? | The forecasting model (`sokoradar_forecast.py`). This is the only alert in SokoRadar. |
| **ALPS label** | Is the price high for the season right now? | This script. WFP's ALPS method: the price compared with its normal level for that time of year (trend plus month of year), learned from earlier months only. Normal below 0.25, Stress 0.25 to 1, Alert 1 to 2, Crisis 2 and above. It gives context; it is not an alert. |
| **Price range** | How far could the price be from the forecast? | This script. An 80% range around the price forecast, with its own width for each crop and horizon. |

## How to run

Needs Python with numpy and pandas. From the repo folder:

```
python notebooks/handover/alerts/sokoradar_alerts.py --data data/SokoRadar_County_2006_2024_long.csv
python notebooks/handover/alerts/sokoradar_alerts.py --data data/SokoRadar_County_2006_2024_long.csv --forecasts sokoradar_forecasts.csv
python notebooks/handover/alerts/sokoradar_alerts.py --data data/SokoRadar_County_2006_2024_long.csv --origins 2024-06:2024-12 --out alerts.csv
```

1. The first line gives the ALPS label for the latest month.
2. The second adds the price ranges and the spike alert. Run `sokoradar_forecast.py` first to make `sokoradar_forecasts.csv`.
3. The third scores a range of months.

It takes a few seconds and writes a CSV and a `.json` beside it. Don't commit the outputs to Git.

`--check --backtest-dir <folder>` reproduces the results of notebook 07 from the saved backtest files (the ARIMA and M8a `.pkl` files).

## Output columns

| Column | Meaning |
|---|---|
| `series`, `county`, `commodity`, `price_type`, `origin_month` | Which price, and when |
| `price_kes`, `price_is_real` | Price at the origin month; `True` = recorded in a market, `False` = estimated |
| `alps_score`, `phase`, `phase_message` | ALPS score, label (Normal, Stress, Alert, Crisis) and a plain message; blank for the first 36 months of a series |
| `horizon`, `target_month`, `forecast_price_kes`, `forecast_change_pct`, `spike_probability_pct`, `spike_alert`, `where_to_buy_county` | Copied from the forecasting model's output (with `--forecasts`) |
| `range_low_kes`, `range_high_kes`, `range_plus_pct` | 80% price range around the forecast, and its width in % |

## How well it works

2015 to 2024, each year predicted only from earlier years, real market prices only.

* **Spike alert:** catches 48% of rises above 15% one month ahead. 22% of its alerts are followed by a rise, about twice as often as by chance.
* **New seasonal alerts** (a market moving into Alert after 3 calm months, 347 cases): the spike alert warned of 51%, about 2 months ahead. The ALPS Stress label warned of 63%, which is why it is shown beside the alert as context.
* **Price ranges:** on years they had not seen (2017 to 2024), 78%, 80% and 82% of real prices fell inside at 1, 2 and 3 months (target 75% to 85%). Typical widths: maize about ±15%, ±22%, ±28%; potatoes about ±35%, ±51%, ±64%.
* **On WFP market prices** (notebook 06): the first ALPS early warning model warned of 75% of new alerts, about 2 months early, including 15 of 17 in the 2017 drought.

## Limits (please show these to users)

* **An alert means higher risk, not a certain spike.** About half of spikes come without one, because many are caused by events the data cannot see (floods, conflict, policy changes).
* **Mostly estimated prices.** About 7% of later prices were recorded in a market, and all scores use those only.
* **The ALPS label says "high for the season", not "a spike is coming".** The spike alert answers that question.
* **The range width was learned at the 85th percentile of past misses,** because a first test at 80% gave too little coverage in recent, more volatile years.
* **Not yet tested on 2025 to 2026.**

## Frozen settings

All settings sit at the top of `sokoradar_alerts.py`: ALPS cut offs (0.25, 1, 2), 36 months of history, and the price range widths per crop and horizon. They were set in the notebooks; don't change them without rerunning the notebooks.
