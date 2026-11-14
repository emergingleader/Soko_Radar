"""Add the newest county vegetation (NDVI) to app/raw_data/county_climate_chirps_ndvi.csv.

Source: HDX ken-ndvi-subnat-full.csv (WFP, MODIS NDVI every 10 days by sub-county).
Same method as the existing file (checked: it reproduces 2005 to Aug 2026): sub-counties are joined into their county
weighted by pixel count, then the 10-day values are averaged per month.
    ndvi      = monthly mean of the county NDVI (vim)
    ndvi_pct  = monthly mean of 100 x NDVI / its long-term average for that 10-day period (vim / vim_avg)
Only the months given are written, and only when all 3 ten-day periods are in for every county. Rainfall is untouched.
    python update_ndvi.py ken-ndvi-subnat-full.csv county_climate_chirps_ndvi.csv 2026-09 2026-10
"""
import sys
import pandas as pd

src, target, months = sys.argv[1], sys.argv[2], sys.argv[3:]
d = pd.read_csv(src)
a = d[d["adm_level"] == 2].copy()
a["county_pcode"], a["m"] = a["PCODE"].str[:5], a["date"].str[:7]
a["wv"], a["wa"] = a["vim"] * a["n_pixels"], a["vim_avg"] * a["n_pixels"]
dek = a.groupby(["county_pcode", "date", "m"]).agg(v=("wv", "sum"), av=("wa", "sum"), n=("n_pixels", "sum")).reset_index()
dek["ndvi"], dek["ndvi_pct"] = dek["v"] / dek["n"], 100 * dek["v"] / dek["av"]
g = dek.groupby(["county_pcode", "m"]).agg(ndvi=("ndvi", "mean"), ndvi_pct=("ndvi_pct", "mean"), k=("date", "nunique")).reset_index()

c = pd.read_csv(target)
c["m"] = c["month"].str[:7]
for m in months:
    new = g[g["m"] == m].set_index("county_pcode")
    rows = c["m"] == m
    need = set(c.loc[rows, "county_pcode"])
    if not rows.any() or not need <= set(new.index) or (new.loc[list(need), "k"] < 3).any():
        print(f"{m}: skipped (not all counties have 3 ten-day periods yet)")
        continue
    c.loc[rows, "ndvi"] = c.loc[rows, "county_pcode"].map(new["ndvi"]).values
    c.loc[rows, "ndvi_pct"] = c.loc[rows, "county_pcode"].map(new["ndvi_pct"]).values
    print(f"{m}: vegetation written for {rows.sum()} counties")
# write back by editing only the changed lines, so every other line stays byte-for-byte the same
text = open(target, encoding="utf-8").read()
lines = text.splitlines()
head = lines[0].split(",")
i_ndvi, i_pct = head.index("ndvi"), head.index("ndvi_pct")
changed = {(r.county_pcode, r.month): (r.ndvi, r.ndvi_pct) for r in c[c["m"].isin(months)].itertuples()}
for j in range(1, len(lines)):
    f = lines[j].split(",")
    key = (f[0], f[1])
    if key in changed and pd.notna(changed[key][0]):
        f[i_ndvi], f[i_pct] = repr(float(changed[key][0])), repr(float(changed[key][1]))
        lines[j] = ",".join(f)
open(target, "w", encoding="utf-8", newline="\n").write("\n".join(lines) + ("\n" if text.endswith("\n") else ""))
