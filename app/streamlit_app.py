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
import json
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

APP = Path(__file__).resolve().parent
REPO = APP.parent
DATA = REPO / "data" / "SokoRadar_County_2006_2024_long.csv"
RAW = APP / "raw_data"                      # counties, climate, national drivers and county boundaries
HANDOVER = REPO / "notebooks" / "handover"

BLUE, RED, GREY, INK = "#2a6fdb", "#e34948", "#b9b8b3", "#1f1f1e"
PHASE_COLOUR = {"Normal": "#3a9a5b", "Stress": "#d9a400", "Alert": "#e07b26", "Crisis": "#c62f2f", "": "#8a8985"}
HIGH_PHASES = ["Alert", "Crisis"]

st.set_page_config(page_title="SokoRadar", page_icon="🌽", layout="wide")

st.markdown("""
<style>
.sr-hero {background: linear-gradient(110deg, #3b1d12 0%, #7a3417 55%, #b4481d 100%); color: #fff;
          border-radius: 14px; padding: 22px 30px; margin-bottom: 14px;}
.sr-hero .kicker {font-size: 0.78rem; letter-spacing: 0.08em; font-weight: 700; color: #ffd9a8; text-transform: uppercase;}
.sr-hero h1 {color: #fff; margin: 4px 0 6px 0; padding: 0; font-size: 2.2rem;}
.sr-hero p {color: #fbe9dc; margin: 0; font-size: 1.05rem;}
.sr-proof {background: rgba(224, 123, 38, 0.10); border-left: 5px solid #e07b26; border-radius: 8px;
           padding: 14px 20px; margin-bottom: 10px; font-size: 1.02rem; line-height: 1.55;}
.sr-date {display: inline-block; background: rgba(42, 111, 219, 0.10); border: 1px solid rgba(42, 111, 219, 0.35);
          border-radius: 999px; padding: 4px 14px; font-size: 0.9rem; margin-bottom: 10px;}
.sr-card {border: 1px solid rgba(128, 128, 128, 0.28); border-radius: 12px; padding: 14px 18px; height: 100%;}
.sr-card.red {border-top: 5px solid #c62f2f;} .sr-card.orange {border-top: 5px solid #e07b26;}
.sr-card .label {font-size: 0.92rem; opacity: 0.8;}
.sr-card .value {font-size: 2.1rem; font-weight: 700; line-height: 1.25;}
.sr-card .note {font-size: 0.85rem; opacity: 0.75;}
</style>
""", unsafe_allow_html=True)


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


@st.cache_data(show_spinner=False, max_entries=8)
def alps_phases(month: str) -> pd.Series:
    """ALPS label of every series in one month (used for the change since last month)."""
    scores = al.alps_scores(prices_for_alerts(), [pd.Timestamp(month)]).loc[pd.Timestamp(month)]
    return al.to_phase(scores)


@st.cache_data(show_spinner=False)
def alps_history(series: str) -> pd.Series:
    prices = prices_for_alerts()
    return al.alps_scores(prices[prices["series"] == series])[series]


@st.cache_data(show_spinner=False)
def county_shapes():
    geo = json.loads((RAW / "ken_counties.geojson").read_text(encoding="utf-8"))
    codes = pd.read_csv(RAW / "counties.csv")[["county", "pcode"]]
    return geo, dict(zip(codes["county"], codes["pcode"]))


# --------------------------------------------------------------------------- live markets: WFP recorded prices
LEDGER_KEYS = ["admin2", "market", "crop", "pricetype"]
COUNTY_ALIAS = {"ijara": "Garissa", "merunorth": "Meru", "merusouth": "Tharaka-Nithi", "moyale": "Marsabit"}  # as the pipeline


def ledger_alps_scores(price: pd.Series, min_obs: int = 36) -> pd.Series:
    """ALPS score per month, using a trend + season fit on earlier recorded months only (notebook 06, unchanged)."""
    price = price.astype(float)
    t = np.arange(len(price))
    month = price.index.month
    X = np.column_stack([np.ones(len(price)), t] + [(month == m).astype(float) for m in range(2, 13)])
    out = pd.Series(np.nan, index=price.index)
    use = price.notna().values
    for i in range(len(price)):
        past = np.where(use[:i])[0]
        if len(past) < min_obs or np.isnan(price.iloc[i]):
            continue
        beta, *_ = np.linalg.lstsq(X[past], price.values[past], rcond=None)
        resid = price.values[past] - X[past] @ beta
        out.iloc[i] = (price.iloc[i] - X[i] @ beta) / resid.std(ddof=X.shape[1])
    return out


@st.cache_data(show_spinner="Scoring WFP markets ...")
def live_markets() -> pd.DataFrame:
    """Every WFP market series with 37+ recorded months, scored month by month (notebook 06, step 3)."""
    led = pd.read_csv(RAW / "real_ledger.csv")
    names = {re.sub("[^a-z]", "", c.lower()): c for c in pd.read_csv(RAW / "counties.csv")["county"]}
    names.update(COUNTY_ALIAS)
    led["county"] = led["admin2"].map(lambda s: names.get(re.sub("[^a-z]", "", str(s).lower())))
    led["month"] = pd.PeriodIndex(led["month"], freq="M")
    mean = led.groupby(LEDGER_KEYS + ["county", "month"], as_index=False)["kes_kg"].mean()
    months = pd.period_range(mean["month"].min(), mean["month"].max(), freq="M")
    parts = []
    for key, g in mean.groupby(LEDGER_KEYS + ["county"]):
        price = g.set_index("month")["kes_kg"].reindex(months)
        if price.notna().sum() < 37:
            continue
        score = ledger_alps_scores(price)
        df = pd.DataFrame({"month": months, "price": price.values, "alps": score.values})
        recorded = pd.Series(months.astype(str), index=months).where(price.notna())
        df["last_price"] = price.ffill().shift(1).values                          # previous recorded price
        df["last_month"] = recorded.ffill().shift(1).values                       # and its month
        for k, v in zip(LEDGER_KEYS + ["county"], key):
            df[k] = v
        parts.append(df.dropna(subset=["alps"]))
    out = pd.concat(parts, ignore_index=True)
    out["phase"] = al.to_phase(out["alps"])
    out["month"] = out["month"].astype(str)
    return out


@st.cache_data(show_spinner=False)
def ledger_reporting() -> pd.DataFrame:
    led = pd.read_csv(RAW / "real_ledger.csv")
    return led.groupby(["month", "crop"]).agg(markets=("market", "nunique")).reset_index()


def card(col, label, value, note="", tone=""):
    col.markdown(f'<div class="sr-card {tone}"><div class="label">{label}</div>'
                 f'<div class="value">{value}</div><div class="note">{note}</div></div>', unsafe_allow_html=True)


def month_name(m: str) -> str:
    return pd.Timestamp(m).strftime("%B %Y")


def pct(x) -> str:
    """Signed percentage without a "-0.0%"."""
    return f"{round(float(x), 1) + 0.0:+.1f}%"


# --------------------------------------------------------------------------- sidebar
prices = prices_for_forecast()
latest = prices["month"].max()
UNIT = prices.drop_duplicates("commodity").set_index("commodity")["unit"].str.replace("KES/", "", regex=False).to_dict()
month_options = [f"{m:%Y-%m}" for m in pd.date_range(end=latest, periods=24, freq="MS")][::-1]

with st.sidebar:
    st.title("🌽 SokoRadar")
    st.caption("Early warning for food price shocks in Kenyan counties")
    origin = st.selectbox("Forecast from (origin month)", month_options, index=0, format_func=month_name,
                          help="The latest month is a real forecast. Earlier months are in-sample: "
                               f"the models learned outcomes up to {fc.TRAIN_END}.")
    st.divider()
    st.markdown("**Market check**")
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

# --------------------------------------------------------------------------- header, proof and date
targets = pd.date_range(pd.Timestamp(origin), periods=4, freq="MS")[1:]
st.markdown(f"""
<div class="sr-hero">
  <div class="kicker">Food price early warning · Kenya</div>
  <h1>SokoRadar</h1>
  <p>Where county food prices are heading over the next 3 months, and which markets need attention,
     for county teams, NDMA, aid agencies and traders.</p>
</div>
<div class="sr-proof">
  Tested year by year on <b>2015 to 2024</b> recorded prices it had never seen, SokoRadar's spike alert
  <b>caught 48% of price rises above 15% a month before they happened</b>, and after an alert a rise was
  <b>about twice as likely as usual</b> (22% vs 11%). Together with the seasonal ALPS label it warned of
  <b>84% of new seasonal alerts before they began</b> (347 cases).
</div>
<span class="sr-date">📅 Latest prices: <b>{month_name(origin)}</b> &nbsp;·&nbsp; forecasts for
  <b>{targets[0]:%b %Y} to {targets[-1]:%b %Y}</b></span>
""", unsafe_allow_html=True)

if origin == f"{latest:%Y-%m}":
    st.caption(f"The county price data currently ends in {month_name(origin)}. Newer months will appear once the "
               "price panel is rebuilt with 2025 to 2026 prices, after the team's sealed test.")
if origin < fc.TRAIN_END:
    st.warning(f"{month_name(origin)} is **in-sample**: the models learned what happened up to {fc.TRAIN_END}, "
               "so past alerts here look better than a fair test.", icon="⚠️")

with st.expander("How to use SokoRadar"):
    st.markdown("""
1. **This month** shows where to act: counties with spike alerts or prices that are already high for the season,
   a list of markets to watch, and a short bulletin per county you can copy into a report.
2. **Live markets (WFP)** uses newer recorded market prices (to September 2026) to show which markets are
   high for the season right now. It is a status check, not a forecast.
3. **Market check** looks at one market (choose the county, crop and retail or wholesale in the sidebar):
   its price history, the forecast with an 80% range, the spike alert, what drives the forecast and where to buy.
4. **Does it work?** shows how well each part did on years the models had never seen.
5. Read a **spike alert** as "higher risk than usual", not "a spike is coming". Read the **ALPS label** as
   "high for the season right now". They answer different questions, so a market can have one without the other.
""")

with st.spinner(f"Running the SokoRadar models from {month_name(origin)} "
                "(the first run takes 2 to 3 minutes; then it is cached) ..."):
    result = run_models(origin)

tab_month, tab_live, tab_market, tab_proof, tab_about = st.tabs(
    ["📍 This month", "🛰️ Live markets (WFP)", "📈 Market check", "✅ Does it work?", "ℹ️ About & limits"])


# --------------------------------------------------------------------------- tab 1: this month, where to act
with tab_month:
    f1, f2, f3 = st.columns([2, 2, 3])
    crops = ["All crops"] + sorted(result["commodity"].unique())
    crop = f1.selectbox("Crop", crops, key="crop")
    window = f2.radio("Spike alerts for", ["Next month", "Next 3 months"], key="window",
                      help="Next month: alerts 1 month ahead (the most reliable). Next 3 months: an alert at 1, 2 or 3 "
                           "months ahead, which flags many more markets.")
    kind = f3.radio("Show on the map", ["Spike alerts", "Seasonal label: Alert or Crisis"], key="kind")
    max_h = 1 if window == "Next month" else 3
    when = targets[0].strftime("%b %Y") if max_h == 1 else f"{targets[0]:%b} to {targets[-1]:%b %Y}"

    view = result if crop == "All crops" else result[result["commodity"] == crop]
    markets = view.drop_duplicates("series").set_index("series")
    in_window = view[view["horizon"] <= max_h]
    alerted = in_window.groupby("series")["alert"].any().reindex(markets.index, fill_value=False)
    first_alert = in_window[in_window["alert"]].groupby("series")["horizon"].min()
    high_now = markets["phase"].isin(HIGH_PHASES)
    both = alerted & high_now

    prev = f"{pd.Timestamp(origin) - pd.DateOffset(months=1):%Y-%m}"
    prev_phase = alps_phases(prev).reindex(markets.index)
    high_before = int(prev_phase.isin(HIGH_PHASES).sum())

    c1, c2, c3, c4 = st.columns(4)
    card(c1, "Markets forecast", f"{len(markets):,}", f"county × crop × retail/wholesale, {month_name(origin)}")
    card(c2, "Seasonal label: Alert or Crisis", f"{int(high_now.sum()):,}",
         f"high for the season (context) · {int(high_now.sum()) - high_before:+d} vs last month", "red")
    card(c3, f"Spike alerts, {when}", f"{int(alerted.sum()):,}",
         "markets with a higher risk of a rise above 15%", "orange")
    card(c4, "Spike alert, already high", f"{int(both.sum()):,}",
         f"spike alert and seasonal label Alert or Crisis · {markets.loc[both, 'county'].nunique()} counties", "red")
    st.caption("**One alert, one label, one range.** The **spike alert** is SokoRadar's only alert: a rise above 15% "
               "is more likely than usual. The **seasonal label** (ALPS: Normal, Stress, Alert, Crisis) says how high "
               "the price already is for the time of year; it is context, not an alert. The **price range** shows how "
               "far the price could move from the forecast.")
    st.write("")

    t_map, t_list, t_bulletin = st.tabs(["Map", "Action list", "County bulletin"])

    with t_map:
        geo, pcode_of = county_shapes()
        by_county = pd.DataFrame({
            "county": markets["county"],
            "alert": alerted.reindex(markets.index, fill_value=False).values,
            "high": high_now.values,
        }).groupby("county").agg(markets=("alert", "size"), alerts=("alert", "sum"), high=("high", "sum"))
        value_col = "alerts" if kind.startswith("Spike") else "high"
        by_county["pcode"] = by_county.index.map(pcode_of)
        by_county = by_county.dropna(subset=["pcode"])
        colour = [[0, "#f3efe8"], [0.001, "#fbd8b8"], [0.5, "#e07b26"], [1, "#9b2a1a"]]
        fig = go.Figure(go.Choropleth(
            geojson=geo, featureidkey="properties.pcode", locations=by_county["pcode"],
            z=by_county[value_col], colorscale=colour, zmin=0, zmax=max(1, by_county[value_col].max()),
            marker_line_color="white", marker_line_width=0.8,
            customdata=np.stack([by_county.index, by_county["alerts"], by_county["high"], by_county["markets"]], axis=1),
            hovertemplate="<b>%{customdata[0]}</b><br>Spike alerts: %{customdata[1]} of %{customdata[3]} markets"
                          "<br>Seasonal label Alert or Crisis: %{customdata[2]}<extra></extra>",
            colorbar=dict(title="markets", thickness=12, len=0.6)))
        fig.update_geos(visible=False, projection_type="mercator",
                        lonaxis_range=[33.6, 42.2], lataxis_range=[-4.9, 5.2])
        fig.update_layout(height=560, margin=dict(l=0, r=0, t=10, b=0), paper_bgcolor="rgba(0,0,0,0)",
                          geo=dict(bgcolor="rgba(0,0,0,0)"))
        st.plotly_chart(fig, use_container_width=True, config={"scrollZoom": False})
        st.caption("Number of markets per county "
                   + (f"with a spike alert for {when}." if value_col == "alerts"
                      else "whose seasonal label is Alert or Crisis (context, not an alert).")
                   + " Hover over a county for both counts.")

    with t_list:
        watch = markets.assign(
            alert=alerted.reindex(markets.index, fill_value=False),
            first=first_alert.reindex(markets.index),
            chance=in_window.groupby("series")["spike_probability_pct"].max().reindex(markets.index),
            buy=view.dropna(subset=["where_to_buy_county"]).groupby("series")["where_to_buy_county"].first()
                .reindex(markets.index),
            saving=view.dropna(subset=["where_to_buy_county"]).groupby("series")["where_to_buy_saving_pct"].first()
                .reindex(markets.index),
        )
        watch = watch[watch["alert"] | watch["phase"].isin(HIGH_PHASES)].copy()
        if watch.empty:
            st.success("No market has a spike alert or a high seasonal price this month.")
        else:
            def why(r):
                parts = []
                if r["alert"]:
                    parts.append("spike alert for next month" if r["first"] == 1
                                 else f"spike alert in {int(r['first'])} months")
                if r["phase"] in HIGH_PHASES:
                    parts.append(f"seasonal label {r['phase']}")
                return "; ".join(parts)
            watch["priority"] = watch["alert"].astype(int) + watch["phase"].isin(HIGH_PHASES).astype(int) * 2 \
                + (watch["phase"] == "Crisis").astype(int)
            watch = watch.sort_values(["priority", "chance"], ascending=False)
            table = pd.DataFrame({
                "County": watch["county"], "Crop": watch["commodity"], "Type": watch["price_type"],
                "Price (KES)": watch["origin_price_kes"].round(1),
                "per": watch["commodity"].map(UNIT),
                "Recorded?": np.where(watch["origin_price_is_real"], "yes", "estimated"),
                "Why it is listed": watch.apply(why, axis=1),
                "Highest spike chance": watch["chance"].map("{:.0f}%".format),
                "Where to buy": [f"{b} ({s:.0f}% cheaper)" if isinstance(b, str) else "" for b, s
                                 in zip(watch["buy"], watch["saving"])],
            })
            st.markdown(f"**{len(table):,} markets to watch**, most urgent first: a high seasonal price and a spike alert "
                        "together come first.")
            st.dataframe(table, hide_index=True, use_container_width=True, height=460)
            st.download_button("Download the action list (CSV)", table.to_csv(index=False).encode("utf-8-sig"),
                               file_name=f"sokoradar_action_list_{origin}.csv", mime="text/csv")

    with t_bulletin:
        b_county = st.selectbox("County", sorted(markets["county"].unique()), key="b_county",
                                index=sorted(markets["county"].unique()).index(county)
                                if county in set(markets["county"]) else 0)
        cm = markets[markets["county"] == b_county]
        c_alert = alerted.reindex(cm.index, fill_value=False)
        lines = [f"SokoRadar bulletin: {b_county} county, prices of {month_name(origin)}"
                 + ("" if crop == "All crops" else f", {crop}"), ""]
        lines.append(f"{len(cm)} markets checked. {int(c_alert.sum())} with a spike alert for {when}; "
                     f"{int(cm['phase'].isin(HIGH_PHASES).sum())} with a seasonal label of Alert or Crisis (high for the time of year).")
        for s, r in cm[c_alert | cm["phase"].isin(HIGH_PHASES)].iterrows():
            rr = view[view["series"] == s].sort_values("horizon")
            bits = []
            if c_alert[s]:
                chance = rr.loc[rr["horizon"] <= max_h, "spike_probability_pct"].max()
                bits.append(f"spike alert (chance of a rise above 15% up to {chance:.0f}%)")
            if r["phase"] in HIGH_PHASES:
                bits.append(f"seasonal label {r['phase']}")
            f3 = rr.iloc[-1]
            bits.append(f"forecast KES {f3['forecast_price_kes']:,.1f}/{UNIT[r['commodity']]} in "
                        f"{pd.Timestamp(f3['target_month']):%b %Y} ({pct(f3['forecast_change_pct'])}, range {f3['range_low_kes']:,.1f} to {f3['range_high_kes']:,.1f})")
            w = rr.dropna(subset=["where_to_buy_county"])
            if len(w):
                bits.append(f"cheaper in {w.iloc[0]['where_to_buy_county']} "
                            f"({w.iloc[0]['where_to_buy_saving_pct']:.0f}% less, before transport)")
            lines.append(f"- {r['commodity']} ({r['price_type'].lower()}), KES {r['origin_price_kes']:,.1f}/{UNIT[r['commodity']]}: "
                         + "; ".join(bits) + ".")
        if len(lines) == 3:
            lines.append("- No market needs attention this month.")
        lines += ["", "An alert means a higher risk of a price rise, not a certain one. About half of price spikes "
                      "come without an alert. Most county prices are estimates."]
        bulletin = "\n".join(lines)
        st.text_area("Copy this into a report or message", bulletin, height=320)
        st.download_button("Download the bulletin (TXT)", bulletin.encode("utf-8"),
                           file_name=f"sokoradar_{b_county}_{origin}.txt".replace(" ", "_"), mime="text/plain")

    st.download_button("Download all forecasts for this month (CSV)", result.to_csv(index=False).encode("utf-8-sig"),
                       file_name=f"sokoradar_{origin}.csv", mime="text/csv", key="dl_all")


# --------------------------------------------------------------------------- tab 2: live markets (WFP recorded prices)
with tab_live:
    live = live_markets()
    live_months = sorted(live["month"].unique(), reverse=True)
    st.markdown("Recorded WFP market prices, newer than the county forecasts: **is the price high for the season "
                "right now?** This is the seasonal (ALPS) label, which is context, not an alert. Each market is compared with its own normal level for that time of year, learned from "
                "its earlier recorded months (the ALPS method of notebook 06). Only markets that reported a price "
                "that month are shown.")
    l1, l2 = st.columns(2)
    l_month = l1.selectbox("Month", live_months, index=0, format_func=month_name, key="l_month")
    l_crop = l2.selectbox("Crop", ["All crops", "Maize", "Beans", "Sorghum", "Potatoes"], key="l_crop")
    lv = live if l_crop == "All crops" else live[live["crop"] == l_crop]
    now = lv[lv["month"] == l_month]
    l_prev = f"{pd.Period(l_month, 'M') - 1}"
    before = lv[lv["month"] == l_prev]
    hi_now, hi_before = int(now["phase"].isin(HIGH_PHASES).sum()), int(before["phase"].isin(HIGH_PHASES).sum())
    rep = ledger_reporting()
    rep = rep[rep["month"] == l_month] if l_crop == "All crops" else rep[(rep["month"] == l_month) & (rep["crop"] == l_crop)]

    k1, k2, k3, k4 = st.columns(4)
    card(k1, "Markets scored", f"{len(now):,}",
         f"recorded prices, {month_name(l_month)} · {int(rep['markets'].sum())} market reports in all")
    card(k2, "Seasonal label: Alert or Crisis", f"{hi_now:,}", f"{hi_now - hi_before:+d} vs {month_name(l_prev)}", "red")
    card(k3, "In Stress", f"{int((now['phase'] == 'Stress').sum()):,}", "above normal for the season, may reach Alert",
         "orange")
    card(k4, "Counties with label Alert or Crisis", f"{now.loc[now['phase'].isin(HIGH_PHASES), 'county'].nunique()}",
         f"of {now['county'].nunique()} {'county' if now['county'].nunique() == 1 else 'counties'} reporting")
    st.write("")

    if now.empty:
        st.info("No market reported enough recorded prices for this month and crop.")
    else:
        geo, pcode_of = county_shapes()
        rank = {p: i for i, p in enumerate(al.PHASES)}
        worst = (now.assign(r=now["phase"].map(rank)).groupby("county")
                 .agg(r=("r", "max"), markets=("market", "nunique"),
                      high=("phase", lambda s: int(s.isin(HIGH_PHASES).sum()))))
        worst["pcode"] = worst.index.map(pcode_of)
        worst = worst.dropna(subset=["pcode"])
        all_codes = list(pcode_of.values())
        steps = [PHASE_COLOUR[p] for p in al.PHASES]
        scale = [[0, steps[0]], [0.25, steps[0]], [0.25, steps[1]], [0.5, steps[1]],
                 [0.5, steps[2]], [0.75, steps[2]], [0.75, steps[3]], [1, steps[3]]]
        lf = go.Figure()
        lf.add_trace(go.Choropleth(geojson=geo, featureidkey="properties.pcode", locations=all_codes,
                                   z=[0] * len(all_codes), colorscale=[[0, "#e4e2dc"], [1, "#e4e2dc"]],
                                   showscale=False, marker_line_color="white", marker_line_width=0.8,
                                   hoverinfo="skip"))
        lf.add_trace(go.Choropleth(
            geojson=geo, featureidkey="properties.pcode", locations=worst["pcode"], z=worst["r"] + 0.5,
            zmin=0, zmax=4, colorscale=scale, marker_line_color="white", marker_line_width=0.8,
            customdata=np.stack([worst.index, worst["r"].map(dict(enumerate(al.PHASES))), worst["markets"],
                                 worst["high"]], axis=1),
            hovertemplate="<b>%{customdata[0]}</b><br>Worst: %{customdata[1]}<br>Markets reporting: "
                          "%{customdata[2]}<br>In Alert or Crisis: %{customdata[3]}<extra></extra>",
            colorbar=dict(title="worst phase", tickvals=[0.5, 1.5, 2.5, 3.5], ticktext=al.PHASES,
                          thickness=12, len=0.6)))
        lf.update_geos(visible=False, projection_type="mercator", lonaxis_range=[33.6, 42.2],
                       lataxis_range=[-4.9, 5.2])
        lf.update_layout(height=520, margin=dict(l=0, r=0, t=10, b=0), paper_bgcolor="rgba(0,0,0,0)",
                         geo=dict(bgcolor="rgba(0,0,0,0)"))
        st.plotly_chart(lf, use_container_width=True, config={"scrollZoom": False})
        st.caption("Each county shows its worst-placed reporting market. Grey counties had no market with enough "
                   "recorded prices this month, so no label is shown for them.")

        order = {"Crisis": 0, "Alert": 1, "Stress": 2, "Normal": 3}
        show = now.assign(o=now["phase"].map(order)).sort_values(["o", "alps"], ascending=[True, False])
        change = (show["price"] / show["last_price"] - 1) * 100
        st.dataframe(pd.DataFrame({
            "County": show["county"], "Market": show["market"], "Crop": show["crop"], "Type": show["pricetype"],
            "Price (KES/kg)": show["price"].round(1), "Seasonal label": show["phase"],
            "ALPS score": show["alps"].round(2),
            "Change since last report": [f"{pct(c)} (since {pd.Timestamp(m):%b %Y})" if pd.notna(c) and isinstance(m, str)
                                         else "" for c, m in zip(change, show["last_month"])],
        }), hide_index=True, use_container_width=True, height=420)
        st.download_button("Download this list (CSV)", show.to_csv(index=False).encode("utf-8-sig"),
                           file_name=f"sokoradar_live_markets_{l_month}.csv", mime="text/csv")

    st.caption("This view says where prices are **high now**; it is not a forecast. For a 3-month early warning on "
               "these WFP markets, see the team's notebook 06 model in the "
               "[SokoRadar alerts app](https://sokoradar-alerts-gcrnsb8tpndernksznsyws.streamlit.app/). "
               "Data: WFP market prices via HDX (CC BY IGO), maize, beans, sorghum and potatoes.")


# --------------------------------------------------------------------------- tab 3: one market
with tab_market:
    series = f"{county} | {commodity} | {price_type}"
    rows = result[result["series"] == series].sort_values("horizon")
    st.subheader(series)
    st.caption("Choose another market in the sidebar.")
    if rows.empty:
        st.info("No forecast for this series and month.")
    else:
        first = rows.iloc[0]
        u = UNIT.get(commodity, "kg")
        phase = first["phase"] if isinstance(first["phase"], str) else ""

        c1, c2, c3, c4 = st.columns(4)
        c1.metric(f"Price in {pd.Timestamp(origin):%b %Y} (KES/{u})", f"{first['origin_price_kes']:,.1f}",
                  help="Recorded in a market" if first["origin_price_is_real"] else "Estimated by the data pipeline")
        c1.caption("✅ recorded in a market" if first["origin_price_is_real"] else "≈ estimated price")
        c2.metric("Seasonal label (ALPS)", phase or "n/a")
        score = f"Score {first['alps_score']:.2f}. " if pd.notna(first["alps_score"]) else ""
        c2.caption(score + (first["phase_message"] if isinstance(first["phase_message"], str) and first["phase_message"]
                            else "Price compared with its normal level for the season"))
        n_alerts = int(rows["alert"].sum())
        c3.metric("Spike alerts", f"{n_alerts} of 3", help="Alerts at 1, 2 and 3 months ahead")
        c3.caption("Higher risk of a rise above 15%" if n_alerts else "No alert: risk not above usual")
        c4.metric(f"In {pd.Timestamp(rows.iloc[-1]['target_month']):%b %Y} (KES/{u})",
                  f"{rows.iloc[-1]['forecast_price_kes']:,.1f}",
                  pct(rows.iloc[-1]["forecast_change_pct"]), delta_color="inverse")

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
                                 mode="lines+markers", line=dict(color=BLUE, dash="dash", width=2),
                                 name="forecast (ARIMA)"))
        alerted_rows = rows[rows["alert"]]
        if len(alerted_rows):
            fig.add_trace(go.Scatter(x=pd.to_datetime(alerted_rows["target_month"]), y=alerted_rows["forecast_price_kes"],
                                     mode="markers", marker=dict(color=RED, size=13, symbol="triangle-up"),
                                     name="spike alert"))
        fig.update_layout(height=420, margin=dict(l=10, r=10, t=10, b=10), yaxis_title=f"KES per {u}",
                          legend=dict(orientation="h", y=-0.15), hovermode="x unified")
        st.plotly_chart(fig, use_container_width=True)

        # table per horizon
        table = pd.DataFrame({
            "Months ahead": rows["horizon"].values,
            "Month": pd.to_datetime(rows["target_month"]).dt.strftime("%b %Y").values,
            f"Forecast (KES/{u})": rows["forecast_price_kes"].values,
            "Change": rows["forecast_change_pct"].map(pct).values,
            f"80% range (KES/{u})": [f"{lo:,.2f} to {hi:,.2f}" for lo, hi in zip(rows["range_low_kes"], rows["range_high_kes"])],
            "Spike chance": rows["spike_probability_pct"].map("{:.1f}%".format).values,
            "Alert above": rows["alert_threshold_pct"].map("{:.1f}%".format).values,
            "Alert": np.where(rows["alert"], "🚨 higher risk", "—"),
        })
        st.dataframe(table, hide_index=True, use_container_width=True)
        st.caption("The forecast and the alert come from different models on purpose: the forecast is the most likely "
                   "path, the alert says the chance of a big rise is higher than usual. A flat forecast can sit next "
                   "to an alert.")

        left, right = st.columns([3, 2])
        with left:
            st.markdown("#### What moves the forecast")
            h = st.radio("Horizon", [1, 2, 3], horizontal=True,
                         format_func=lambda k: f"{k} month{'s' if k > 1 else ''}", key="driver_h")
            r = rows[rows["horizon"] == h].iloc[0]
            d = pd.DataFrame({"driver": [r[f"driver_{k}"] for k in (1, 2, 3)],
                              "push": [r[f"driver_{k}_push_points"] for k in (1, 2, 3)]})[::-1]
            bar = go.Figure(go.Bar(x=d["push"], y=d["driver"], orientation="h",
                                   marker_color=[RED if v > 0 else BLUE for v in d["push"]],
                                   text=[f"{v:+.2f} pts" for v in d["push"]], textposition="auto"))
            bar.update_layout(height=220, margin=dict(l=10, r=10, t=10, b=10),
                              xaxis_title="push on the predicted change (points)")
            st.plotly_chart(bar, use_container_width=True)
            st.caption(f"Typical change {r['drivers_typical_change_pct']:+.2f}%, this market "
                       f"{r['drivers_model_change_pct']:+.2f}% (driver model M5). Red pushes the price up, blue down. "
                       "This explains what the model leans on, not proof of cause and effect.")
        with right:
            st.markdown("#### Where to buy")
            w = rows[rows["where_to_buy_county"].notna()]
            if len(w):
                b = w.iloc[0]
                st.success(f"**{b['where_to_buy_county']}** ({b['where_to_buy_km']:.0f} km away): "
                           f"KES {b['where_to_buy_price_kes']:,.2f}/{u} in {b['where_to_buy_price_month']}, "
                           f"**{b['where_to_buy_saving_pct']:.0f}% cheaper** than {county} "
                           f"(KES {b['where_to_buy_compared_with_kes']:,.2f}).")
                st.caption("Savings are before transport, handling and market fees. In the backtest a full load of "
                           "5 t or more still saved money in 68% to 85% of cases; small loads rarely did. "
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


# --------------------------------------------------------------------------- tab 3: does it work?
with tab_proof:
    st.markdown("Every figure comes from a **year-by-year test on 2015 to 2024**: each year was predicted using only "
                "earlier years, and only **prices recorded in a market** were used to score it.")
    p1, p2, p3 = st.columns(3)
    card(p1, "Spike alert, 1 month ahead", "48%", "of price rises above 15% were caught", "orange")
    card(p2, "After an alert", "2×", "a rise was about twice as likely as usual (22% vs 11%)", "orange")
    card(p3, "New seasonal alerts warned early", "84%",
         "by the spike alert or the ALPS Stress label, of 347 cases", "red")
    st.write("")
    p4, p5, p6 = st.columns(3)
    card(p4, "Price forecast error", "9.0%", "average at 1 month (12.3% at 2, 14.5% at 3)")
    card(p5, "Price ranges", "78–82%", "of recorded prices fell inside the 80% range")
    card(p6, "Where to buy", "85%", "of suggestions were really cheaper a month later, saving about 20% before transport")
    st.write("")
    st.markdown("""
| Part | 1 month | 2 months | 3 months |
|---|---|---|---|
| Rises above 15% caught by the spike alert | 48% | 45% | 34% |
| Alerts followed by a rise above 15% | 22% | 32% | 39% |
| Calm months left quiet | 80% | 81% | 86% |
| Average forecast error | 9.0% | 12.3% | 14.5% |
| Recorded prices inside the 80% range | 78% | 80% | 82% |

**New seasonal alerts** (a market moving into ALPS Alert after 3 calm months, 347 cases): the spike alert warned of
51%, about 2 months ahead; the ALPS Stress label warned of 63%; together 84%.

**Where to buy after transport:** a full load of 5 to 7 t still saved money in 68% of suggestions, 12 t in 83% and
20 t in 85%. A 1 t pickup saved money in only 29%, and small loads almost never.

**What it can't do:** about half of price spikes come without an alert, because many are caused by events the data
cannot see (floods, conflict, policy changes). The price forecast is about level with "next month = this month";
the value is in the alert, the range and the where-to-buy advice.

These results were re-run and reproduced from the team's notebooks (02, 05 and 07) and handover scripts.
""")


# --------------------------------------------------------------------------- tab 4: about
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

### Limits
* An alert means **higher risk**, not a certain spike. About half of spikes come without one, because many are caused
  by events the data cannot see (floods, conflict, policy changes).
* **The seasonal label says "high for the season", not "a spike is coming".** The spike alert answers that question.
  SokoRadar has one alert (the spike alert), one label (ALPS) and one range, as set in the team's alerts notebook.
* The price range width was learned at the 85th percentile of past misses, because a first test at 80% gave too little
  coverage in recent, more volatile years.
* Only about 5% to 7% of prices were recorded in a market; the rest are estimates.
* The county price data ends in **{month_name(f"{latest:%Y-%m}")}**. 2025 to 2026 prices are kept for the team's
  sealed final test and will be added after it.
* The alert and driver models overfit their training years; the figures in **Does it work?** are on unseen years,
  so they are the ones to trust.
* Drivers explain the model, not the market. Weather and economy inputs end in Dec 2024.
* Alert thresholds are frozen (set so alerts fire in 20% of calm months on 2011 to 2014) and are not adjustable here.
* Models are trained on outcomes up to **{fc.TRAIN_END}**; settings are frozen in the handover scripts.

Group 10, Moringa School Data Science Capstone, 2026. Data: KAMIS, WFP via HDX (CC BY IGO), KNBS, Central Bank of Kenya, World Bank.
""")
