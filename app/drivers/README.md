# Model drivers after 2024

The forecast script reads two driver files in `app/raw_data`. Both now run to October 2026.

| File | What was added | Source |
|---|---|---|
| `national_drivers_2006_2024.csv` | January 2025 to October 2026 for the columns the model uses: KES per USD, Murban crude, diesel, 12-month inflation, CPI index, El Niño index (ONI) and ENSO phase | CBK, OPEC, EPRA, KNBS, NOAA |
| `county_climate_chirps_ndvi.csv` | Vegetation (NDVI) for September (now complete) and October 2026, all 47 counties | WFP MODIS NDVI on HDX |

The file name still says 2006_2024 because the forecast script and the pipeline look for that name.

## How each column was extended (same method as 2006 to 2024, checked on the months where both exist)

| Column | Method | Check |
|---|---|---|
| KES per USD | Monthly mean of CBK daily rates (sheet "exchange rates" in the MoA file `moa_daily_market_prices.xlsx`) | Same as the team file for all 60 overlapping months |
| Murban crude (USD/bbl) | OPEC basket (same MoA file) x 1.003032, the ratio the team file used from July 2024 | Same method |
| Diesel (KES/L) | EPRA Nairobi diesel, day-weighted mean per calendar month, scaled to the team value at December 2024 (x 0.9949) | December 2024 within 0.5% before scaling |
| Overall inflation, 12-month (%) | CBK inflation table | December 2024 the same (2.99%) |
| CPI index (Feb 2019=100, chained) | KNBS CPI releases for October 2025 and October 2026 | October to December 2024 the same; CPI-implied inflation matches CBK within 0.01 points in every new month |
| ONI (El Niño index), ENSO phase | NOAA `oni.ascii.txt`, the 3-month season centred on the month, 1 decimal; 0.5 or more El Niño, -0.5 or less La Niña | Within 0.05 of the team file (NOAA revises old values slightly). October 2026 is not out yet and is left empty |
| Vegetation (county) | Sub-counties joined into counties weighted by pixels, 10-day values averaged per month; % of normal = monthly mean of 100 x NDVI / its long-term average | Reproduces the team file from 2005 to August 2026 (99% of months within 0.00002) |

Columns the model does not read (Brent, food and fuel inflation, world prices, national rainfall and others) are left
empty for the new months, as they could not be rebuilt the same way.

With these files the forecast script runs with no "inputs missing" warning. Forecasts, jump warnings and ranges are
unchanged; only the drivers behind each forecast (the SHAP explanations) use the new data.

## Updating again

```
python app/drivers/build_drivers.py <folder> app/raw_data/national_drivers_2006_2024.csv app/raw_data/national_drivers_2006_2024.csv
python app/drivers/update_ndvi.py ken-ndvi-subnat-full.csv app/raw_data/county_climate_chirps_ndvi.csv 2026-11
```

`<folder>` holds the files in `app/drivers/sources` (updated with the new months) plus `moa_daily_market_prices.xlsx`.
`ken-ndvi-subnat-full.csv` is the Kenya sub-national NDVI file from WFP on HDX (data.humdata.org, search "Kenya NDVI"). The 2006 to 2024
rows are copied unchanged; only the months after them are rebuilt.
