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

# accessible dark theme: blue for falls/forecast, orange for rises and warnings (colour-blind safe, WCAG AA+)
BLUE, RED, GREY, INK = "#7cc4ff", "#ff9e6b", "#b8c1d1", "#f2f4f8"
# short seasonal labels for the list on the map tab; the full messages come from the alerts script
SEASON_SHORT = {"Normal": "Normal", "Stress": "Above normal", "Alert": "Unusually high", "Crisis": "Very high"}

st.set_page_config(page_title="SokoRadar", layout="wide")
st.markdown("""
<style>
.sr-row {display: grid; grid-template-columns: repeat(auto-fit, minmax(210px, 1fr)); gap: 16px; align-items: stretch;
          margin-bottom: 8px;}
.sr-card {display: flex; flex-direction: column; gap: 6px; padding: 14px 18px 16px; border-radius: 14px;
          background: #24387a; border: 2px solid transparent; border-top: 6px solid #c7d2fe;
          box-shadow: 0 6px 18px rgba(0,0,0,0.25);}
.sr-card.down {border-top-color: #8be9ff;} .sr-card.up {border-top-color: #ffc266;}
.sr-card.warn {border-color: #ff9e6b; border-top-color: #ff9e6b;}
.sr-card .top {display: flex; flex-wrap: wrap; justify-content: space-between; align-items: center; gap: 6px 8px;
               min-height: 26px;}
.sr-card .m {font-size: 0.8rem; font-weight: 700; letter-spacing: 0.06em; text-transform: uppercase; color: #c7d2fe;
             white-space: nowrap;}
.sr-card .w {font-size: 0.78rem; font-weight: 700; color: #1a1a1a; background: #ff9e6b; padding: 3px 9px;
             border-radius: 999px; white-space: nowrap;}
.sr-card .p {font-size: 2.2rem; font-weight: 800; line-height: 1.15; white-space: nowrap; color: #7ee2a8;}
.sr-card .p small {font-size: 0.9rem; font-weight: 500; color: #c7d2fe;}
.sr-card .rl {font-size: 0.72rem; font-weight: 700; letter-spacing: 0.06em; text-transform: uppercase; color: #c7d2fe;
              margin-top: 8px;}
.sr-card .lh {display: flex; align-items: center; gap: 8px;}
.sr-card .lh b {flex: 1; text-align: center; font-size: 1.1rem; color: #e8ecff; background: #1d2c5e;
                border-radius: 10px; padding: 6px 10px;}
.sr-card .lh i {font-style: normal; font-size: 0.85rem; color: #c7d2fe;}
.sr-card .d {margin-top: auto; padding-top: 8px; font-size: 0.9rem; color: #c7d2fe;}
.sr-card .c {font-weight: 700; padding: 2px 9px; border-radius: 999px; margin-right: 4px; color: #e8ecff;
             background: #1d2c5e;}
.sr-card .c.down {color: #8be9ff; background: rgba(139,233,255,0.14);}
.sr-card .c.up {color: #ffc266; background: rgba(255,194,102,0.14);}
.st-key-price_chart, .st-key-jump_chart, .st-key-buy_panel, .st-key-jump_list {background: #1b2c63; border-radius: 16px; padding: 14px 16px 6px;
                     box-shadow: 0 6px 18px rgba(0,0,0,0.25);}
/* the rest of the page follows the heading: off-white headings with a mint accent, lavender text */
[data-testid="stMain"] [data-testid="stMarkdownContainer"] p,
[data-testid="stMain"] [data-testid="stMarkdownContainer"] li {color: #c7d2fe;}
[data-testid="stMain"] [data-testid="stCaptionContainer"] {color: #aab6e8;}
[data-testid="stMain"] [data-testid="stHeading"] h3,
[data-testid="stMain"] [data-testid="stMarkdownContainer"] h4 {color: #f2f4f8; border-left: 5px solid #7ee2a8;
    padding-left: 12px; margin-top: 0.6rem;}
.stTabs [role="tablist"] {gap: 6px; border-bottom: 1px solid #2c3d58;}
.stTabs [data-testid="stTab"] {padding: 8px 16px; border-radius: 10px 10px 0 0; border-bottom: 3px solid transparent;}
.stTabs [data-testid="stTab"][aria-selected="true"] {background: #1b2c63; border-bottom-color: #7ee2a8;}
.stTabs [data-testid="stTab"][aria-selected="true"] p {color: #7ee2a8; font-weight: 700;}
[data-testid="stExpander"] details {background: #1b2c63; border: none; border-radius: 14px;}
[data-testid="stExpander"] summary p {color: #f2f4f8; font-weight: 600;}
[data-testid="stSidebar"] {background: #17263d;}
[data-testid="stSidebarUserContent"] {counter-reset: sbstep;}
[data-testid="stSidebar"] h2 {color: #f2f4f8; display: flex; align-items: center; gap: 10px;}
[data-testid="stSidebar"] h2::before {counter-increment: sbstep; content: counter(sbstep); flex: none;
    width: 28px; height: 28px; border-radius: 50%; background: #7ee2a8; color: #0f1b2d; font-size: 0.95rem;
    font-weight: 800; display: inline-flex; align-items: center; justify-content: center;}
[data-testid="stSidebar"] label p {color: #c7d2fe;}
.st-key-buy_panel {padding-bottom: 18px !important;}
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
with st.spinner("Preparing the forecasts. After the app restarts this can take up to 7 minutes; "
                "later visits are quick."):
    result = run_models(origin)
months = [pd.Timestamp(m) for m in sorted(result["target_month"].unique())]

# Header and market choice
start = f"{months[0]:%B %Y}" if months[0].year != months[-1].year else f"{months[0]:%B}"
st.markdown(
    '<div style="margin: 0.4rem 0 1rem;">'
    '<div style="font-size: 2.4rem; font-weight: 800; line-height: 1.1; color: #f2f4f8;">'
    'Soko<span style="color: #7ee2a8;">Radar</span></div>'
    '<div style="width: 64px; height: 5px; background: #7ee2a8; border-radius: 4px; margin: 10px 0 10px;"></div>'
    f'<div style="font-size: 1rem; color: #c7d2fe;">Food price forecast for Kenyan counties. '
    f'Latest prices: {latest:%B %Y}. Forecast: {start} to {months[-1]:%B %Y}.</div></div>', unsafe_allow_html=True)
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

    # past prices for the chosen market (2006 to the latest month)
    st.header("See a past price")
    past = prices[(prices["county"] == county) & (prices["commodity"] == crop)
                  & (prices["price_type"] == price_type)].sort_values("month")
    years = sorted(past["month"].dt.year.unique(), reverse=True)
    year = st.selectbox("Year", years, index=None, placeholder="Choose a year")
    when = None
    if year is not None:
        in_year = past[past["month"].dt.year == year]
        when = st.selectbox("Month", list(in_year["month"]), format_func=lambda m: f"{m:%B}")
        then = in_year[in_year["month"] == when].iloc[0]
        now = past.iloc[-1]
        unit = UNIT.get(crop, "kg")
        st.metric(f"{when:%B %Y}", f"KES {then['price_kes']:,.1f} per {unit}",
                  f"{(now['price_kes'] / then['price_kes'] - 1) * 100:+.0f}% by {latest:%B %Y}",
                  delta_color="inverse")
        st.caption(("Recorded in a market" if then["observed"] else "Estimate") +
                   f". Price in {latest:%B %Y}: KES {now['price_kes']:,.1f}.")

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

    cards = []                                # one row of cards, so all three are the same height
    for _, r in rows.iterrows():
        warn = bool(r["alert"])
        change = round(r["forecast_change_pct"], 1) + 0.0
        trend = "up" if change >= 0.5 else ("down" if change <= -0.5 else "")
        arrow = {"up": "▲", "down": "▼"}.get(trend, "●")
        lo, hi, f = r["range_low_kes"], r["range_high_kes"], r["forecast_price_kes"]
        steady = abs(change) < 0.5
        cards.append(
            f'<div class="sr-card {trend} {"warn" if warn else ""}">'
            f'<div class="top"><span class="m">{pd.Timestamp(r["target_month"]):%B %Y}</span>'
            + ('<span class="w">⚠ May jump 15%+</span>' if warn else "") + '</div>'
            f'<div class="p">KES {f:,.0f} <small>/ {u}</small></div>'
            f'<div class="rl">Likely between</div>'
            f'<div class="lh"><b>{lo:,.0f}</b><i>and</i><b>{hi:,.0f}</b></div>'
            + (f'<div class="d"><span class="c">● No change</span> from {latest:%B}</div>' if steady else
               f'<div class="d"><span class="c {trend}">{arrow} {abs(change):.0f}%</span> from {latest:%B}</div>')
            + "</div>")
    st.markdown(f'<div class="sr-row">{"".join(cards)}</div>', unsafe_allow_html=True)
    st.write("")

    hist = prices[(prices["series"] == first["series"])].tail(36)
    if when is not None and when < hist["month"].min():       # stretch back to show the chosen past month
        hist = prices[(prices["series"] == first["series"]) & (prices["month"] >= when - pd.DateOffset(months=6))]
    tm = pd.to_datetime(rows["target_month"])
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=[latest, *tm, *tm[::-1], latest],
                             y=[first["origin_price_kes"], *rows["range_high_kes"], *rows["range_low_kes"][::-1],
                                first["origin_price_kes"]],
                             mode="lines", fill="toself", fillcolor="rgba(126,226,168,0.16)", line=dict(width=0),
                             name="Likely range", hoverinfo="skip"))
    fig.add_trace(go.Scatter(x=hist["month"], y=hist["price_kes"], mode="lines", line=dict(color=GREY, width=2.5),
                             name="Past price", hovertemplate="KES %{y:,.0f}<extra>Past price</extra>"))
    fig.add_trace(go.Scatter(x=[latest, *tm], y=[first["origin_price_kes"], *rows["forecast_price_kes"]],
                             mode="lines+markers", line=dict(color="#7ee2a8", dash="dash", width=3), name="Forecast",
                             hovertemplate="KES %{y:,.0f}<extra>Forecast</extra>"))
    jumps = rows[rows["alert"]]
    if len(jumps):
        fig.add_trace(go.Scatter(x=pd.to_datetime(jumps["target_month"]), y=jumps["forecast_price_kes"],
                                 mode="markers", marker=dict(color=RED, size=14, symbol="triangle-up"),
                                 name="May jump 15%+", hoverinfo="skip"))
    if when is not None:
        # the chosen past month: gold guide line, large ringed dot and a filled label so it is easy to find
        fig.add_vline(x=when, line=dict(color="#ffc266", dash="dash", width=2))
        fig.add_trace(go.Scatter(x=[when], y=[then["price_kes"]], mode="markers", name=f"{when:%B %Y}",
                                 marker=dict(color="#ffc266", size=20, line=dict(color="#ffffff", width=3)),
                                 hovertemplate="KES %{y:,.0f}<extra>" + f"{when:%B %Y}" + "</extra>"))
        fig.add_annotation(x=when, y=then["price_kes"], text=f"<b>{when:%b %Y}: KES {then['price_kes']:,.0f}</b>",
                           showarrow=True, arrowhead=0, arrowcolor="#ffc266", arrowwidth=2, ax=0, ay=-48,
                           bgcolor="#ffc266", bordercolor="#ffc266", borderpad=6, font=dict(color="#1a1a1a", size=14))
    fig.add_vline(x=latest, line=dict(color=GREY, dash="dot", width=1))
    fig.add_annotation(x=latest, y=1, yref="paper", text=f"Latest price<br>{latest:%b %Y}", showarrow=False,
                       xanchor="right", yanchor="top", align="right", font=dict(color=GREY, size=12))
    fig.update_layout(height=380, margin=dict(l=10, r=10, t=10, b=10),
                      paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", font=dict(color="#c7d2fe"),
                      xaxis_title="Month", yaxis_title=f"KES per {u}",
                      legend=dict(orientation="h", y=-0.22), hovermode="x unified")
    axis = dict(showline=True, linecolor="#c7d2fe", linewidth=1.5, ticks="outside", tickcolor="#c7d2fe",
                ticklen=6, gridcolor="rgba(199,210,254,0.10)", zeroline=False)
    fig.update_xaxes(**axis, tickformat="%b %Y", nticks=8)
    fig.update_yaxes(**axis, rangemode="tozero")
    with st.container(key="price_chart"):                    # chart sits in its own panel, like the cards
        st.markdown(                                          # title styled like the SokoRadar heading
            f'<div style="font-size: 1.25rem; font-weight: 800; color: #f2f4f8; margin-bottom: 6px;"><span style="display: inline-block; width: 12px; height: 12px; border-radius: 50%; background: #7ee2a8; box-shadow: 0 0 0 4px rgba(126,226,168,0.22); margin-right: 12px; vertical-align: middle;"></span>{crop} price in {county}</div>'
            '',
            unsafe_allow_html=True)
        st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})

    # chance of a jump against the warning level for each month (a bullet chart in place of the table;
    # the forecast, change and range are already on the cards)
    labels = [f"{m:%B %Y}" for m in pd.to_datetime(rows["target_month"])][::-1]
    chance = rows["spike_probability_pct"].to_numpy()[::-1]
    level = rows["alert_threshold_pct"].to_numpy()[::-1]
    alert = rows["alert"].to_numpy()[::-1]
    jf = go.Figure()
    jf.add_trace(go.Bar(y=labels, x=chance, orientation="h", name="Chance of a jump",
                        marker=dict(color=["#ff9e6b" if a else "#8be9ff" for a in alert]),
                        text=[f"{c:.0f}%" for c in chance], textposition="outside",
                        textfont=dict(color="#f2f4f8", size=14), cliponaxis=False,
                        hovertemplate="Chance of a jump: %{x:.0f}%<extra></extra>"))
    jf.add_trace(go.Scatter(y=labels, x=level, mode="markers", name="Warning level",
                            marker=dict(symbol="line-ns", size=34, line=dict(color="#f2f4f8", width=4)),
                            hovertemplate="Warning level: %{x:.0f}%<extra></extra>"))
    jf.update_layout(height=230, margin=dict(l=10, r=40, t=10, b=10), barmode="overlay", bargap=0.45,
                     paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", font=dict(color="#c7d2fe"),
                     legend=dict(orientation="h", y=-0.25), showlegend=True)
    jf.update_xaxes(range=[0, max(50, float(np.max(np.r_[chance, level])) + 10)], ticksuffix="%",
                    gridcolor="rgba(199,210,254,0.10)", zeroline=False, showline=True, linecolor="#c7d2fe")
    jf.update_yaxes(showline=True, linecolor="#c7d2fe")
    with st.container(key="jump_chart"):
        st.markdown(
            '<div style="font-size: 1.25rem; font-weight: 800; color: #f2f4f8; margin-bottom: 6px;"><span style="display: inline-block; width: 12px; height: 12px; border-radius: 50%; background: #7ee2a8; box-shadow: 0 0 0 4px rgba(126,226,168,0.22); margin-right: 12px; vertical-align: middle;"></span>Chance of a price jump</div>'
            '',
            unsafe_allow_html=True)
        st.plotly_chart(jf, use_container_width=True, config={"displayModeBar": False})
    # where to buy cheaper: recorded prices in nearby counties (the handover rule uses recorded prices only).
    # Borrowed from the tester app: trip inputs always shown and a one-line verdict. Not borrowed: forecast prices
    # and estimated prices (notebook 05 and the model card use recorded prices only).
    # where to buy sits in one panel, like the charts above
    with st.container(key="buy_panel"):
        st.markdown('<div style="font-size: 1.25rem; font-weight: 800; color: #f2f4f8; margin-bottom: 8px;">'
                    '<span style="display: inline-block; width: 12px; height: 12px; border-radius: 50%; '
                    'background: #7ee2a8; box-shadow: 0 0 0 4px rgba(126,226,168,0.22); margin-right: 12px; '
                    'vertical-align: middle;"></span>Where to buy cheaper</div>', unsafe_allow_html=True)
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
                local = float(w.iloc[0]["where_to_buy_compared_with_kes"])

            # Indicative fallback, used only when recorded prices can't be compared: add the Ministry's county
            # bulletin prices (a real county-level report for maize, beans and potatoes). Other estimates (copied from
            # neighbours, trends, averages) are still left out, as notebook 05 and the model card require.
            indicative = False
            if near.empty or local is None:
                bulletin = prices["flag"].str.startswith("Estimated: MoA county bulletin")
                ind = prices[(prices["month"] == latest) & (prices["observed"] | bulletin)
                             & (prices["commodity"] == crop) & (prices["price_type"] == price_type)]
                near_i = (nearby.merge(ind[["county", "price_kes"]], left_on="county_b", right_on="county")
                          .drop(columns="county").rename(columns={"price_kes": "price"}).sort_values("price"))
                here_i = ind.loc[ind["county"] == county, "price_kes"]
                if not near_i.empty and len(here_i):
                    near, local, indicative = near_i, float(here_i.iloc[0]), True

            # the question this section answers, and why it asks for a vehicle and a load
            st.markdown(f'<div style="font-size: 1.05rem; color: #f2f4f8; margin-bottom: 4px;">Is a nearby county cheaper '
                        f'than {county}, <span style="color: #7ee2a8; font-weight: 700;">even after paying for '
                        f'transport?</span></div>', unsafe_allow_html=True)
            left, right = st.columns([1, 1.5], gap="medium")   # your trip on the left, the answer on the right
            vehicle = left.selectbox("How will you carry it?", list(inputs[0].index), index=2,
                                   help="Hire rate and fuel use differ by vehicle (government hire rates, county pump "
                                        "prices).")
            cap = int(inputs[0].loc[vehicle, "capacity_kg"])
            qty = left.number_input(f"How much will you buy? ({u})", min_value=50, max_value=3 * cap, value=cap,
                                  step=50, key=f"qty_{vehicle}",
                                  help="A bigger load shares the trip cost, so each kg costs less to move.")

            month = f"{latest:%B %Y}"
            other = [t for t in types if t != price_type]
            hint = ""                                         # tip pill, only if the other price type can be compared
            if other:
                rec_o = prices[(prices["month"] == latest) & prices["observed"] & (prices["commodity"] == crop)
                               & (prices["price_type"] == other[0])]
                if nearby["county_b"].isin(rec_o["county"]).any() and county in set(rec_o["county"]):
                    hint = f"Try {other[0].lower()} prices in the sidebar"
            stat = ""                                             # big figure on the right, only when buying pays
            net_of, pick = {}, None                               # saving per kg after transport, and the chosen county
            if near.empty:
                icon, tone, head = "i", "#c4b5fd", "Can't compare yet"
                body = (f"No market near {county} reported a {price_type.lower()} price in {month}, "
                        "so there is nothing to compare.")
            elif local is None:
                icon, tone, head = "i", "#c4b5fd", "Can't compare yet"
                body = (f"Nearby markets reported prices, but {county}'s own {price_type.lower()} price was not "
                        f"recorded in {month}, so we can't tell which is cheaper.")
            else:
                options, best = tp.advise(county, local, near[["county_b", "price"]], qty, vehicle, inputs)
                net_of = dict(zip(options["county_b"], options["net"]))
                pick = best["county_b"] if best is not None else None
                if best is not None:
                    icon, tone, head = "✓", "#7ee2a8", f"Buy in {best['county_b']}"
                    body = (f"KES {best['price']:,.0f} per {u} there, KES {local:,.0f} in {county}. "
                            f"Transport about KES {best['transport']:,.1f} per {u}.")
                    stat = (f'<div style="margin-top: 10px;"><span style="font-size: 0.75rem; color: #aab6e8; '
                            f'letter-spacing: 0.05em;">YOU SAVE ABOUT </span><span style="font-size: 1.5rem; '
                            f'font-weight: 800; color: #7ee2a8;">KES {best["net"] * qty:,.0f}</span></div>')
                else:
                    top_opt = options.iloc[0]
                    icon, tone, head = "⌂", "#8be9ff", f"Stay in {county}"
                    if top_opt["gross"] < 0.05 * local:
                        body = f"No nearby county is at least 5% cheaper (KES {local:,.0f} per {u} here)."
                    else:
                        gap = top_opt["net"]
                        body = (f"{top_opt['county_b']} is cheaper, but transport (KES {top_opt['transport']:,.1f} per {u}) "
                                + (f"makes it cost KES {-gap:,.1f} per {u} more." if gap < 0 else
                                   f"leaves a saving under 5%."))
                        kg = tp.smallest_paying_load(top_opt["gross"] - 0.05 * local, top_opt["road_km"], vehicle,
                                                     county, inputs)
                        body += (f" It pays from about {kg:,} {u} with this vehicle." if kg else
                                 " Not even 3 full loads of this vehicle would pay.")
            right.markdown(
                f'<div style="display: flex; align-items: flex-start; gap: 14px; background: {tone}1a; '
                f'border: 1px solid {tone}; border-left: 6px solid {tone}; border-radius: 14px; padding: 16px 18px; '
                f'margin: 28px 0 16px;">'
                f'<div style="flex: none; width: 34px; height: 34px; border-radius: 50%; background: {tone}; color: #0f1b2d; '
                f'display: flex; align-items: center; justify-content: center; font-size: 1.1rem; font-weight: 800;">'
                f'{icon}</div>'
                f'<div style="flex: 1;"><div style="color: {tone}; font-weight: 800; font-size: 1.15rem; line-height: 34px;">'
                f'{head}'
                + (' <span style="font-size: 0.72rem; font-weight: 700; letter-spacing: 0.05em; color: #0f1b2d; '
                   'background: #c7d2fe; border-radius: 999px; padding: 2px 9px; margin-left: 6px; vertical-align: '
                   'middle;">INDICATIVE</span>' if indicative and icon != "i" else "")
                + f'</div><div style="color: #e8ecff; font-size: 0.95rem;">{body}</div>'
                + (f'<div style="display: inline-block; margin-top: 10px; padding: 4px 12px; border-radius: 999px; '
                   f'background: #0f1b2d; color: {tone}; font-size: 0.85rem; font-weight: 600;">→ {hint}</div>'
                   if hint and icon == "i" else "")
                + f'{stat}</div></div>', unsafe_allow_html=True)

            if not near.empty:
                # price ladder: the 6 cheapest nearby counties plus this county (gold), cheapest on top.
                # Mint = at least 5% cheaper than here, slate = not cheap enough. Values sit inside the bars.
                ladder = near.head(6)[["county_b", "price", "road_km"]].copy()
                if local is not None:
                    ladder = pd.concat([ladder, pd.DataFrame([{"county_b": county, "price": local, "road_km": 0.0}])])
                ladder = ladder.sort_values("price", ascending=False)        # plotly draws the last row on top
                home = ladder["county_b"] == county
                # mint = the best buy from the answer box (clears the 5% rule after transport); everything else is slate,
                # so the chart always agrees with the answer
                chosen = ladder["county_b"] == pick
                colour = np.where(home, "#ffc266", np.where(chosen, "#7ee2a8", "#5d6fb0"))
                ink = np.where(home | chosen, "#0f1b2d", "#f2f4f8")
                inside = [f"  KES {p:,.0f}" for p in ladder["price"]]
                def after(c, km):
                    n = net_of.get(c)
                    if n is None:
                        return f"  {km:,.0f} km"
                    return f"  {km:,.0f} km · " + (f"saves KES {n:,.1f}/{u}" if n > 0 else f"costs KES {-n:,.1f}/{u} more")
                beside = ["  your county" if h else ("  ✓ " + after(c, km).strip() if c == pick else after(c, km))
                          for h, c, km in zip(home, ladder["county_b"], ladder["road_km"])]
                names = [f"<b>{c}</b>" if h else c for c, h in zip(ladder["county_b"], home)]
                bf = go.Figure(go.Bar(y=names, x=ladder["price"], orientation="h", text=inside, textposition="inside",
                                      insidetextanchor="start", textfont=dict(color=list(ink), size=14),
                                      marker=dict(color=list(colour), cornerradius=8),
                                      hovertemplate="%{y}: KES %{x:,.0f}<extra></extra>", showlegend=False))
                for y, x, t in zip(names, ladder["price"], beside):         # distance and difference after each bar
                    bf.add_annotation(x=x, y=y, text=t, showarrow=False, xanchor="left",
                                      font=dict(color="#c7d2fe", size=13))
                bf.update_layout(height=60 + 44 * len(ladder), margin=dict(l=10, r=10, t=10, b=10), bargap=0.32,
                                 paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", font=dict(color="#c7d2fe"))
                bf.update_xaxes(visible=False, range=[0, float(ladder["price"].max()) * 2.1])
                bf.update_yaxes(showline=False, ticks="", tickfont=dict(size=14, color="#e8ecff"))
                legend = ('<span style="color:#ffc266">●</span> your county &nbsp; '
                          + ('<span style="color:#7ee2a8">●</span> best buy &nbsp; ' if pick else "")
                          + '<span style="color:#5d6fb0">●</span> '
                          + ("other counties" if pick else "not worth the trip" if net_of else "nearby county"))
                st.markdown(f'<div style="border-top: 1px solid #2c3d58; margin-top: 4px; padding-top: 14px; '
                            f'display: flex; flex-wrap: wrap; justify-content: space-between; gap: 6px 16px;">'
                            f'<span style="font-size: 1rem; font-weight: 700; color: #f2f4f8;">Prices in nearby counties, '
                            f'{month}</span>'
                            f'<span style="font-size: 0.85rem; color: #c7d2fe;">{legend}</span></div>',
                            unsafe_allow_html=True)
                st.plotly_chart(bf, use_container_width=True, config={"displayModeBar": False})

    # disclaimer: a small fold-out under Where to buy that opens downwards (an expander, not a pop-over, so it never
    # opens upwards at the bottom of the page)
    st.markdown('<div style="height: 10px;"></div>', unsafe_allow_html=True)
    with st.expander("Disclaimer", icon=":material/info:"):
        st.markdown("""
SokoRadar is a Moringa School student project (Group 10) for information and planning only. It is not an official
Ministry of Agriculture, WFP or government service, and it is not advice to buy, sell or trade.

* Prices, forecasts and savings are estimates and may be wrong or out of date. About 8 times in 10 the real price
  falls inside the likely range.
* "May jump" means a higher risk than usual, not a certain rise. Many jumps come without a warning (floods, conflict
  or policy changes are not in the data).
* Most county prices are estimated; only some markets report prices each month. Where to buy uses market prices or,
  when marked Indicative, the Ministry county bulletin.
* Transport costs use government hire rates and pump prices, and leave out handling and market fees.

Check prices at the market and get transport quotes before making decisions. The team accepts no liability for losses
from using this app.

Data: Ministry of Agriculture and Livestock Development (KAMIS), WFP via HDX (CC BY IGO), KNBS, Central Bank of Kenya,
World Bank.
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
    # each county is simply "jump warning" or "no warning"; the hover lists which foods carry the warning
    by_county = view.groupby("county")["alert"].any().to_frame("warn")
    foods = (jumps.assign(item=jumps["commodity"] + " (" + jumps["price_type"].str.lower() + ")")
             .groupby("county")["item"].apply(lambda x: "<br>".join(sorted(x))))
    by_county["pcode"] = by_county.index.map(pcode_of)
    by_county = by_county.dropna(subset=["pcode"])
    by_county["hover"] = [f"<b>{c}</b><br>Jump warning:<br>{foods[c]}" if w else f"<b>{c}</b><br>No warning"
                          for c, w in zip(by_county.index, by_county["warn"])]
    fig = go.Figure(go.Choropleth(
        geojson=geo, featureidkey="properties.pcode", locations=by_county["pcode"], z=by_county["warn"].astype(int),
        colorscale=[[0, "#2c3d58"], [0.5, "#2c3d58"], [0.5, "#f05252"], [1, "#f05252"]], zmin=0, zmax=1,
        showscale=False, marker_line_color="#0f1b2d", marker_line_width=0.8,
        customdata=by_county["hover"], hovertemplate="%{customdata}<extra></extra>"))
    fig.update_geos(visible=False, projection_type="mercator", lonaxis_range=[33.6, 42.2], lataxis_range=[-4.9, 5.2])
    fig.update_layout(height=520, margin=dict(l=0, r=0, t=10, b=0), paper_bgcolor="rgba(0,0,0,0)",
                      geo=dict(bgcolor="rgba(0,0,0,0)"))
    # KPI tiles (same card style as the price tab), then the full map
    n_counties = jumps["county"].nunique()
    n_high = view.loc[view["phase"].isin(["Alert", "Crisis"]), "county"].nunique()
    typical = float(view["forecast_change_pct"].median()) if len(view) else 0.0

    def kpi(label, value, sub, colour):
        return (f'<div class="sr-card" style="border-top-color: {colour}; min-height: 0;">'
                f'<div class="m" style="white-space: normal;">{label}</div><div class="p" style="color: {colour};">{value} '
                f'<small>{sub}</small></div></div>')
    st.markdown('<div class="sr-row">'
                + kpi("Jump warning", n_counties, "of 47 counties", "#f05252")
                + kpi("High for the season", n_high, "of 47 counties", "#ffc266")
                + kpi("Typical change", f"{typical:+.1f}%", f"by {pick_month}", "#7ee2a8")
                + '</div>', unsafe_allow_html=True)
    st.markdown('<span style="color:#f05252">■</span> Jump warning &nbsp;&nbsp; '
                '<span style="color:#5d6fb0">■</span> No warning', unsafe_allow_html=True)
    st.plotly_chart(fig, use_container_width=True, config={"scrollZoom": False, "displayModeBar": False})

    # ranked list of the warnings (replaces the long table): bar = chance of a jump, highest first
    with st.container(key="jump_list"):
        st.markdown('<div style="font-size: 1.25rem; font-weight: 800; color: #f2f4f8; margin-bottom: 6px;">'
                    '<span style="display: inline-block; width: 12px; height: 12px; border-radius: 50%; '
                    'background: #f05252; box-shadow: 0 0 0 4px rgba(240,82,82,0.25); margin-right: 12px; '
                    f'vertical-align: middle;"></span>Jump warnings for {pick_month}</div>', unsafe_allow_html=True)
        pick = []
        if jumps.empty:
            st.markdown(f"No county has a jump warning for {pick_month}.")
        else:
            pick = st.multiselect("Filter foods", sorted(jumps["commodity"].unique()), key="table_foods",
                                  placeholder="All foods")
            shown = (jumps[jumps["commodity"].isin(pick)] if pick else jumps).sort_values(
                "spike_probability_pct", ascending=False)
            top = shown.head(3)
            rows_html = []
            for _, r in top.iterrows():
                pct = float(r["spike_probability_pct"])
                high_tag = ('<span style="font-size: 0.72rem; font-weight: 700; color: #0f1b2d; background: #ffc266; '
                            'border-radius: 999px; padding: 1px 8px; margin-left: 6px;">high for season</span>'
                            if r["phase"] in ("Alert", "Crisis") else "")
                rows_html.append(
                    '<div style="display: grid; grid-template-columns: minmax(150px, 1.3fr) minmax(120px, 2fr) '
                    'minmax(120px, 1fr); gap: 12px; align-items: center; padding: 7px 0; '
                    'border-bottom: 1px solid #24387a;">'
                    f'<div><div style="color: #f2f4f8; font-weight: 600;">{r["county"]}{high_tag}</div>'
                    f'<div style="color: #c7d2fe; font-size: 0.85rem;">{r["commodity"]} ({r["price_type"].lower()})'
                    '</div></div>'
                    '<div style="display: flex; align-items: center; gap: 8px;">'
                    '<div style="flex: 1; height: 10px; border-radius: 6px; background: #2c3d58;">'
                    f'<div style="width: {min(pct, 100):.0f}%; height: 10px; border-radius: 6px; background: #ff9e6b;">'
                    f'</div></div><span style="color: #ff9e6b; font-weight: 700; width: 44px;">{pct:.0f}%</span></div>'
                    f'<div style="color: #c7d2fe; font-size: 0.9rem; text-align: right;">KES {r["origin_price_kes"]:,.0f}'
                    f' → <b style="color: #f2f4f8;">{r["forecast_price_kes"]:,.0f}</b></div></div>')
            st.markdown('<div style="font-size: 0.8rem; color: #aab6e8; display: grid; grid-template-columns: '
                        'minmax(150px, 1.3fr) minmax(120px, 2fr) minmax(120px, 1fr); gap: 12px;">'
                        '<span>COUNTY AND FOOD</span><span>CHANCE OF A JUMP</span>'
                        f'<span style="text-align: right;">NOW → {pick_month.upper()} (KES)</span></div>'
                        + "".join(rows_html), unsafe_allow_html=True)
            if len(shown) > len(top):
                st.caption(f"Showing the {len(top)} highest of {len(shown)} warnings. Download for the full list.")
            csv = pd.DataFrame({
                "county": shown["county"], "food": shown["commodity"], "price_type": shown["price_type"],
                "price_now_kes": shown["origin_price_kes"].round(1),
                f"forecast_{pick_month.lower()}_kes": shown["forecast_price_kes"].round(1),
                "likely_low_kes": shown["range_low_kes"].round(1), "likely_high_kes": shown["range_high_kes"].round(1),
                "chance_of_jump_pct": shown["spike_probability_pct"].round(0),
                "season": shown["phase"].map(SEASON_SHORT).fillna(""),
                "cheaper_nearby": shown["where_to_buy_county"].fillna(""),
            }).to_csv(index=False).encode("utf-8")
            st.download_button("Download these warnings (CSV)", csv, file_name=f"sokoradar_warnings_{pick_month.lower()}.csv",
                               mime="text/csv", icon=":material/download:")

        # counties whose price is already high for the season (the alerts card's seasonal label), with or without a
        # jump warning, so officers see both kinds of pressure in one place
        high = view[view["phase"].isin(["Alert", "Crisis"])]
        if pick:
            high = high[high["commodity"].isin(pick)]
        st.markdown('<div style="border-top: 1px solid #2c3d58; margin-top: 14px; padding-top: 14px; font-size: 1.05rem; '
                    'font-weight: 700; color: #f2f4f8;"><span style="color: #ffc266;">●</span> High for the season now</div>',
                    unsafe_allow_html=True)
        if high.empty:
            st.markdown("No county's price is unusually high for this time of year.")
        else:
            high = high.assign(o=high["phase"].map({"Crisis": 0, "Alert": 1})).sort_values(["o", "county"])
            rows_h = []
            for _, r in high.head(3).iterrows():
                warn_tag = ('<span style="font-size: 0.72rem; font-weight: 700; color: #0f1b2d; background: #f05252; '
                            'border-radius: 999px; padding: 1px 8px; margin-left: 6px;">jump warning</span>'
                            if r["alert"] else "")
                rows_h.append(
                    '<div style="display: grid; grid-template-columns: minmax(150px, 1.3fr) minmax(120px, 2fr) '
                    'minmax(120px, 1fr); gap: 12px; align-items: center; padding: 7px 0; '
                    'border-bottom: 1px solid #24387a;">'
                    f'<div><div style="color: #f2f4f8; font-weight: 600;">{r["county"]}{warn_tag}</div>'
                    f'<div style="color: #c7d2fe; font-size: 0.85rem;">{r["commodity"]} ({r["price_type"].lower()})'
                    '</div></div>'
                    f'<div><span style="font-size: 0.85rem; font-weight: 700; color: #0f1b2d; background: '
                    f'{"#ff9e6b" if r["phase"] == "Crisis" else "#ffc266"}; border-radius: 999px; padding: 3px 10px;">'
                    f'{SEASON_SHORT.get(r["phase"], r["phase"])} for the season</span></div>'
                    f'<div style="color: #c7d2fe; font-size: 0.9rem; text-align: right;">KES {r["origin_price_kes"]:,.0f}'
                    f' → <b style="color: #f2f4f8;">{r["forecast_price_kes"]:,.0f}</b></div></div>')
            st.markdown("".join(rows_h), unsafe_allow_html=True)
            if len(high) > 3:
                st.caption(f"Showing 3 of {len(high)}. Download for the full list.")
            csv_h = pd.DataFrame({
                "county": high["county"], "food": high["commodity"], "price_type": high["price_type"],
                "season": high["phase"].map(SEASON_SHORT).fillna(""), "jump_warning": high["alert"].map({True: "yes", False: "no"}),
                "price_now_kes": high["origin_price_kes"].round(1),
                f"forecast_{pick_month.lower()}_kes": high["forecast_price_kes"].round(1),
            }).to_csv(index=False).encode("utf-8")
            st.download_button("Download high-for-season list (CSV)", csv_h,
                               file_name=f"sokoradar_high_for_season_{pick_month.lower()}.csv", mime="text/csv",
                               icon=":material/download:")


