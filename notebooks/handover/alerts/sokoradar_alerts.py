"""SokoRadar alerts: the ALPS label and price ranges, for every county price series.

What it does, for every county price series (the same 1,222 series as the forecasting model):
  1. ALPS label: how far the price sits above its normal level for that time of year, learned from earlier
     months only (WFP's ALPS method). Each month is Normal, Stress, Alert or Crisis. It gives context; it is not an alert.
  2. If the forecasting model's output is given (sokoradar_forecast.py), for each horizon:
       - an 80% price range around the ARIMA forecast (width per commodity and horizon, tested on unseen years)
       - the spike alert, copied from the forecasting model (the one alert in SokoRadar)

Run (from Anaconda Prompt or Git Bash):
    python sokoradar_alerts.py                                              # ALPS label for the latest month
    python sokoradar_alerts.py --forecasts sokoradar_forecasts.csv          # + price ranges and the spike alert
    python sokoradar_alerts.py --origins 2024-06:2024-12 --out path/to/alerts.csv
    python sokoradar_alerts.py --check --backtest-dir path/to/forecasts     # reproduce the notebook results (06_alerts_aligned)

Output: a CSV (one row per series and origin month, or per series, origin month and horizon when --forecasts is given)
and a small JSON describing the run. See ALERTS_CARD.md for the columns, the results and the limits.
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

# --------------------------------------------------------------------------- frozen settings (from the notebooks)
DATA_FILE = "SokoRadar_County_2006_2024_long.csv"
MIN_MONTHS = 36                                   # months of history needed before a series gets an ALPS score
PHASES = ["Normal", "Stress", "Alert", "Crisis"]
CUTS = [-np.inf, 0.25, 1, 2, np.inf]              # WFP ALPS: Stress from 0.25, Alert from 1, Crisis from 2

# 80% price ranges around the ARIMA forecast: forecast x exp(+/- width). Widths are the 85th percentile of past misses
# |log(real price / forecast)| on real prices 2015-2024, per commodity and horizon (overall width when a commodity has
# fewer than 150 real misses at that horizon). Tested on 2017-2024, each year learning only from earlier years:
# 78.1% / 80.4% / 81.9% of real prices fell inside at 1 / 2 / 3 months (notebook 06_alerts_aligned, Step 5).
RANGE_WIDTH_OVERALL = {1: 0.16628, 2: 0.22775, 3: 0.26636}
RANGE_WIDTH = {
    "Beans Canadian": {1: 0.13502, 2: 0.18635, 3: 0.21447},
    "Beans Dolichos (Njahi)": {1: 0.14648, 2: 0.19242, 3: 0.22492},
    "Beans Mwitemania": {1: 0.13124, 2: 0.18176, 3: 0.21224},
    "Beans Rosecoco": {1: 0.14489, 2: 0.18745, 3: 0.21834},
    "Dry Maize": {1: 0.13626, 2: 0.19670, 3: 0.24342},
    "Mwezi Moja": {1: 0.13784, 2: 0.18714, 3: 0.21197},
    "Red Irish Potatoes": {1: 0.30066, 2: 0.41514, 3: 0.49464},
    "Sorghum": {1: 0.16925, 2: 0.21446, 3: 0.23690},
    "Vegetable oil": {1: 0.09205, 2: 0.11648, 3: 0.12050},
    "Wheat flour": {1: 0.11381, 2: 0.15461, 3: 0.11540},
    "White Irish Potatoes": {1: 0.31798, 2: 0.43957, 3: 0.53160},
}
RANGE_LEARN_AT, RANGE_MIN_ROWS = 0.85, 150        # only used by --check (recomputes the widths year by year)

# notebook results that --check must reproduce (06_alerts_aligned, real prices, 2015-2024)
EXPECTED = {
    "new alerts": 347,
    "M8a warned early %": 50.7, "Stress warned early %": 63.4, "Either warned early %": 84.1,
    "M8a spikes caught % (1 month)": 47.8, "Stress spikes caught % (1 month)": 11.3, "Either spikes caught % (1 month)": 53.8,
    "range inside % (1 month)": 78.1, "range inside % (2 months)": 80.4, "range inside % (3 months)": 81.9,
}
SPIKE = 0.15
M8A_THRESHOLD = {1: 0.08230874618305906, 2: 0.2025086377495205, 3: 0.35055914314124076}   # from sokoradar_forecast.py


# --------------------------------------------------------------------------- 1. load the data
def find_data(data_arg):
    if data_arg:
        path = Path(data_arg)
    else:
        places = [Path(os.environ["SOKORADAR_OUTPUT"])] if os.environ.get("SOKORADAR_OUTPUT") else []
        here = Path(__file__).resolve().parent
        places += [up / "output" for up in [here, Path.cwd(), *here.parents, *Path.cwd().parents][:12]]
        path = next((p / DATA_FILE for p in places if (p / DATA_FILE).exists()), None)
    if path is None or not path.exists():
        sys.exit(f"Could not find {DATA_FILE}. Pass --data, or set SOKORADAR_OUTPUT to the folder that holds it.")
    return path


def load_prices(path):
    prices = pd.read_csv(path, parse_dates=["month"])
    for col in ["month", "county", "commodity", "price_type", "price_kes", "flag"]:
        if col not in prices.columns:
            sys.exit(f"The price file has no '{col}' column")
    prices["observed"] = prices["flag"].astype(str).str.startswith("Observed")
    prices["series"] = prices["county"] + " | " + prices["commodity"] + " | " + prices["price_type"]
    return prices


# --------------------------------------------------------------------------- 2. ALPS label
def alps_scores(prices, months_wanted=None):
    """ALPS score per series and month: trend + 12 month dummies fitted on earlier months only (all prices),
    divided by the usual error. Returns a table: one row per month, one column per series."""
    P = prices.pivot(index="month", columns="series", values="price_kes").sort_index()
    t = np.arange(len(P))
    mon = P.index.month
    X = np.column_stack([np.ones(len(P)), t] + [(mon == m).astype(float) for m in range(2, 13)])
    rows = range(MIN_MONTHS, len(P)) if months_wanted is None else [P.index.get_loc(m) for m in months_wanted]
    out = pd.DataFrame(np.nan, index=P.index, columns=P.columns)
    Y = P.values
    for i in rows:
        if i < MIN_MONTHS:
            continue
        beta, *_ = np.linalg.lstsq(X[:i], Y[:i], rcond=None)                 # all series at once
        resid = Y[:i] - X[:i] @ beta
        sd = resid.std(axis=0, ddof=X.shape[1])
        out.iloc[i] = (Y[i] - X[i] @ beta) / sd
    return out.rename_axis(index="month", columns="series")


def to_phase(score):
    return pd.cut(score, CUTS, right=False, labels=PHASES).astype(str).replace("nan", "")


def phase_message(phase):
    return {"Stress": "Price above its normal level for the season; may reach Alert",
            "Alert": "Price unusually high for the season",
            "Crisis": "Price very high for the season: act now"}.get(phase, "")


# --------------------------------------------------------------------------- 3. price ranges
def width_for(commodity, horizon):
    return RANGE_WIDTH.get(commodity, {}).get(horizon, RANGE_WIDTH_OVERALL[horizon])


def add_forecasts(base, forecasts_path):
    fc = pd.read_csv(forecasts_path, encoding="utf-8-sig")
    need = ["series", "origin_month", "horizon", "forecast_price_kes", "alert"]
    missing = [c for c in need if c not in fc.columns]
    if missing:
        sys.exit(f"The forecasts file has no {missing} column(s); is it the output of sokoradar_forecast.py?")
    fc["alert"] = fc["alert"].astype(str).str.lower().isin(["true", "1"])
    keep = ["series", "origin_month", "horizon", "target_month", "forecast_price_kes", "forecast_change_pct",
            "spike_probability_pct", "alert", "where_to_buy_county"]
    out = base.merge(fc[[c for c in keep if c in fc.columns]].rename(columns={"alert": "spike_alert"}),
                     on=["series", "origin_month"], how="inner")
    w = np.array([width_for(c, h) for c, h in zip(out["commodity"], out["horizon"])])
    out["range_low_kes"] = (out["forecast_price_kes"] * np.exp(-w)).round(2)
    out["range_high_kes"] = (out["forecast_price_kes"] * np.exp(w)).round(2)
    out["range_plus_pct"] = ((np.exp(w) - 1) * 100).round(0)
    return out


def run(prices, origins, forecasts_path=None):
    t0 = time.time()
    scores = alps_scores(prices, origins)
    base = scores.loc[origins].stack().rename("alps_score").reset_index()
    base = base.rename(columns={"month": "origin_month"})
    info = prices.loc[prices["month"].isin(origins), ["series", "county", "commodity", "price_type", "month", "price_kes", "observed"]]
    base = info.rename(columns={"month": "origin_month", "observed": "price_is_real"}).merge(base, on=["series", "origin_month"], how="left")
    base["alps_score"] = base["alps_score"].round(3)
    base["phase"] = to_phase(base["alps_score"])
    base["phase_message"] = base["phase"].map(phase_message)
    base["origin_month"] = base["origin_month"].dt.strftime("%Y-%m")
    out = add_forecasts(base, forecasts_path) if forecasts_path else base
    out = out.sort_values([c for c in ["series", "origin_month", "horizon"] if c in out.columns]).reset_index(drop=True)
    print(f"Scored {base['series'].nunique():,} series x {len(origins)} month(s) in {time.time() - t0:.0f} s; "
          f"Stress or higher in {base['phase'].isin(['Stress', 'Alert', 'Crisis']).mean():.0%} of them")
    if "spike_alert" in out:
        print(f"Spike alerts: {int(out['spike_alert'].sum()):,} of {len(out):,} forecasts")
    return out


# --------------------------------------------------------------------------- 4. --check: reproduce the notebook
def check(prices, backtest_dir):
    """Recompute the headline results of 06_alerts_aligned from the saved backtests and compare."""
    d = Path(backtest_dir)
    def find(*names):
        p = next((d / n for n in names if (d / n).exists()), None)
        if p is None:
            sys.exit(f"Missing {names[0]} in {d}")
        return p
    arima = pd.read_pickle(find("ARIMA_Daniella_s_orders.pkl", "ARIMAorders.pkl"))
    m8a = pd.read_pickle(find("M8a_full_balancing_weight.pkl"))
    key = ["series", "origin_month", "horizon"]
    bt = (arima.rename(columns={"forecast_price": "arima_price"})
               .merge(m8a[key + ["forecast_price"]].rename(columns={"forecast_price": "spike_prob"}), on=key))
    bt["commodity"] = bt["commodity"].astype(str)
    bt["spike"] = bt["target_price"] / bt["origin_price"] - 1 > SPIKE
    bt["alert"] = bt["spike_prob"] > bt["horizon"].map(M8A_THRESHOLD)
    got = {}

    # new seasonal alerts: who warned first (Step 3)
    A = alps_scores(prices)
    OBS = prices.pivot(index="month", columns="series", values="observed").reindex_like(A).astype(bool)
    hit, stress = A >= 1, (A >= 0.25) & (A < 1)
    calm = ~hit.shift(1, fill_value=False) & ~hit.shift(2, fill_value=False) & ~hit.shift(3, fill_value=False)
    inside = pd.Series((A.index >= "2015-04-01") & (A.index <= "2024-12-01"), index=A.index)
    events = (hit & calm & OBS).loc[inside]
    def m8a_at(k):
        w = bt[bt["horizon"] == k].pivot(index="origin_month", columns="series", values="alert")
        return w.reindex(index=A.index, columns=A.columns).fillna(False).astype(bool)
    def lead(warned):
        L = pd.DataFrame(0, index=A.index, columns=A.columns)
        for k in (1, 2, 3):
            L = L.mask(warned(k), k)
        return L.loc[inside].values[events.values]
    l_m8a = lead(lambda k: m8a_at(k).shift(k, fill_value=False))
    l_str = lead(lambda k: stress.shift(k, fill_value=False))
    got["new alerts"] = len(l_m8a)
    got["M8a warned early %"] = 100 * (l_m8a > 0).mean()
    got["Stress warned early %"] = 100 * (l_str > 0).mean()
    got["Either warned early %"] = 100 * ((l_m8a > 0) | (l_str > 0)).mean()

    # sudden jumps (Step 4)
    st = stress.stack().rename("stress_now").reset_index().rename(columns={"month": "origin_month"})
    b = bt.merge(st, on=["origin_month", "series"], how="left")
    b["stress_now"] = b["stress_now"].fillna(False).astype(bool)
    g = b[b["target_observed"] & (b["horizon"] == 1)]
    for name, on in [("M8a", g["alert"]), ("Stress", g["stress_now"]), ("Either", g["alert"] | g["stress_now"])]:
        got[f"{name} spikes caught % (1 month)"] = 100 * (on & g["spike"]).sum() / g["spike"].sum()

    # price ranges (Step 5)
    real = bt[bt["target_observed"]].copy()
    real["miss"] = np.abs(np.log(real["target_price"] / real["arima_price"]))
    parts = []
    for y in range(2017, 2025):
        learn, test = real[real["fold year"] < y], real[real["fold year"] == y]
        for (h, c), grp in test.groupby(["horizon", "commodity"]):
            L = learn[learn["horizon"] == h]
            Lc = L[L["commodity"] == c]
            q = (Lc if len(Lc) >= RANGE_MIN_ROWS else L)["miss"].quantile(RANGE_LEARN_AT)
            parts.append(pd.DataFrame({"h": h, "inside": grp["miss"] <= q}))
    cov = pd.concat(parts).groupby("h")["inside"].mean() * 100
    for h, label in [(1, "1 month"), (2, "2 months"), (3, "3 months")]:
        got[f"range inside % ({label})"] = cov[h]

    ok = True
    for k, want in EXPECTED.items():
        same = abs(got[k] - want) <= 0.15
        ok &= same
        print(f"{'OK ' if same else 'DIFF'}  {k:38s} notebook {want:8.1f}   script {got[k]:8.1f}")
    print("All results reproduced." if ok else "Some results differ: is the data file the same version as the notebook's?")
    return ok


# --------------------------------------------------------------------------- 5. main
def parse_origins(text, prices):
    if not text:
        return [prices["month"].max()]
    start, _, end = text.partition(":")
    return list(pd.date_range(pd.Timestamp(start), pd.Timestamp(end or start), freq="MS"))


def main():
    ap = argparse.ArgumentParser(description="SokoRadar: ALPS label and price ranges")
    ap.add_argument("--data", help=f"path to {DATA_FILE} (default: found automatically)")
    ap.add_argument("--forecasts", help="output CSV of sokoradar_forecast.py, to add price ranges and the spike alert")
    ap.add_argument("--origins", help="origin month or range, e.g. 2024-12 or 2024-06:2024-12 (default: latest month)")
    ap.add_argument("--out", default="sokoradar_alerts.csv", help="output CSV (default: sokoradar_alerts.csv)")
    ap.add_argument("--check", action="store_true", help="reproduce the results of notebook 06_alerts_aligned")
    ap.add_argument("--backtest-dir", help="folder with ARIMA_Daniella_s_orders.pkl and M8a_full_balancing_weight.pkl (for --check)")
    args = ap.parse_args()

    data_path = find_data(args.data)
    prices = load_prices(data_path)
    print(f"Prices: {data_path}\n{len(prices):,} rows, {prices['series'].nunique():,} series, "
          f"{prices['month'].min():%b %Y} to {prices['month'].max():%b %Y}")

    if args.check:
        if not args.backtest_dir:
            sys.exit("--check needs --backtest-dir (the folder with the saved backtest .pkl files)")
        sys.exit(0 if check(prices, args.backtest_dir) else 1)

    origins = parse_origins(args.origins, prices)
    missing = [o for o in origins if o not in set(prices["month"])]
    if missing:
        sys.exit(f"No prices for origin month(s) {[f'{m:%Y-%m}' for m in missing]}")
    out = run(prices, origins, args.forecasts)

    path = Path(args.out)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    out.to_csv(tmp, index=False, encoding="utf-8-sig")
    os.replace(tmp, path)
    path.with_suffix(".json").write_text(json.dumps({
        "created": pd.Timestamp.now().strftime("%Y-%m-%d %H:%M"), "data_file": str(data_path),
        "origin_months": [f"{o:%Y-%m}" for o in origins], "forecasts_file": args.forecasts, "rows": len(out),
        "alps": {"min_months": MIN_MONTHS, "cuts": CUTS[1:-1]},
        "range_widths": {"overall": RANGE_WIDTH_OVERALL, "by_commodity": RANGE_WIDTH},
    }, indent=1, default=str))
    print(f"Saved {len(out):,} rows to {path.resolve()}")


if __name__ == "__main__":
    main()
