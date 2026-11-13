"""Transport costs for "where to buy", taken from notebooks/05_recommender.ipynb.

Same rules and assumptions as the notebook:
- Nearby means county centres within 200 km. Road distances come from data/county_road_distance.csv
  (41 of 47 counties); other pairs use straight-line distance x 1.3.
- Hire rates come from the government vehicle hire card (data/govt_vehicle_hire_rates.csv). Fuel use and the
  driver and handling cost per trip are the notebook's assumptions.
- Fuel is priced at the EPRA pump price in the buyer's county (data/fuel_prices_by_county.csv), or the national
  average if the county is missing.
- The vehicle is paid for both ways, and a part-empty vehicle costs the same as a full one.
- A county is suggested only if it is still at least 5% cheaper after transport.
"""
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parent.parent
DATA = REPO / "data"
COUNTIES = Path(__file__).resolve().parent / "raw_data" / "counties.csv"

RADIUS_KM = 200
ROAD_FACTOR = 1.3
RETURN_FACTOR = 2
MIN_GAIN = 0.05
# vehicle, hire card item, capacity in kg (lower end of the card's range), fuel, fuel use in L/km (assumed),
# driver and handling per trip in KES (assumed)
VEHICLES = [("Pickup 4x2 (1 t)", 30, 1000, "diesel", 0.12, 1000),
            ("Flat-bed truck 2.5-5 t", 1, 2500, "diesel", 0.14, 1000),
            ("Flat-bed truck 5-7 t", 2, 5000, "diesel", 0.20, 1000),
            ("Flat-bed truck 12 t", 4, 12000, "diesel", 0.30, 1000),
            ("Flat-bed truck 20 t", 6, 20000, "diesel", 0.38, 1000)]


def load_inputs():
    """Vehicle rates, fuel prices and neighbour pairs with road distances (notebook 05, cells 6 and 7)."""
    card = pd.read_csv(DATA / "govt_vehicle_hire_rates.csv")
    rows = []
    for name, item, cap, fuel_type, l_km, fixed in VEHICLES:
        r = card[(card["item"] == item) & (card["basic_unit"] == "KM")].iloc[0]
        assert r["description"] in ("Pick UP 4x2", "Truck flat bed"), (item, r["description"])
        rows.append([name, cap, fuel_type, l_km, r["dry_hire_private_kes"], r["min_charge_per_day_kes"], fixed])
    rates = pd.DataFrame(rows, columns=["mode", "capacity_kg", "fuel_type", "fuel_l_per_km", "hire_rate_per_km",
                                        "min_charge_per_trip", "fixed_cost_per_trip"]).set_index("mode")

    fuelc = pd.read_csv(DATA / "fuel_prices_by_county.csv")
    fuel = {"diesel": fuelc.set_index("county")["diesel_mean"].to_dict(),
            "petrol": fuelc.set_index("county")["petrol_mean"].to_dict()}
    fuel_national = {"diesel": fuelc["diesel_mean"].mean(), "petrol": fuelc["petrol_mean"].mean()}

    cty = pd.read_csv(COUNTIES)[["county", "center_lat", "center_lon"]]
    lat, lon = np.radians(cty["center_lat"].values), np.radians(cty["center_lon"].values)
    a = (np.sin((lat[:, None] - lat[None, :]) / 2) ** 2
         + np.cos(lat)[:, None] * np.cos(lat)[None, :] * np.sin((lon[:, None] - lon[None, :]) / 2) ** 2)
    km = 2 * 6371 * np.arcsin(np.sqrt(a))
    ii, jj = np.where((km <= RADIUS_KM) & (km > 0))
    pairs = pd.DataFrame({"county_a": cty["county"].values[ii], "county_b": cty["county"].values[jj],
                          "km": km[ii, jj].round(0)})
    road = pd.read_csv(DATA / "county_road_distance.csv")[["county_a", "county_b", "road_km"]]
    pairs = pairs.merge(road, on=["county_a", "county_b"], how="left")
    pairs["road_measured"] = pairs["road_km"].notna()
    pairs.loc[~pairs["road_measured"], "road_km"] = pairs.loc[~pairs["road_measured"], "km"] * ROAD_FACTOR
    return rates, fuel, fuel_national, pairs


def transport_per_kg(road_km, qty, m, fuel_price):
    """KES per kg to move qty kg a road distance, paying the vehicle both ways (notebook 05, cell 16)."""
    trips = np.ceil(qty / m["capacity_kg"])
    rt = np.asarray(road_km, dtype=float) * RETURN_FACTOR
    return trips * (np.maximum(rt * m["hire_rate_per_km"], m["min_charge_per_trip"])
                    + rt * m["fuel_l_per_km"] * fuel_price + m["fixed_cost_per_trip"]) / qty


def advise(county, local_price, candidates, qty_kg, vehicle, inputs):
    """Best nearby county after transport for one buyer. candidates: DataFrame with county_b, price (recorded this month).
    Returns (table of every nearby option, best row or None)."""
    rates, fuel, fuel_national, pairs = inputs
    m = rates.loc[vehicle]
    fuel_price = fuel[m["fuel_type"]].get(county, fuel_national[m["fuel_type"]])      # buyer's county
    c = pairs[pairs["county_a"] == county].merge(candidates, on="county_b")
    if c.empty:
        return c, None
    c = c.assign(transport=transport_per_kg(c["road_km"], qty_kg, m, fuel_price))
    c["gross"] = local_price - c["price"]
    c["net"] = c["gross"] - c["transport"]
    c = c.sort_values("net", ascending=False).reset_index(drop=True)
    best = c.iloc[0]
    return c, (best if best["net"] >= MIN_GAIN * local_price else None)


def smallest_paying_load(saving_per_kg, road_km, vehicle, county, inputs):
    """Smallest load at which the saving pays for the trip (notebook 05, cell 16). None if no load up to 3 vehicles."""
    rates, fuel, fuel_national, _ = inputs
    m = rates.loc[vehicle]
    fuel_price = fuel[m["fuel_type"]].get(county, fuel_national[m["fuel_type"]])
    grid = np.arange(10, 3 * m["capacity_kg"], 10)
    ok = grid[transport_per_kg(road_km, grid, m, fuel_price) < saving_per_kg]
    return int(ok.min()) if len(ok) else None
