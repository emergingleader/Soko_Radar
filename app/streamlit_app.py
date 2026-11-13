"""SokoRadar food price forecasts for Kenyan counties.

The forecasts come from the handover scripts in notebooks/handover (price forecast, spike alert, where to buy,
seasonal label and price range). They are loaded as they are. Transport costs come from app/transport.py.

Run from the repo folder:
    pip install -r app/requirements.txt
    streamlit run app/streamlit_app.py
"""
import importlib.util
import io
import json
import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

APP = Path(__file__).resolve().parent
REPO = APP.parent
DATA = REPO / "data" / "SokoRadar_County_2006_2024_long.csv"
RAW = APP / "raw_data"
HANDOVER = REPO / "notebooks" / "handover"

BLUE, RED, GREY, INK = "#2a6fdb", "#e34948", "#b9b8b3", "#1f1f1e"
# short seasonal labels for the list on the map tab; the full messages come from the alerts script
SEASON_SHORT = {"Normal": "Normal", "Stress": "Above normal", "Alert": "Unusually high", "Crisis": "Very high"}

st.set_page_config(page_title="SokoRadar", layout="wide")
st.markdown("""
<style>
.sr-card {border: 1px solid rgba(128,128,128,0.3); border-radius: 12px; padding: 14px 18px;}
.sr-card.warn {border-top: 6px solid #e34948;}
.sr-card .m {font-size: 1rem; font-weight: 600; opacity: 0.85;}
.sr-card .p {font-size: 2.2rem; font-weight: 700; line-height: 1.2;}
.sr-card .c {font-size: 1rem;}
.sr-card .r {font-size: 0.9rem; opacity: 0.75;}
.sr-card .a {font-size: 0.95rem; font-weight: 600; color: #e34948; margin-top: 4px;}
</style>
""", unsafe_allow_html=True)


# Models and data (cached)
@st.cache_resource
def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


fc = load_module("sokoradar_forecast", HANDOVER / "sokoradar_forecast.py")
al = load_module("sokoradar_alerts", HANDOVER / "alerts" / "sokoradar_alerts.py")
tp = load_module("sokoradar_transport", APP / "transport.py")


def safely(fn, *args):
    try:
        return fn(*args)
    except SystemExit as e:
        st.error(f"SokoRadar stopped: {e}")
        st.stop()


@st.cache_resource
def prices_file() -> Path:
    """The team's 2006-2024 county prices plus the newer months built by the same pipeline (app/update_prices.py)."""
    newer = RAW / "prices_after_2024.csv"
    if not newer.exists():
        return DATA
    path = Path(tempfile.gettempdir()) / "sokoradar_prices_2006_latest.csv"
    pd.concat([pd.read_csv(DATA), pd.read_csv(newer)]).to_csv(path, index=False)
    return path


@st.cache_data(show_spinner=False)
def load_prices():
    path = prices_file()
    return safely(fc.load_prices, path), safely(al.load_prices, path)


@st.cache_data(show_spinner=False, max_entries=2)
def run_models(origin: str) -> pd.DataFrame:
    p_fc, p_al = load_prices()
    month = pd.Timestamp(origin)
    out = safely(fc.run, p_fc, RAW, [month], fc.TRAIN_END)
    ranges = safely(al.run, p_al, [month], io.StringIO(out.to_csv(index=False)))
    key = ["series", "origin_month", "horizon"]
    return out.merge(ranges[key + ["phase", "phase_message", "range_low_kes", "range_high_kes"]], on=key, how="left")


@st.cache_data(show_spinner=False)
def transport_inputs():
    return tp.load_inputs()


@st.cache_data(show_spinner=False)
def county_shapes():
    geo = json.loads((RAW / "ken_counties.geojson").read_text(encoding="utf-8"))
    codes = pd.read_csv(RAW / "counties.csv")[["county", "pcode"]]
    return geo, dict(zip(codes["county"], codes["pcode"]))


def season_text(row):
    """The alerts script's message for the seasonal label (it has none for Normal)."""
    msg = row.get("phase_message")
    return msg if isinstance(msg, str) and msg else "Normal for the season"


# Latest prices and forecasts
prices, _ = load_prices()
latest = prices["month"].max()
origin = f"{latest:%Y-%m}"
UNIT = prices.drop_duplicates("commodity").set_index("commodity")["unit"].str.replace("KES/", "", regex=False).to_dict()
with st.spinner("Preparing the forecasts. The first visit takes 2 to 3 minutes."):
    result = run_models(origin)
months = [pd.Timestamp(m) for m in sorted(result["target_month"].unique())]

# Header and market choice
st.title("SokoRadar")
start = f"{months[0]:%B %Y}" if months[0].year != months[-1].year else f"{months[0]:%B}"
st.markdown(f"Food price forecast for Kenyan counties. Latest prices: {latest:%B %Y}. "
            f"Forecast: {start} to {months[-1]:%B %Y}.")
if (pd.Timestamp.today().to_period("M") - latest.to_period("M")).n > 2:
    st.caption(f"Newer prices have not been added yet, so this forecast starts from {latest:%B %Y}.")

with st.sidebar:
    st.header("Choose a market")
    counties = sorted(prices["county"].unique())
    county = st.selectbox("County", counties, index=counties.index("Nakuru"))
    here = prices[prices["county"] == county]
    crops = sorted(here["commodity"].unique())
    crop = st.selectbox("Food", crops, index=crops.index("Dry Maize") if "Dry Maize" in crops else 0)
    types = sorted(here.loc[here["commodity"] == crop, "price_type"].unique())
    price_type = st.radio("Price", types, horizontal=True)

tab_market, tab_map = st.tabs(["Price forecast", "Where prices may jump"])

# Tab 1: one market
with tab_market:
    rows = result[(result["county"] == county) & (result["commodity"] == crop)
                  & (result["price_type"] == price_type)].sort_values("horizon")
    u = UNIT.get(crop, "kg")
    first = rows.iloc[0]
    st.subheader(f"{crop}, {county} ({price_type.lower()})")
    st.markdown(f"Price in {latest:%B}: KES {first['origin_price_kes']:,.1f} per {u}"
                + ("" if first["origin_price_is_real"] else " (estimate)")
                + (f". {season_text(first)}." if isinstance(first["phase"], str) and first["phase"] else "."))

    cols = st.columns(3)
    for col, (_, r) in zip(cols, rows.iterrows()):
        warn = bool(r["alert"])
        change = r["forecast_change_pct"]
        col.markdown(
            f'<div class="sr-card {"warn" if warn else ""}">'
            f'<div class="m">{pd.Timestamp(r["target_month"]):%B %Y}</div>'
            f'<div class="p">KES {r["forecast_price_kes"]:,.1f}</div>'
            f'<div class="c">{round(change, 1) + 0.0:+.1f}% from now</div>'
            f'<div class="r">likely between {r["range_low_kes"]:,.0f} and {r["range_high_kes"]:,.0f}</div>'
            + ('<div class="a">Price may jump more than 15%</div>' if warn else "")
            + "</div>", unsafe_allow_html=True)
    st.write("")

    hist = prices[(prices["series"] == first["series"])].tail(36)
    tm = pd.to_datetime(rows["target_month"])
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=[latest, *tm, *tm[::-1], latest],
                             y=[first["origin_price_kes"], *rows["range_high_kes"], *rows["range_low_kes"][::-1],
                                first["origin_price_kes"]],
                             mode="lines", fill="toself", fillcolor="rgba(42,111,219,0.15)", line=dict(width=0),
                             name="likely range", hoverinfo="skip"))
    fig.add_trace(go.Scatter(x=hist["month"], y=hist["price_kes"], mode="lines", line=dict(color=GREY, width=2.5),
                             name="past price"))
    fig.add_trace(go.Scatter(x=[latest, *tm], y=[first["origin_price_kes"], *rows["forecast_price_kes"]],
                             mode="lines+markers", line=dict(color=BLUE, dash="dash", width=3), name="forecast"))
    jumps = rows[rows["alert"]]
    if len(jumps):
        fig.add_trace(go.Scatter(x=pd.to_datetime(jumps["target_month"]), y=jumps["forecast_price_kes"],
                                 mode="markers", marker=dict(color=RED, size=14, symbol="triangle-up"),
                                 name="may jump"))
    fig.update_layout(height=380, margin=dict(l=10, r=10, t=10, b=10), yaxis_title=f"KES per {u}",
                      legend=dict(orientation="h", y=-0.15), hovermode="x unified")
    st.plotly_chart(fig, use_container_width=True)

    # where to buy cheaper: recorded prices in nearby counties (the handover rule uses recorded prices only)
    st.markdown("#### Where to buy cheaper")
    if crop not in fc.RECOMMEND_CROPS:
        st.info("Available for maize, sorghum, Rosecoco beans and red potatoes.")
    else:
        inputs = transport_inputs()
        pairs = inputs[3]
        nearby = pairs[pairs["county_a"] == county][["county_b", "road_km"]]
        rec = prices[(prices["month"] == latest) & prices["observed"] & (prices["commodity"] == crop)
                     & (prices["price_type"] == price_type)]
        near = (nearby.merge(rec[["county", "price_kes"]], left_on="county_b", right_on="county")
                .drop(columns="county").rename(columns={"price_kes": "price"}).sort_values("price"))
        # compare only with a price recorded in this county (the model card: estimated prices are not used,
        # because they are partly copied from neighbouring counties)
        local = float(first["origin_price_kes"]) if first["origin_price_is_real"] else None
        w = rows[rows["where_to_buy_county"].notna()]
        if len(w):                                            # the official suggestion (after a jump warning)
            b = w.iloc[0]
            local = float(b["where_to_buy_compared_with_kes"])
            st.success(f"Buy in {b['where_to_buy_county']}: KES {b['where_to_buy_price_kes']:,.1f} per {u}, "
                       f"{b['where_to_buy_saving_pct']:.0f}% less than in {county}.")
        if near.empty:
            st.info(f"No nearby county reported a {price_type.lower()} price for this food in {latest:%B %Y}.")
        else:
            table = {"Nearby county": near["county_b"],
                     f"Price {latest:%b %Y} (KES per {u})": near["price"].round(1)}
            if local is not None:
                table[f"Compared with {county}"] = [f"{(p / local - 1) * 100:+.0f}%" for p in near["price"]]
            table["Distance (km)"] = near["road_km"].round(0).astype(int)
            st.dataframe(pd.DataFrame(table), hide_index=True, use_container_width=True)
            cheaper = near[near["price"] <= local * 0.95] if local is not None else near.iloc[0:0]
            if local is None:
                st.caption(f"No price was recorded in {county} in {latest:%B %Y}, so these cannot be compared with it.")
            elif cheaper.empty:
                st.caption(f"None of these is at least 5% cheaper than {county} (KES {local:,.1f} per {u}).")
            else:
                st.markdown("Is the trip worth it?")
                v1, v2 = st.columns(2)
                vehicle = v1.selectbox("Your vehicle", list(inputs[0].index), index=2)
                cap = int(inputs[0].loc[vehicle, "capacity_kg"])
                qty = v2.number_input(f"How much ({u})", min_value=50, max_value=3 * cap, value=cap, step=50,
                                      key=f"qty_{vehicle}")
                options, best = tp.advise(county, local, near[["county_b", "price"]], qty, vehicle, inputs)
                if best is not None:
                    st.success(f"Worth the trip to {best['county_b']}: you save about "
                               f"KES {best['net'] * qty:,.0f} after transport "
                               f"(transport about KES {best['transport']:,.1f} per {u}).")
                else:
                    top = options.iloc[0]
                    st.warning(f"Not worth the trip with this load: transport to {top['county_b']} costs about "
                               f"KES {top['transport']:,.1f} per {u}, so buying in {county} is better.")
        st.caption(f"Prices recorded in markets in {latest:%B %Y}. Savings exclude handling and market fees; "
                   "they pay off for a lorry load, not a few bags.")

    with st.expander("Please note"):
        st.markdown("""
* A forecast is the most likely price, not a promise. About 8 times in 10 the real price falls inside the range shown.
* "Price may jump" means a higher risk than usual, not a certainty: most warnings are not followed by a jump, and
  about half of jumps come without a warning (floods, conflict or policy changes are not in the data).
* "High for the season" compares today's price with the usual price for this time of year; it does not mean a jump
  is coming.
* Most county prices are estimates; only some markets report prices each month. Forecasts are less certain where no
  price was recorded.
* Transport costs use government hire rates and pump prices; real quotes may differ.
""")

# Tab 2: map of jump warnings
with tab_map:
    f1, f2 = st.columns(2)
    pick_crop = f1.selectbox("Food", ["All foods"] + sorted(result["commodity"].unique()), key="map_crop")
    pick_month = f2.radio("Month", [f"{m:%B}" for m in months], horizontal=True, key="map_month")
    h = [f"{m:%B}" for m in months].index(pick_month) + 1
    view = result[result["horizon"] == h]
    if pick_crop != "All foods":
        view = view[view["commodity"] == pick_crop]
    jumps = view[view["alert"]]

    geo, pcode_of = county_shapes()
    by_county = view.groupby("county")["alert"].sum().to_frame("n")
    by_county["pcode"] = by_county.index.map(pcode_of)
    by_county = by_county.dropna(subset=["pcode"])
    fig = go.Figure(go.Choropleth(
        geojson=geo, featureidkey="properties.pcode", locations=by_county["pcode"], z=by_county["n"],
        colorscale=[[0, "#f3efe8"], [0.001, "#fbd8b8"], [0.5, "#e07b26"], [1, "#9b2a1a"]],
        zmin=0, zmax=max(1, by_county["n"].max()), marker_line_color="white", marker_line_width=0.8,
        customdata=by_county.index, colorbar=dict(title="markets", thickness=12, len=0.6),
        hovertemplate="<b>%{customdata}</b><br>%{z} market(s) may jump<extra></extra>"))
    fig.update_geos(visible=False, projection_type="mercator", lonaxis_range=[33.6, 42.2], lataxis_range=[-4.9, 5.2])
    fig.update_layout(height=520, margin=dict(l=0, r=0, t=10, b=0), paper_bgcolor="rgba(0,0,0,0)",
                      geo=dict(bgcolor="rgba(0,0,0,0)"))
    st.markdown(f"{len(jumps):,} markets where the price may jump more than 15% in {pick_month}.")
    st.plotly_chart(fig, use_container_width=True, config={"scrollZoom": False})

    # the seasonal label is shown beside the warning as context (alerts card); markets already high come first
    order = {"Crisis": 0, "Alert": 1, "Stress": 2, "Normal": 3}
    table = jumps.assign(o=jumps["phase"].map(order).fillna(4)).sort_values(["o", "spike_probability_pct"],
                                                                           ascending=[True, False])
    st.dataframe(pd.DataFrame({
        "County": table["county"], "Food": table["commodity"], "Price": table["price_type"],
        "Price now (KES)": table["origin_price_kes"].round(1),
        "This season": table["phase"].map(SEASON_SHORT).fillna(""),
        f"Forecast {pick_month} (KES)": table["forecast_price_kes"].round(1),
        "Cheaper nearby": table["where_to_buy_county"].fillna(""),
    }), hide_index=True, use_container_width=True, height=380)
    high = int(jumps["phase"].isin(["Alert", "Crisis"]).sum())
    if high:
        st.caption(f"{high} of these markets are also unusually high for the season. They are listed first.")

st.caption("SokoRadar, Moringa School Data Science Capstone, Group 10. Data: Ministry of Agriculture and Livestock "
           "Development (KAMIS), WFP via HDX (CC BY IGO), KNBS, Central Bank of Kenya, World Bank.")
