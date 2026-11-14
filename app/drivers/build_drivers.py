"""Extend app/raw_data/national_drivers_2006_2024.csv from January 2025 to October 2026.

Only the columns the forecast model reads are extended, each with the same source and method as the 2006-2024 rows
(checked on the months where both exist). Every other column is left empty for the new months, as before.

  KES per USD                         CBK daily rates (sheet "exchange rates" in moa_daily_market_prices.xlsx), monthly mean
  Murban crude (USD/bbl)              OPEC basket (same file) x 1.003032, the ratio the team file used from Jul 2024
  Diesel (KES/L)                      EPRA Nairobi diesel, day-weighted monthly mean, scaled to the team level at Dec 2024
  Overall inflation, 12-month (%)     CBK inflation table
  CPI index (Feb 2019=100, chained)   KNBS CPI releases (October 2025 and October 2026)
  ONI (El Nino index), ENSO phase     NOAA oni.ascii.txt, season centred on the month, 1 decimal; >= 0.5 El Nino, <= -0.5 La Nina
"""
import math
import sys
from pathlib import Path

import pandas as pd

D = Path(sys.argv[1])            # folder with the sources (app/drivers/sources plus moa_daily_market_prices.xlsx)
TEAM = Path(sys.argv[2])         # team national_drivers_2006_2024.csv
OUT = Path(sys.argv[3])
NEW = pd.period_range("2025-01", "2026-10", freq="M").strftime("%Y-%m")

ref = pd.read_csv(TEAM)
ref["Month"] = ref["Month"].astype(str)
ref = ref[ref["Month"] <= "2024-12"].reset_index(drop=True)      # the original 2006-2024 rows; the rest is rebuilt


def monthly(sheet, date_col, value_col):
    x = pd.read_excel(D / "moa_daily_market_prices.xlsx", sheet_name=sheet)[[date_col, value_col]]
    x[date_col] = pd.to_datetime(x[date_col], errors="coerce")
    x[value_col] = pd.to_numeric(x[value_col], errors="coerce")
    m = x.dropna().set_index(date_col)[value_col].resample("MS").mean()
    m.index = m.index.strftime("%Y-%m")
    return m


fx = monthly("exchange rates", "DATE", "KES/USD")
opec = monthly("opec basket", "Date", "Opec Basket Price ($)")
MURBAN_RATIO = 1.003032
diesel = pd.read_csv(D / "diesel_nairobi_monthly.csv").set_index("month")["diesel_kes_l"]
DIESEL_SCALE = ref.set_index("Month").loc["2024-12", "Diesel (KES/L)"] / diesel["2024-12"]
infl = pd.read_csv(D / "cbk_inflation.csv").set_index("month")["inflation_12m"]
cpi = pd.read_csv(D / "cpi_inflation_2024_10_2026_10.csv").set_index("month")["cpi_index"]

oni = pd.read_csv(D / "oni.txt", sep=r"\s+")
CENTRE = {"DJF": 1, "JFM": 2, "FMA": 3, "MAM": 4, "AMJ": 5, "MJJ": 6, "JJA": 7, "JAS": 8, "ASO": 9, "SON": 10, "OND": 11, "NDJ": 12}
oni["month"] = oni["YR"].astype(str) + "-" + oni["SEAS"].map(CENTRE).map("{:02d}".format)
oni = oni.set_index("month")["ANOM"]
round1 = lambda v: math.copysign(math.floor(abs(v) * 10 + 0.5) / 10, v) + 0.0       # 1.05 -> 1.1, -0.85 -> -0.9 as in the team file

rows = []
for m in NEW:
    r = {c: None for c in ref.columns}
    r["Month"] = m
    r["KES per USD"] = fx.get(m)
    r["Murban crude (USD/bbl)"] = opec[m] * MURBAN_RATIO if m in opec else None
    r["Diesel (KES/L)"] = diesel[m] * DIESEL_SCALE if m in diesel else None
    r["Overall inflation, 12-month (%)"] = infl.get(m)
    r["CPI index (Feb 2019=100, chained)"] = cpi.get(m)
    if m in oni:
        v = round1(oni[m])
        r["ONI (El Nino index)"] = v
        r["ENSO phase"] = "El Nino" if v >= 0.5 else ("La Nina" if v <= -0.5 else "Neutral")
    rows.append(r)

# the 2006-2024 lines are copied as they are (byte for byte); the new months are added after them
text = TEAM.read_text(encoding="utf-8").splitlines()
old_lines = [text[0]] + [line for line in text[1:] if line.split(",")[0] <= "2024-12"]
new_lines = pd.DataFrame(rows, columns=ref.columns).to_csv(index=False, header=False).splitlines()
OUT.write_text("\n".join(old_lines + new_lines) + "\n", encoding="utf-8")
print(f"Saved {OUT.name}: {len(ref)} old rows + {len(rows)} new rows ({NEW[0]} to {NEW[-1]}); diesel scale {DIESEL_SCALE:.4f}")
