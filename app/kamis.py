"""Ministry of Agriculture market prices (KAMIS) as recorded county prices.

KAMIS (kamis.kilimo.go.ke, Markets) lists one wholesale and one retail price per market per day. Its "Export to
Excel" files are turned into one monthly price per county, food and price type (the median across markets and
days) and kept in app/raw_data/kamis_monthly.csv, flagged "Observed (KAMIS)" so the models and Where to buy count
them as recorded prices. app/update_prices.py puts them into prices_after_2024.csv each month: a KAMIS price
replaces an estimated price for the same county, food, price type and month; WFP recorded prices are kept.

Add new KAMIS exports (one file per food, as many pages as needed), from the repo folder:
    python app/kamis.py <Market_Prices files>              # adds them to app/raw_data/kamis_monthly.csv
    python app/update_prices.py --no-download              # or wait for the monthly update
"""
import sys
from pathlib import Path

import pandas as pd

APP = Path(__file__).resolve().parent
MONTHLY = APP / "raw_data" / "kamis_monthly.csv"
COUNTIES = APP / "raw_data" / "counties.csv"
FLAG = "Observed (KAMIS)"
FIRST_MONTH = "2025-01"                  # the team panel covers 2006 to 2024; KAMIS fills the months after
LOW, HIGH = 0.4, 2.5                     # drop prices below 40% or above 250% of that food's national median that month

# KAMIS names that differ from the team's
COUNTY_FIX = {"Taita-Taveta": "Taita Taveta", "Tana-River": "Tana River", "Uasin-Gishu": "Uasin Gishu",
              "Trans-Nzoia": "Trans Nzoia", "West-Pokot": "West Pokot", "Homa-bay": "Homa Bay", "Homa-Bay": "Homa Bay", "Muranga": "Murang'a",
              "Tharaka Nithi": "Tharaka-Nithi", "Elgeyo Marakwet": "Elgeyo-Marakwet", "Elgeyo-marakwet": "Elgeyo-Marakwet"}
CROP_FIX = {"Beans (Canadian wonder)": "Beans Canadian", "Beans (Mwitemania)": "Beans Mwitemania",
            "Red Irish potato": "Red Irish Potatoes", "White Sorghum": "Sorghum"}
# the variety the team's series follows (foods not listed keep every variety)
KEEP_CLASS = {"Dry Maize": "White Maize", "Eggs": "Exotic/Grade"}
COLUMNS = ["month", "county_code", "county", "commodity", "price_type", "unit", "price_kes", "flag", "n_markets"]


def read_exports(files):
    parts = []
    for f in files:
        f = str(f)
        d = pd.read_csv(f) if f.endswith(".csv") else pd.read_excel(f, engine="openpyxl")
        print(f"read {Path(f).name}: {len(d)} rows")
        parts.append(d)
    raw = pd.concat(parts, ignore_index=True)
    return raw.drop_duplicates(subset=["Commodity", "Classification", "Market", "County", "Date", "Wholesale", "Retail"])


def to_monthly(raw, foods):
    """Daily market prices -> one median price per county, food, price type and month (complete months only)."""
    counties = pd.read_csv(COUNTIES)
    d = raw.copy()
    for c in ("Commodity", "Classification", "Market", "County"):
        d[c] = d[c].astype(str).str.strip()
    d["county"] = d["County"].replace(COUNTY_FIX)
    d["Commodity"] = d["Commodity"].replace(CROP_FIX)
    d["date"] = pd.to_datetime(d["Date"])
    unknown = sorted(set(d["county"]) - set(counties["county"]))
    if unknown:
        print("left out (not a county):", ", ".join(unknown))
    d = d[d["county"].isin(counties["county"]) & d["Commodity"].isin(foods) & (d["date"] >= FIRST_MONTH)]
    for food, cls in KEEP_CLASS.items():
        d = d[(d["Commodity"] != food) | (d["Classification"] == cls)]
    d["month"] = d["date"].dt.strftime("%Y-%m")
    under_way = raw["Date"].pipe(pd.to_datetime).max().strftime("%Y-%m")   # the month of the newest day is not over
    d = d[d["month"] < under_way]

    long = d.melt(id_vars=["Commodity", "Market", "county", "month"], value_vars=["Wholesale", "Retail"],
                  var_name="price_type", value_name="raw_price")
    long["unit"] = "KES/" + long["raw_price"].astype(str).str.extract(r"/\s*(\w+)", expand=False).str.lower()
    long["price"] = pd.to_numeric(long["raw_price"].astype(str).str.split("/").str[0].str.strip(), errors="coerce")
    long = long[long["price"] > 0].rename(columns={"Commodity": "commodity"})
    med = long.groupby(["commodity", "price_type", "month"])["price"].transform("median")
    ok = long["price"].between(LOW * med, HIGH * med)
    print(f"impossible prices dropped: {(~ok).sum()} of {len(long)}")
    m = (long[ok].groupby(["month", "county", "commodity", "price_type", "unit"])
         .agg(price_kes=("price", "median"), n_markets=("Market", "nunique")).reset_index())
    m["price_kes"] = m["price_kes"].round(2)
    m["flag"] = FLAG
    m = m.merge(counties[["county", "code"]].rename(columns={"code": "county_code"}), on="county")
    return m[COLUMNS].sort_values(["commodity", "price_type", "county", "month"]).reset_index(drop=True)


def apply(prices, kamis):
    """Replace estimated prices with KAMIS prices (same county, food, price type, month and unit)."""
    key = ["month", "county", "commodity", "price_type"]
    k = kamis[key + ["unit", "price_kes", "n_markets"]].rename(
        columns={"unit": "k_unit", "price_kes": "k_price", "n_markets": "k_n"})
    t = prices.merge(k, on=key, how="left")
    swap = t["k_price"].notna() & ~t["flag"].astype(str).str.startswith("Observed") & (t["unit"] == t["k_unit"])
    t.loc[swap, "price_kes"] = t.loc[swap, "k_price"]
    t.loc[swap, "flag"] = FLAG
    t.loc[swap, "n_markets"] = t.loc[swap, "k_n"]
    print(f"KAMIS: {int(swap.sum()):,} estimated prices replaced by recorded market prices")
    return t[prices.columns]


def main(files):
    if not files:
        sys.exit(__doc__)
    foods = set(pd.read_csv(APP / "raw_data" / "prices_after_2024.csv", usecols=["commodity"])["commodity"])
    new = to_monthly(read_exports(files), foods)
    if MONTHLY.exists():                     # keep earlier months; newer exports win for the same month
        old = pd.read_csv(MONTHLY)
        key = ["month", "county", "commodity", "price_type"]
        old = old.merge(new[key], on=key, how="left", indicator=True)
        new = pd.concat([old[old["_merge"] == "left_only"][COLUMNS], new], ignore_index=True)
    new = new.sort_values(["commodity", "price_type", "county", "month"]).reset_index(drop=True)
    new.to_csv(MONTHLY, index=False)
    print(f"Saved {MONTHLY.name}: {len(new):,} monthly prices, {new['county'].nunique()} counties, "
          f"{new['month'].min()} to {new['month'].max()}")


if __name__ == "__main__":
    main(sys.argv[1:])
