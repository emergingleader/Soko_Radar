"""Three tabs added to the dashboard: On any phone (USSD and SMS preview), Does it work? (test results in plain words)
and About. Plus the "Use my location" switch for the sidebar.

The phone tab runs the real USSD menu code (app/phone, the same menu as the live Africa's Talking service in
github.com/sirajiali-hub/sokoradar-demo) on the forecasts this app has just made, so both always agree.
"""
import math
import sys
from html import escape
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent / "phone"))
import menu                                         # noqa: E402  (the USSD menu)
import sokoradar_data                               # noqa: E402
from i18n import LANGUAGES, TEXT                    # noqa: E402
from sms import SMS_MAX, message_for                # noqa: E402

DEMO_PHONE = "+254700000000"
PANEL = ("background: #1b2c63; border-radius: 16px; padding: 16px 18px; box-shadow: 0 6px 18px rgba(0,0,0,0.25); "
         "margin-bottom: 14px;")


def _title(text, dot="#7ee2a8"):
    st.markdown(f'<div style="font-size: 1.25rem; font-weight: 800; color: #f2f4f8; margin: 6px 0 8px;">'
                f'<span style="display: inline-block; width: 12px; height: 12px; border-radius: 50%; background: {dot}; '
                f'margin-right: 12px; vertical-align: middle;"></span>{text}</div>', unsafe_allow_html=True)


# ---------------------------------------------------------------------------------------------- Use my location
def nearest_county(lat, lon, counties_csv):
    """The county whose centre is closest to the point."""
    c = pd.read_csv(counties_csv)
    d = (c["center_lat"] - lat) ** 2 + ((c["center_lon"] - lon) * math.cos(math.radians(lat))) ** 2
    return c.loc[d.idxmin(), "county"]


def location_switch(counties_csv):
    """Sidebar switch. Returns the user's county when they share their location, else None. Nothing is saved."""
    if not st.toggle("Use my location", key="use_location",
                     help="Your browser asks first. Used only to pick your county, never saved."):
        return None
    from streamlit_js_eval import get_geolocation
    loc = get_geolocation()
    if loc and "coords" in loc:
        county = nearest_county(loc["coords"]["latitude"], loc["coords"]["longitude"], counties_csv)
        st.caption(f"You seem to be in **{county}** county.")
        return county
    if loc is not None:
        st.caption("Location not shared. Pick your county below.")
    return None


# ---------------------------------------------------------------------------------------------- On any phone
PHONE = """
<div style="max-width: 320px; margin: auto; background: #05090e; border: 2px solid #2c3d58; border-radius: 28px;
            padding: 22px 16px 26px;">
  <div style="background: #e8f5e9; color: #1b1b1b; border-radius: 10px; padding: 14px; min-height: 260px;
              font-family: monospace; font-size: 14px; line-height: 1.45; white-space: pre-wrap;">{screen}</div>
  <div style="color: #aab6e8; text-align: center; font-size: 12px; margin-top: 10px;">{status}</div>
</div>"""


def _dial():
    st.session_state.ussd_text = ""


def _hang_up():
    st.session_state.ussd_text = None


def _press():
    key = st.session_state.get("ussd_key", "").strip()
    st.session_state.ussd_key = ""
    if key:
        text = st.session_state.ussd_text
        st.session_state.ussd_text = key if text == "" else f"{text}*{key}"


def phone_tab(result, county):
    sokoradar_data.use(result)
    names = ", ".join(TEXT[c]["name"] for c in LANGUAGES)
    st.markdown("Farmers and traders without a smartphone or internet dial a USSD code to get the price outlook and "
                f"jump warnings for their county, in {names}, and can sign up for alert SMS. Try the same menu here.")
    st.session_state.setdefault("ussd_text", None)          # None = not dialled yet

    left, right = st.columns([1, 1], gap="large")
    with left:
        _title("1. Dial the USSD code")
        text = st.session_state.ussd_text
        if text is None:
            reply, status = "CON Tap Dial to start", "not connected"
        else:
            reply = menu.handle(text, DEMO_PHONE)
            status = "session ended" if reply.startswith("END") else "type a number and tap Send"
        st.markdown(PHONE.format(screen=escape(reply[4:]), status=status), unsafe_allow_html=True)
        st.write("")
        c1, c2 = st.columns([2, 1])
        if text is None or reply.startswith("END"):
            c1.button("Dial", type="primary", width="stretch", on_click=_dial, key="ussd_dial")
        else:
            c1.text_input("Your choice", max_chars=2, placeholder="type a number, e.g. 1", key="ussd_key",
                          label_visibility="collapsed", on_change=_press)
            c1.button("Send", type="primary", width="stretch", on_click=_press, key="ussd_send")
        c2.button("Hang up", width="stretch", on_click=_hang_up, key="ussd_hang")
        st.caption("Counties come 8 per screen: 9 shows more, 0 goes back. Option 3 asks for consent before signing up. "
                   "This page is a preview: it sends no SMS and keeps no phone number.")

    with right:
        _title("2. The alert SMS")
        options = sokoradar_data.counties()
        c1, c2 = st.columns(2)
        sms_county = c1.selectbox("Subscriber's county", options,
                                  index=options.index(county) if county in options else 0,
                                  key=f"sms_county_{county}")         # follows the county chosen in the sidebar
        lang = c2.selectbox("Language", LANGUAGES, format_func=lambda c: TEXT[c]["name"], key="sms_lang")
        msg = message_for(sms_county, lang)
        if msg:
            st.markdown(f'<div style="background: #24387a; color: #e8ecff; border-radius: 14px; padding: 12px 14px; '
                        f'max-width: 360px;">{escape(msg)}</div>', unsafe_allow_html=True)
            st.caption(f"{len(msg)} characters: fits in one SMS ({SMS_MAX}).")
        else:
            st.info(f"No jump warning in {sms_county} next month, so no SMS is sent.")
        st.markdown("""
**How it works**
1. A user dials the code, picks a language and county, and agrees to receive alerts (option 3).
2. When new forecasts arrive, each subscriber gets the jump warnings for their county by SMS, and can also get a
   voice call that reads the alert aloud.
3. Checking the price outlook or alerts on USSD also sends the answer by SMS, since a USSD screen disappears.
4. To stop, dial again and choose 4.

**Status:** the menu runs on Africa's Talking (test mode). Live SMS and voice calls already reach Airtel numbers;
Safaricom needs a registered sender ID, and a live USSD code needs a paid code from Africa's Talking.
""")


# ---------------------------------------------------------------------------------------------- Does it work?
def _kpis(items):
    cards = "".join(
        f'<div class="sr-card" style="min-height: 0;"><div class="m" style="white-space: normal;">{label}</div>'
        f'<div class="p">{value}</div><div class="d" style="margin-top: 0;">{note}</div></div>'
        for label, value, note in items)
    st.markdown(f'<div class="sr-row">{cards}</div>', unsafe_allow_html=True)


def results_tab():
    st.markdown("Every result below is judged only on prices recorded in a market, never on estimates.")

    _title("Sealed test on 2025 to 2026 (months the model never saw)")
    _kpis([
        ("Average error, 1 month ahead", "10.8%", "12.8% at 2 months, 13.6% at 3"),
        ("Sharp rises caught", "51%", "of rises above 15%, 1 month ahead (42% at 2, 38% at 3)"),
        ("Warnings followed by a rise", "22%", "at 1 month (37% at 2, 46% at 3)"),
    ])
    st.markdown("The frozen model, trained on 2006 to 2024 and run once, forecast every month from January 2025 to August "
                "2026 and was scored on real WFP prices (870 at 1 month, in 135 series). This was a harder period: even "
                "\"next month = this month\" missed by 10.8% at 1 month. The forecast was level with that at 1 month and "
                "2% to 3% better at 2 and 3 months, as good as in the backtest. The jump warning caught about half of "
                "sharp rises, as before, with more false alarms at 1 month (68% of calm months stayed quiet). "
                "Details: notebook 02, section 12, and the model card.")

    _title("Backtest 2015 to 2024")
    st.markdown("""
Each year was predicted using only the years before it.
* **Price forecast:** average error **9.0%, 12.3% and 14.5%** at 1, 2 and 3 months, about the same as assuming next month
  equals this month. Prices are hard to forecast exactly, so SokoRadar leads with the jump warning and a range.
* **Jump warning:** catches about **half of sharp rises** (48% one month ahead). About 1 in 5 warnings is followed by a
  rise, roughly **twice the normal rate** of 12%.
* **Early warning:** of 347 times a market moved into WFP's ALPS "Alert", the jump warning warned of **51%** about
  **2 months** before. WFP's own label only flags a market once prices are already high.
* **Likely range:** **78% to 82%** of real prices fell inside the 80% range. Each crop has its own width; potatoes are
  the hardest to predict.
* **Where to buy:** of 956 suggestions that could be checked a month later, the suggested county was really
  cheaper in **85%**, saving about **20%** before transport. After transport, full loads in bigger vehicles pay most
  often. In the 2025 to 2026 test only 10 could be checked (8 right), too few to judge.
""")

    _title("Limits", dot="#ffc266")
    st.markdown("""
* A warning means **higher risk, not a certain rise**. About half of sharp rises come with no warning, often caused by
  things the data cannot see (floods, conflict, policy changes).
* Only part of county prices are recorded in a market; the rest are estimates. All scores use recorded prices only.
* Where to buy needs a recorded price in the county and a nearby one, so it is not available everywhere every month.
* The price range was checked in the backtest only, not in the 2025 to 2026 test.
""")


# ---------------------------------------------------------------------------------------------- About
def about_tab():
    st.markdown("""
#### The problem
Food price spikes hit poor households, farmers and pastoralists hardest. Today's tools report prices after they have
risen, so responses such as cash transfer top ups or reserve releases come late. SokoRadar asks: **can we see a price
shock coming early enough to act?**

#### What SokoRadar gives each user
| Output | Question it answers |
|---|---|
| Price forecast | Where is this price heading over the next 1 to 3 months? |
| Likely range | How far could it be from the forecast? (80% range) |
| Jump warning | Is a rise above 15% more likely than usual? |
| Season label | Is the price already high for this time of year? (WFP's ALPS method) |
| Where to buy | Is a nearby county cheaper, even after transport? |
| On any phone | The same warnings by USSD, SMS and voice, without a smartphone |

#### How it works
1. **Data:** monthly prices for 47 counties (retail and wholesale) from 2006, with rainfall, vegetation, fuel and exchange
   rate data.
2. **Price forecast:** ARIMA on log prices, 1 to 3 months ahead.
3. **Jump warning:** a LightGBM model gives the chance of a rise above 15%; a warning shows above a fixed level.
4. **Season label and ranges:** WFP's ALPS method, and ranges learned from past forecast errors for each crop.
5. **Where to buy:** nearby counties with a recorded price, costed with road distance, fuel prices and vehicle hire.
6. **Updates:** new prices are added every month, and the forecasts are made again.

#### Data sources
Ministry of Agriculture and Livestock Development (KAMIS), WFP market prices via HDX (CC BY IGO), KNBS, Central Bank of
Kenya, World Bank, EPRA fuel prices, CHIRPS rainfall and NDVI via HDX, the government vehicle hire rates and the road
distance matrix.

#### Team
Group 10, Moringa School Data Science Capstone, 2026: Zainabu (data), Thande and Frank (forecasting), Siraji (alerts,
explainability and phone service), Tonny (deployment), Sam (product and impact).

*An alert means higher risk, not certainty. SokoRadar is early warning, not trading advice.*
""")
