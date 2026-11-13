"""Update the app's prices.

Downloads the latest WFP Kenya food prices from HDX, runs the team's pipeline (app/pipeline/sokoradar_pipeline.py)
up to the newest month, and saves the months after 2024 to app/raw_data/prices_after_2024.csv. The app then
forecasts the 3 months after that month. The GitHub Action in .github/workflows/update-prices.yml runs this monthly.

Usage, from the repo folder:
    python app/update_prices.py                 # download from HDX and update
    python app/update_prices.py --no-download   # use only the raw data stored in the pipeline
    python app/update_prices.py --raw <folder>  # add newer raw files you have, such as a new MoA bulletin

Steps:
1. Raw data: the files stored in the pipeline, then any files from --raw, then the WFP download.
2. Run a copy of the pipeline in a temporary folder with only its end month changed. Months after the MoA daily
   file are filled by the pipeline's own rule (MoA bulletin trend, otherwise seasonal growth). National series
   with no data after 2024 are kept at their last value.
3. Add the new months to data/SokoRadar_County_2006_2024_long.csv without changing 2006 to 2024. Estimated new
   prices are scaled by each series' Dec 2024 difference so the two parts line up. Recorded prices are kept as is.

The models are not retrained (they learned from data up to Dec 2024). On Jan 2025 to Jun 2026 recorded prices the
forecast error was 8.9%, 10.6% and 12.4% at 1, 2 and 3 months, close to the 2015 to 2024 backtest.
"""
import argparse
import base64
import io
import json
import lzma
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path

import pandas as pd

APP = Path(__file__).resolve().parent
REPO = APP.parent
PIPELINE = APP / "pipeline" / "sokoradar_pipeline.py"
PANEL = REPO / "data" / "SokoRadar_County_2006_2024_long.csv"
OUT = APP / "raw_data" / "prices_after_2024.csv"
HDX_DATASET = "wfp-food-prices-for-kenya"
HDX_FILES = {"wfp_food_prices_ken.csv": "food_prices", "wfp_markets_ken.csv": "markets"}

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


def embedded_raw(code: str, raw: Path):
    """Unpack the raw files embedded at the end of the pipeline (its own fallback when there is no raw folder)."""
    blob = code.split('EMBEDDED_RAW_DATA = """', 1)[1].split('"""', 1)[0]
    with tarfile.open(fileobj=io.BytesIO(lzma.decompress(base64.b64decode("".join(blob.split()))))) as t:
        for m in t.getmembers():
            if m.isfile():
                (raw / Path(m.name).name).write_bytes(t.extractfile(m).read())


def download_hdx(raw: Path):
    """Latest WFP Kenya food prices and markets from HDX (public CKAN API)."""
    api = f"https://data.humdata.org/api/3/action/package_show?id={HDX_DATASET}"
    req = urllib.request.Request(api, headers={"User-Agent": "sokoradar-updater"})
    with urllib.request.urlopen(req, timeout=60) as r:
        resources = json.load(r)["result"]["resources"]
    for name, key in HDX_FILES.items():
        url = next(x["url"] for x in resources if key in x["url"] and x["url"].endswith(".csv"))
        req = urllib.request.Request(url, headers={"User-Agent": "sokoradar-updater"})
        with urllib.request.urlopen(req, timeout=300) as r:
            (raw / name).write_bytes(r.read())
        print(f"Downloaded {name} from HDX")


def latest_month(wfp_csv: Path) -> str:
    w = pd.read_csv(wfp_csv, skiprows=[1], usecols=["date"])        # row 2 is an HXL tag row
    return pd.to_datetime(w["date"]).max().strftime("%Y-%m")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--no-download", action="store_true", help="do not download from HDX")
    ap.add_argument("--raw", help="folder with newer raw files to use (they replace the embedded ones)")
    ap.add_argument("--end", help="last month to build, e.g. 2026-10 (default: latest month in the WFP file)")
    args = ap.parse_args()

    work = Path(tempfile.mkdtemp(prefix="sokoradar_update_"))
    raw = work / "raw"; raw.mkdir()
    code = PIPELINE.read_text(encoding="utf-8")
    embedded_raw(code, raw)
    if args.raw:
        for f in Path(args.raw).iterdir():
            if f.is_file():
                shutil.copy(f, raw / f.name)
    if not args.no_download:
        download_hdx(raw)
    end = args.end or latest_month(raw / "wfp_food_prices_ken.csv")
    print(f"Building county prices to {end}")

    for old, new in PATCHES:
        if code.count(old) != 1:
            sys.exit(f"The pipeline does not contain this line exactly once; has it changed?\n  {old}")
        code = code.replace(old, new.format(end=end))
    (work / "sokoradar_pipeline.py").write_text(code, encoding="utf-8")
    env = {**os.environ, "SOKORADAR_RAW": str(raw), "PYTHONIOENCODING": "utf-8", "MPLBACKEND": "Agg"}
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
    assert len(ext) == repo.groupby(k).ngroups * ext["month"].nunique() and ext["price_kes"].gt(0).all()
    ext.to_csv(OUT, index=False)
    shutil.rmtree(work, ignore_errors=True)
    print(f"Saved {len(ext):,} rows ({ext['month'].min()} to {ext['month'].max()}) to {OUT}")
    latest = pd.Timestamp(ext["month"].max())
    print(f"Prices now run to {latest:%B %Y}. The app will forecast "
          f"{latest + pd.DateOffset(months=1):%B %Y} to {latest + pd.DateOffset(months=3):%B %Y}.")
    if os.environ.get("GITHUB_OUTPUT"):                               # tell the GitHub Action the new month
        with open(os.environ["GITHUB_OUTPUT"], "a") as f:
            f.write(f"latest={end}\n")


if __name__ == "__main__":
    main()
