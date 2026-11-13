"""SokoRadar dashboard (Streamlit).

Runs the team's frozen handover scripts as they are:
  notebooks/handover/sokoradar_forecast.py         price forecast, spike alert, drivers, where to buy
  notebooks/handover/alerts/sokoradar_alerts.py    ALPS label and 80% price ranges
Nothing in those files is changed: they are loaded as modules and their functions are called directly.

Run locally from the repo folder:
    pip install -r app/requirements.txt
    streamlit run app/streamlit_app.py
"""
import importlib.util
import io
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

APP = Path(__file__).resolve().parent
REPO = APP.parent
DATA = REPO / "data" / "SokoRadar_County_2006_2024_long.csv"
RAW = APP / "raw_data"                      # counties, climate and national drivers (not in data/)
HANDOVER = REPO / "notebooks" / "handover"

BLUE, RED, GREY, INK = "#2a6fdb", "#e34948", "#b9b8b3", "#1f1f1e"
PHASE_COLOUR = {"Normal": "#3a9a5b", "Stress": "#d9a400", "Alert": "#e07b26", "Crisis": "#c62f2f", "": "#8a8985"}

st.set_page_config(page_title="SokoRadar", page_icon="🌽", layout="wide")


# --------------------------------------------------------------------------- the handover scripts, loaded as modules
@st.cache_resource
def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


fc = load_module("sokoradar_forecast", HANDOVER / "sokoradar_forecast.py")
al = load_module("sokoradar_alerts", HANDOVER / "alerts" / "sokoradar_alerts.py")


def safely(fn, *args):
    """The scripts stop with sys.exit() on bad input; show that as an error instead of killing the app."""
    try:
        return fn(*args)
    except SystemExit as e:
        st.error(f"SokoRadar stopped: {e}")
        st.stop()


# --------------------------------------------------------------------------- data and models (cached)
@st.cache_data(show_spinner="Loading the county price panel ...")
def prices_for_forecast():
    return safely(fc.load_prices, DATA)


@st.cache_data(show_spinner=False)
def prices_for_alerts():
    return safely(al.load_prices, DATA)


@st.cache_data(show_spinner=False, max_entries=4)
def run_models(origin: str) -> pd.DataFrame:
    """Forecast + spike alert + drivers + where to buy, then ALPS label + price ranges, for one origin month."""
    month = pd.Timestamp(origin)
    out = safely(fc.run, prices_for_forecast(), RAW, [month], fc.TRAIN_END)
    ranges = safely(al.run, prices_for_alerts(), [month], io.StringIO(out.to_csv(index=False)))
    key = ["series", "origin_month", "horizon"]
    extra = ranges[key + ["alps_score", "phase", "phase_message", "range_low_kes", "range_high_kes", "range_plus_pct"]]
    return out.merge(extra, on=key, how="left")


@st.cache_data(show_spinner=False)
def alps_history(series: str) -> pd.Series:
    prices = prices_for_alerts()
    return al.alps_scores(prices[prices["series"] == series])[series]


# --------------------------------------------------------------------------- sidebar
prices = prices_for_forecast()
latest = prices["month"].max()
month_options = [f"{m:%Y-%m}" for m in pd.date_range(end=latest, periods=24, freq="MS")][::-1]

with st.sidebar:
    st.title("🌽 SokoRadar")
    st.caption("Early warning for food price shocks in Kenyan counties")
    origin = st.selectbox("Forecast from (origin month)", month_options, index=0,
                          help="The latest month is a real forecast. Earlier months are in-sample: "
                               f"the models learned outcomes up to {fc.TRAIN_END}.")
    counties = sorted(prices["county"].unique())
    county = st.selectbox("County", counties, index=counties.index("Nakuru") if "Nakuru" in counties else 0)
    here = prices[prices["county"] == county]
    commodities = sorted(here["commodity"].unique())
    commodity = st.selectbox("Commodity", commodities,
                             index=commodities.index("Dry Maize") if "Dry Maize" in commodities else 0)
    types = sorted(here.loc[here["commodity"] == commodity, "price_type"].unique())
    price_type = st.radio("Price type", types, horizontal=True)
    st.divider()
    st.caption("An alert means **higher risk**, not a certain spike. About half of spikes come without one. "
               "Most prices are estimates; only recorded prices were used to score the models.")

with st.spinner(f"Running the SokoRadar models from {origin} (first run takes 2 to 3 minutes; then it is cached) ..."):
    result = run_models(origin)

if origin < fc.TRAIN_END:
    st.warning(f"Origin {origin} is **in-sample**: the models learned what happened up to {fc.TRAIN_END}, "
               "so past alerts here look better than a fair test.", icon="⚠️")

series = f"{county} | {commodity} | {price_type}"
rows = result[result["series"] == series].sort_values("horizon")

tab_series, tab_alerts, tab_about = st.tabs(["📈 Market view", "🚨 Alerts this month", "ℹ️ About and limits"])


# --------------------------------------------------------------------------- tab 1: one market
with tab_series:
    st.subheader(series)
    if rows.empty:
        st.info("No forecast for this series and month.")
        st.stop()
    first = rows.iloc[0]
    phase = first["phase"] if isinstance(first["phase"], str) else ""

    c1, c2, c3, c4 = st.columns(4)
    c1.metric(f"Price in {origin} (KES/kg)", f"{first['origin_price_kes']:,.1f}",
              help="Recorded in a market" if first["origin_price_is_real"] else "Estimated by the data pipeline")
    c1.caption("✅ recorded in a market" if first["origin_price_is_real"] else "≈ estimated price")
    c2.metric("Seasonal label (ALPS)", phase or "n/a")
    score = f"Score {first['alps_score']:.2f}. " if pd.notna(first["alps_score"]) else ""
    c2.caption(score + (first["phase_message"] if isinstance(first["phase_message"], str) and first["phase_message"]
                        else "Price compared with its normal level for the season"))
    n_alerts = int(rows["alert"].sum())
    c3.metric("Spike alerts", f"{n_alerts} of 3", help="Alerts at 1, 2 and 3 months ahead")
    c3.caption("Higher risk of a rise above 15%" if n_alerts else "No alert: risk not above usual")
    c4.metric("In 3 months (KES/kg)", f"{rows.iloc[-1]['forecast_price_kes']:,.1f}",
              f"{rows.iloc[-1]['forecast_change_pct']:+.1f}%", delta_color="inverse")

    # chart: history, real prices, forecast with 80% range
    hist = prices[(prices["series"] == series) & (prices["month"] <= pd.Timestamp(origin))].tail(36)
    real = hist[hist["observed"]]
    tm = pd.to_datetime(rows["target_month"])
    o = pd.Timestamp(origin)
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=[o, *tm, *tm[::-1], o],
                             y=[first["origin_price_kes"], *rows["range_high_kes"], *rows["range_low_kes"][::-1],
                                first["origin_price_kes"]],
                             mode="lines", fill="toself", fillcolor="rgba(42,111,219,0.15)", line=dict(width=0),
                             name="80% price range", hoverinfo="skip"))
    fig.add_trace(go.Scatter(x=hist["month"], y=hist["price_kes"], mode="lines", line=dict(color=GREY, width=2),
                             name="price (estimated months included)"))
    fig.add_trace(go.Scatter(x=real["month"], y=real["price_kes"], mode="markers", marker=dict(color=INK, size=6),
                             name="recorded market price"))
    fig.add_trace(go.Scatter(x=[o, *tm], y=[first["origin_price_kes"], *rows["forecast_price_kes"]],
                             mode="lines+markers", line=dict(color=BLUE, dash="dash", width=2), name="forecast (ARIMA)"))
    alerted = rows[rows["alert"]]
    if len(alerted):
        fig.add_trace(go.Scatter(x=pd.to_datetime(alerted["target_month"]), y=alerted["forecast_price_kes"],
                                 mode="markers", marker=dict(color=RED, size=13, symbol="triangle-up"),
                                 name="spike alert"))
    fig.update_layout(height=420, margin=dict(l=10, r=10, t=10, b=10), yaxis_title="KES per kg",
                      legend=dict(orientation="h", y=-0.15), hovermode="x unified")
    st.plotly_chart(fig, use_container_width=True)

    # table per horizon
    table = pd.DataFrame({
        "Months ahead": rows["horizon"].values,
        "Month": rows["target_month"].values,
        "Forecast (KES/kg)": rows["forecast_price_kes"].values,
        "Change": rows["forecast_change_pct"].map("{:+.1f}%".format).values,
        "80% range (KES/kg)": [f"{lo:,.2f} to {hi:,.2f}" for lo, hi in zip(rows["range_low_kes"], rows["range_high_kes"])],
        "Spike chance": rows["spike_probability_pct"].map("{:.1f}%".format).values,
        "Alert above": rows["alert_threshold_pct"].map("{:.1f}%".format).values,
        "Alert": np.where(rows["alert"], "🚨 higher risk", "—"),
    })
    st.dataframe(table, hide_index=True, use_container_width=True)
    st.caption("The forecast and the alert come from different models on purpose: the forecast is the most likely path, "
               "the alert says the chance of a big rise is higher than usual. A flat forecast can sit next to an alert.")

    left, right = st.columns([3, 2])
    with left:
        st.markdown("#### What moves the forecast")
        h = st.radio("Horizon", [1, 2, 3], horizontal=True, format_func=lambda k: f"{k} month{'s' if k > 1 else ''}",
                     key="driver_h")
        r = rows[rows["horizon"] == h].iloc[0]
        d = pd.DataFrame({"driver": [r[f"driver_{k}"] for k in (1, 2, 3)],
                          "push": [r[f"driver_{k}_push_points"] for k in (1, 2, 3)]})[::-1]
        bar = go.Figure(go.Bar(x=d["push"], y=d["driver"], orientation="h",
                               marker_color=[RED if v > 0 else BLUE for v in d["push"]],
                               text=[f"{v:+.2f} pts" for v in d["push"]], textposition="auto"))
        bar.update_layout(height=220, margin=dict(l=10, r=10, t=10, b=10), xaxis_title="push on the predicted change (points)")
        st.plotly_chart(bar, use_container_width=True)
        st.caption(f"Typical change {r['drivers_typical_change_pct']:+.2f}%, this market {r['drivers_model_change_pct']:+.2f}% "
                   "(driver model M5). Red pushes the price up, blue down. This explains what the model leans on, "
                   "not proof of cause and effect.")
    with right:
        st.markdown("#### Where to buy")
        w = rows[rows["where_to_buy_county"].notna()]
        if len(w):
            b = w.iloc[0]
            st.success(f"**{b['where_to_buy_county']}** ({b['where_to_buy_km']:.0f} km away): "
                       f"KES {b['where_to_buy_price_kes']:,.2f}/kg in {b['where_to_buy_price_month']}, "
                       f"**{b['where_to_buy_saving_pct']:.0f}% cheaper** than {county} "
                       f"(KES {b['where_to_buy_compared_with_kes']:,.2f}).")
            st.caption("Savings are before transport, handling and market fees: they pay off for a lorry load, not a few bags. "
                       "Distances are between county centres.")
        else:
            st.info("No suggestion. It needs an alert, a recorded price in both counties this month, and a county "
                    "within 200 km at least 5% cheaper (maize, sorghum, Rosecoco beans and red potatoes only).")

    with st.expander("ALPS score history for this market"):
        a = alps_history(series).dropna()
        a = a[a.index <= pd.Timestamp(origin)]
        af = go.Figure(go.Scatter(x=a.index, y=a.values, mode="lines", line=dict(color=INK)))
        for cut, name in [(0.25, "Stress"), (1, "Alert"), (2, "Crisis")]:
            af.add_hline(y=cut, line_dash="dot", line_color=PHASE_COLOUR[name], annotation_text=name)
        af.update_layout(height=280, margin=dict(l=10, r=10, t=10, b=10), yaxis_title="ALPS score")
        st.plotly_chart(af, use_container_width=True)


# --------------------------------------------------------------------------- tab 2: every alert this month
with tab_alerts:
    h = st.radio("Months ahead", [1, 2, 3], horizontal=True, key="alerts_h")
    view = result[result["horizon"] == h]
    a = view[view["alert"]]
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Markets forecast", f"{view['series'].nunique():,}")
    c2.metric("Spike alerts", f"{len(a):,}")
    c2.caption(f"{len(a) / len(view):.0%} of markets")
    c3.metric("ALPS Stress or worse", f"{view['phase'].isin(['Stress', 'Alert', 'Crisis']).sum():,}")
    c4.metric("Where to buy", f"{int(view['where_to_buy_county'].notna().sum()):,}", help="Cheaper-county suggestions")

    by_county = a.groupby("county").size().sort_values(ascending=True).tail(20)
    if len(by_county):
        cf = go.Figure(go.Bar(x=by_county.values, y=by_county.index, orientation="h", marker_color=RED))
        cf.update_layout(height=max(250, 22 * len(by_county)), margin=dict(l=10, r=10, t=30, b=10),
                         title="Counties with the most alerts", xaxis_title="alerts")
        st.plotly_chart(cf, use_container_width=True)

    pick = st.multiselect("Filter commodities", sorted(view["commodity"].unique()))
    if pick:
        a = a[a["commodity"].isin(pick)]
    show = a[["county", "commodity", "price_type", "origin_price_kes", "origin_price_is_real", "spike_probability_pct",
              "forecast_change_pct", "phase", "where_to_buy_county", "where_to_buy_saving_pct"]]
    show = show.sort_values("spike_probability_pct", ascending=False).rename(columns={
        "county": "County", "commodity": "Commodity", "price_type": "Type", "origin_price_kes": "Price (KES/kg)",
        "origin_price_is_real": "Recorded?", "spike_probability_pct": "Spike chance %",
        "forecast_change_pct": "Forecast change %", "phase": "ALPS", "where_to_buy_county": "Buy from",
        "where_to_buy_saving_pct": "Saving %"})
    st.dataframe(show, hide_index=True, use_container_width=True, height=420)

    st.download_button("Download all forecasts for this month (CSV)", result.to_csv(index=False).encode("utf-8-sig"),
                       file_name=f"sokoradar_{origin}.csv", mime="text/csv")


# --------------------------------------------------------------------------- tab 3: about
with tab_about:
    st.markdown(f"""
### What SokoRadar gives you
| Output | Question it answers |
|---|---|
| **Price forecast** (ARIMA) | Where is this price heading over the next 1 to 3 months? |
| **Price range** | How far could it be from the forecast? (80% range) |
| **Spike alert** (LightGBM, M8a) | Is a rise above 15% more likely than usual? |
| **ALPS label** | Is the price high for the season right now? (Normal, Stress, Alert, Crisis) |
| **Drivers** (M5 + SHAP) | What is pushing the forecast up or down? |
| **Where to buy** | Which nearby county is cheaper right now? |

### How well it works (backtest 2015 to 2024, recorded prices only)
* **Forecast:** average error 9.0% / 12.3% / 14.5% at 1 / 2 / 3 months, about level with "next month = this month".
* **Spike alert:** catches 48% of rises above 15% one month ahead; 22% of alerts are followed by a rise, about twice the normal rate.
* **Price ranges:** 78% to 82% of recorded prices fell inside on unseen years (target 75% to 85%).
* **Where to buy:** the suggested county was really cheaper in about 85% of backtest alerts, saving about 20% before transport.

### Limits
* An alert means **higher risk**, not a certain spike. About half of spikes come without one (floods, conflict, policy changes are not in the data).
* Only about 5% to 7% of prices were recorded in a market; the rest are estimates.
* The alert and driver models overfit their training years; the figures above are on unseen years, so they are the ones to trust.
* Drivers explain the model, not the market.
* Not yet tested on 2025 to 2026 prices. Weather and economy inputs end in Dec 2024.
* Models are trained on outcomes up to **{fc.TRAIN_END}**; settings are frozen in the handover scripts.

Group 10, Moringa School Data Science Capstone, 2026. Data: KAMIS, WFP via HDX (CC BY IGO), KNBS, Central Bank of Kenya, World Bank.
""")
