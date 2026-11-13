"""Build app/raw_data/prices_2025_2026.csv: county prices from Jan 2025 to the latest month of raw prices, made by the
team's own data pipeline (sokoradar_pipeline.py, notebook 00), so the app can forecast from the newest month.

Run from the repo folder (the pipeline is not in the repo; pass its path and the raw data folder):
    python app/build_prices_2025_2026.py <path to sokoradar_pipeline.py> <raw data folder> [end month, default 2026-09]

What it does, without touching any file in the repo except the output:
  1. Copies the pipeline to a temporary folder and changes only its end month (END and the MoA month range), so months
     after the MoA daily file are filled by the pipeline's own rule (MoA bulletin trend, else seasonal growth).
     Two national series with no source after 2024 (milk from Apr 2026, dried fish) are held at their last value,
     flagged "Carried forward (no newer source)".
  2. Runs it and keeps only the new months.
  3. Joins them to data/SokoRadar_County_2006_2024_long.csv: the 2006-2024 prices are never changed, and estimated
     2025-26 prices are scaled by each series' small Dec 2024 difference so the two parts join smoothly. Prices
     recorded in a market are kept as recorded.
The deployed models are unchanged (trained on answers up to Dec 2024). Tested on Jan 2025 - Jun 2026 recorded prices:
forecast error 8.9 / 10.6 / 12.4 % at 1 / 2 / 3 months, in line with the 2015-2024 backtest.
"""
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pandas as pd

APP = Path(__file__).resolve().parent
REPO = APP.parent
PANEL = REPO / "data" / "SokoRadar_County_2006_2024_long.csv"
OUT = APP / "raw_data" / "prices_2025_2026.csv"

PATCHES = [  # (line as in the team's pipeline, replacement)
    ("START, END = pd.Timestamp('2006-01-01'), pd.Timestamp('2024-12-01')",
     "START, END = pd.Timestamp('2006-01-01'), pd.Timestamp('{end}-01')"),
    ("MOA_MONTHS = pd.date_range('2019-01-01', '2025-01-01', freq='MS')",
     "MOA_MONTHS = pd.date_range('2019-01-01', END, freq='MS')"),
    ("    NAT = pd.DataFrame(NAT)[[c for c, *_ in COMMODITIES]]; NFLAG = pd.DataFrame(NFLAG)[NAT.columns]",
     "    NAT = pd.DataFrame(NAT)[[c for c, *_ in COMMODITIES]]; NFLAG = pd.DataFrame(NFLAG)[NAT.columns]\n"
     "    tail = NAT.isna() & np.asarray(NAT.index > pd.Timestamp('2024-12-01'))[:, None]\n"
     "    NAT = NAT.ffill(); NFLAG = NFLAG.mask(tail, 'Carried forward (no newer source)')"),
]


def main():
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    pipeline, raw = Path(sys.argv[1]), Path(sys.argv[2])
    end = sys.argv[3] if len(sys.argv) > 3 else "2026-09"
    work = Path(tempfile.mkdtemp(prefix="sokoradar_pipeline_"))
    code = pipeline.read_text(encoding="utf-8")
    for old, new in PATCHES:
        if code.count(old) != 1:
            sys.exit(f"The pipeline does not contain this line exactly once; has it changed?\n  {old}")
        code = code.replace(old, new.format(end=end))
    (work / "sokoradar_pipeline.py").write_text(code, encoding="utf-8")
    print(f"Running the team pipeline to {end} in {work} ...")
    env = {**os.environ, "SOKORADAR_RAW": str(raw), "PYTHONIOENCODING": "utf-8"}
    subprocess.run([sys.executable, "sokoradar_pipeline.py"], cwd=work, env=env, check=True)
    new = pd.read_csv(work / "output" / "SokoRadar_County_2006_2024_long.csv")
    repo = pd.read_csv(PANEL)

    k = ["county", "commodity", "price_type"]
    seam = new[new["month"] == "2024-12"].merge(repo[repo["month"] == "2024-12"], on=k + ["month"],
                                                 suffixes=("_new", "_repo"))
    seam["ratio"] = seam["price_kes_repo"] / seam["price_kes_new"]
    ext = new[new["month"] >= "2025-01"].merge(seam[k + ["ratio"]], on=k)
    est = ~ext["flag"].str.startswith("Observed")
    ext.loc[est, "price_kes"] = (ext.loc[est, "price_kes"] * ext.loc[est, "ratio"]).round(2)
    ext = ext.drop(columns="ratio")[repo.columns].sort_values(["county_code", "commodity", "price_type", "month"])
    n_series = repo.groupby(k).ngroups
    assert len(ext) == n_series * ext["month"].nunique() and ext["price_kes"].gt(0).all()
    ext.to_csv(OUT, index=False)
    shutil.rmtree(work, ignore_errors=True)
    print(f"Saved {len(ext):,} rows ({ext['month'].min()} to {ext['month'].max()}) to {OUT}")


if __name__ == "__main__":
    main()
