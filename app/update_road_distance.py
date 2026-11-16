"""Rebuild data/county_road_distance.csv with today's road distances for all 47 counties.

Where to buy used the Ministry of Roads distance matrix from 1994, which covers only 41 of 47 counties; the
other pairs fell back to straight-line km x 1.3. This script measures every pair on today's road network:

  1. Takes the location of each county's main town (TOWNS below, read off OpenStreetMap) and checks it lies
     in that county (within 150 km of the county centre in app/raw_data/counties.csv).
  2. Asks the OSRM routing service for the driving distance between every pair of towns, in one request.
  3. Keeps the old file as data/county_road_distance_1994.csv and writes the new one in the same format,
     so app/transport.py needs no change.

Run from the repo root (needs internet, a few seconds):  python app/update_road_distance.py
Sources: OpenStreetMap contributors (ODbL), routing by OSRM.
"""
import math
import shutil
import sys
from pathlib import Path

import pandas as pd
import requests

REPO = Path(__file__).resolve().parent.parent
OUT = REPO / "data" / "county_road_distance.csv"
OLD = REPO / "data" / "county_road_distance_1994.csv"
COUNTIES = REPO / "app" / "raw_data" / "counties.csv"
HEADERS = {"User-Agent": "SokoRadar capstone (Moringa School) road distances"}
MAX_KM_FROM_CENTRE = 150

# main town of each county: (town, lat, lon). Lamu uses the Mokowe jetty, where the road ends.
TOWNS = {
    "Mombasa": ("Mombasa", -4.043, 39.668), "Kwale": ("Kwale", -4.174, 39.452), "Kilifi": ("Kilifi", -3.630, 39.849),
    "Tana River": ("Hola", -1.486, 40.030), "Lamu": ("Lamu", -2.230, 40.844),
    "Taita Taveta": ("Wundanyi", -3.399, 38.364), "Garissa": ("Garissa", -0.453, 39.646),
    "Wajir": ("Wajir", 1.747, 40.057), "Mandera": ("Mandera", 3.937, 41.856), "Marsabit": ("Marsabit", 2.334, 37.990),
    "Isiolo": ("Isiolo", 0.354, 37.582), "Meru": ("Meru", 0.047, 37.649), "Tharaka-Nithi": ("Chuka", -0.333, 37.646),
    "Embu": ("Embu", -0.531, 37.450), "Kitui": ("Kitui", -1.367, 38.010), "Machakos": ("Machakos", -1.517, 37.263),
    "Makueni": ("Wote", -1.781, 37.629), "Nyandarua": ("Ol Kalou", -0.270, 36.379), "Nyeri": ("Nyeri", -0.420, 36.947),
    "Kirinyaga": ("Kerugoya", -0.499, 37.280), "Murang'a": ("Murang'a", -0.721, 37.153),
    "Kiambu": ("Kiambu", -1.171, 36.835), "Turkana": ("Lodwar", 3.119, 35.597),
    "West Pokot": ("Kapenguria", 1.239, 35.112), "Samburu": ("Maralal", 1.097, 36.698),
    "Trans Nzoia": ("Kitale", 1.016, 35.006), "Uasin Gishu": ("Eldoret", 0.514, 35.270),
    "Elgeyo-Marakwet": ("Iten", 0.673, 35.508), "Nandi": ("Kapsabet", 0.204, 35.105),
    "Baringo": ("Kabarnet", 0.492, 35.743), "Laikipia": ("Nanyuki", 0.006, 37.072), "Nakuru": ("Nakuru", -0.303, 36.080),
    "Narok": ("Narok", -1.081, 35.871), "Kajiado": ("Kajiado", -1.852, 36.776), "Kericho": ("Kericho", -0.368, 35.284),
    "Bomet": ("Bomet", -0.782, 35.342), "Kakamega": ("Kakamega", 0.282, 34.752), "Vihiga": ("Mbale", 0.083, 34.719),
    "Bungoma": ("Bungoma", 0.563, 34.561), "Busia": ("Busia", 0.460, 34.111), "Siaya": ("Siaya", 0.061, 34.288),
    "Kisumu": ("Kisumu", -0.092, 34.768), "Homa Bay": ("Homa Bay", -0.527, 34.457),
    "Migori": ("Migori", -1.063, 34.473), "Kisii": ("Kisii", -0.682, 34.767), "Nyamira": ("Nyamira", -0.563, 34.935),
    "Nairobi": ("Nairobi", -1.286, 36.817),
}


def km_between(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return 2 * 6371 * math.asin(math.sqrt(a))


def main():
    cty = pd.read_csv(COUNTIES).set_index("county")
    names = list(cty.index)
    missing = sorted(set(names) - set(TOWNS))
    if missing:
        sys.exit(f"STOP: no town for {missing}. Nothing was changed.")

    print(f"1. Checking {len(names)} county towns lie in their county...")
    for c in names:
        far = km_between(*TOWNS[c][1:], cty.at[c, "center_lat"], cty.at[c, "center_lon"])
        if far > MAX_KM_FROM_CENTRE:
            sys.exit(f"STOP: {TOWNS[c][0]} is {far:.0f} km from the centre of {c}. Nothing was changed.")
    print("   all OK")

    print("2. Measuring road distances between every pair (OSRM)...")
    coords = ";".join(f"{TOWNS[c][2]:.4f},{TOWNS[c][1]:.4f}" for c in names)
    r = requests.get(f"https://router.project-osrm.org/table/v1/driving/{coords}", headers=HEADERS, timeout=120,
                     params={"annotations": "distance"})
    r.raise_for_status()
    js = r.json()
    if js.get("code") != "Ok":
        sys.exit(f"STOP: routing failed ({js.get('code')}). Nothing was changed.")
    dist = js["distances"]

    rows = []
    for i, a in enumerate(names):
        for j, b in enumerate(names):
            if i == j:
                continue
            d = dist[i][j]
            if d is None:
                sys.exit(f"STOP: no road found from {a} to {b}. Nothing was changed.")
            rows.append([a, b, round(d / 1000), TOWNS[a][0], TOWNS[b][0]])
    new = pd.DataFrame(rows, columns=["county_a", "county_b", "road_km", "town_a_used", "town_b_used"])

    if not OLD.exists():
        shutil.copy(OUT, OLD)
    old = pd.read_csv(OLD)
    new.to_csv(OUT, index=False)

    both = new.merge(old, on=["county_a", "county_b"], suffixes=("", "_1994"))
    ratio = (both["road_km"] / both["road_km_1994"]).median()
    print(f"3. Wrote {len(new):,} county pairs to {OUT.relative_to(REPO)} (1994 file: {len(old):,}, 41 counties).")
    print(f"   Old file kept as {OLD.relative_to(REPO)}. Median new / 1994 distance: {ratio:.2f}")
    checks = [("Kakamega", "Bomet"), ("Kakamega", "Kisumu"), ("Nairobi", "Mombasa"), ("Garissa", "Nairobi"),
              ("Nairobi", "Nakuru"), ("Nairobi", "Nyeri"), ("Nairobi", "Embu"), ("Mombasa", "Kwale"),
              ("Nakuru", "Narok"), ("Machakos", "Makueni")]
    for a, b in checks:
        km = new[(new.county_a == a) & (new.county_b == b)]["road_km"].iloc[0]
        print(f"   {TOWNS[a][0]} to {TOWNS[b][0]}: {km} km")


if __name__ == "__main__":
    main()
