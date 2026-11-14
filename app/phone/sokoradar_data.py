"""The forecasts the USSD menu and the SMS read. In the app, streamlit_app.py hands over the forecasts it has just
made (use(result)), so the phone screens always show the same numbers as the dashboard. Nothing is computed here."""
import pandas as pd

# crops in the menu, in this order (their names in each language are in translations.csv)
CROPS = ["Dry Maize", "Beans Rosecoco", "Sorghum", "Red Irish Potatoes"]

_df = None


def use(result):
    """Take the app's forecasts (one row per series and horizon) in the shape the menu expects."""
    global _df
    df = result[result["commodity"].isin(CROPS)].copy()
    df = df.rename(columns={"alert": "spike_alert", "origin_price_kes": "price_kes",
                            "origin_price_is_real": "price_is_real"})
    for col in ("origin_month", "target_month"):
        df[col] = pd.to_datetime(df[col]).dt.strftime("%Y-%m")
    df["spike_alert"] = df["spike_alert"].astype(bool)
    df["price_is_real"] = df["price_is_real"].astype(bool)
    _df = df


def load():
    if _df is None:
        raise RuntimeError("call sokoradar_data.use(result) first")
    return _df


def counties():
    return sorted(load()["county"].unique())


def outlook(county, commodity, price_type, horizon=1):
    """One forecast row (a dict), or None."""
    df = load()
    r = df[(df["county"] == county) & (df["commodity"] == commodity) &
           (df["price_type"] == price_type) & (df["horizon"] == horizon)]
    return None if r.empty else r.iloc[0].to_dict()


def county_alerts(county, horizon=1):
    """Crops in this county with a jump warning, one row per crop (retail first when both warn)."""
    df = load()
    a = df[(df["county"] == county) & (df["horizon"] == horizon) & df["spike_alert"]]
    a = a.sort_values("price_type", key=lambda s: s.map({"Retail": 0, "Wholesale": 1}))
    a = a.drop_duplicates("commodity")
    return sorted(a.to_dict("records"), key=lambda r: CROPS.index(r["commodity"]))
