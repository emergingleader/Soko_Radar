"""All words the USSD menu and the SMS use come from translations.csv: one row per phrase, one column per language.

Columns: sw Kiswahili, en English, so Somali, ki Gikuyu, luo Dholuo, luy Luluhya, kam Kikamba, kln Kalenjin, mer Kimeru.

To add a language: a native speaker fills its column in translations.csv (it opens in Excel; save as CSV UTF-8),
keeping {county}, {month}, {crop}, {phase} and {items} exactly as they are. As soon as every row of a column is filled,
the language appears on the first screen. Then run  python test_ussd.py  to check every screen still fits on a phone.
Please have each column checked by a second speaker: farmers act on these words.
"""
import csv
from pathlib import Path

FILE = Path(__file__).parent / "translations.csv"
ORDER = ["sw", "en", "so", "ki", "luo", "luy", "kam", "kln", "mer"]     # order on the first screen
CROP_KEYS = ["Dry Maize", "Beans Rosecoco", "Sorghum", "Red Irish Potatoes"]
CHOOSE_LANGUAGE = "Lugha / Language / Luqadda:"


def _load():
    with open(FILE, newline="", encoding="utf-8-sig") as f:
        # headers may be "ki" or "ki (Gikuyu)": only the code before the first space counts
        rows = [{(k or "").split(" ")[0]: v for k, v in r.items()} for r in csv.DictReader(f)]
    text = {}
    for code in ORDER:
        col = {r["key"]: (r.get(code) or "").strip() for r in rows}
        if not all(col.values()):                 # a language goes live only when every phrase is written
            continue
        text[code] = {
            **{k: v for k, v in col.items() if not k.startswith(("main_", "crop_", "type_", "phase_", "month_"))},
            "main": [col[f"main_{i}"] for i in range(1, 5)],
            "crops": {c: col[f"crop_{c}"] for c in CROP_KEYS},
            "types": {t: col[f"type_{t}"] for t in ("Retail", "Wholesale")},
            "phase": {p: col[f"phase_{p}"] for p in ("Normal", "Stress", "Alert", "Crisis")},
            "months": [col[f"month_{i}"] for i in range(1, 13)],
        }
    return text


TEXT = _load()
LANGUAGES = [c for c in ORDER if c in TEXT]       # at most 9, so the first screen stays one page


def t(lang):
    return TEXT.get(lang, TEXT["sw"])


def month(lang, yyyy_mm):
    y, m = str(yyyy_mm).split("-")[:2]
    return f"{t(lang)['months'][int(m) - 1]} {y}"
