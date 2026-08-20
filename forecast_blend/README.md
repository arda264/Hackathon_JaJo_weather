# Forecast-model blending against ERA5

Learns **two weights per weather forecast model — one for wind speed, one for
wind direction** — so their blended 10 m wind forecast matches the "real" data
(ERA5 reanalysis, `wind_data/ERA5hourly10m.grib`) as closely as possible over
the southern North Sea corridor.

## How it works

1. **`fetch_forecasts.py`** downloads *archived past forecasts* from the free
   [Open-Meteo Historical Forecast API](https://open-meteo.com/en/docs/historical-forecast-api)
   (no API key) for six models — ECMWF IFS 0.25°, NOAA GFS, DWD ICON-EU,
   Météo-France ARPEGE Europe, KNMI HARMONIE-AROME NL, UKMO Global 10 km — at four
   ERA5 grid points inside `geometry/area_of_interest.geojson`, hourly,
   2024-07-02 → 2026-08-13 (the common availability window of all six models).
   Speed/direction are converted to u/v components so vectors can be blended.
2. **`train_blend.py`** extracts ERA5 u10/v10 truth at the same points, merges
   on time+location, and solves two constrained least-squares problems
   (SLSQP over the probability simplex, `w_m ≥ 0, Σ w_m = 1` for each set):

   ```
   speed:      min_ws  Σ ( Σ_m ws_m·s_m  −  s_ERA5 )²
   direction:  min_wd  Σ ‖ Σ_m wd_m·e_m  −  e_ERA5 ‖²
   ```

   where `s_m` is model *m*'s wind speed and `e_m` the **unit vector** of its
   wind direction — direction is circular, so 350° and 10° must blend to 0°,
   never 180°; the blended direction is the angle of the weighted unit-vector
   sum. The simplex constraint keeps weights interpretable: `w_m` is literally
   how much to trust model *m* for that quantity.

## Honest evaluation

Weights are fit on the **first 75 %** of the record (chronological); every
reported number comes from the **held-out final 25 %**. The blend is compared
against each individual model and the equal-weight ensemble. Metrics: speed
RMSE/MAE/bias and direction MAE (direction fit and scored on hours with ERA5
speed > 2 m/s, where a direction is physically meaningful).

## Outputs (`results/`)

- `weights.json` — learned speed + direction weights and training metadata
- `metrics.csv` — held-out metrics per source
- `blend_evaluation_{light,dark}.png` — weights + accuracy comparison

## Run

```
python forecast_blend/fetch_forecasts.py   # ~24 API calls, a few minutes
python forecast_blend/train_blend.py       # first run reads the 1 GB GRIB once
```

Requires: `numpy pandas scipy matplotlib requests xarray cfgrib eccodes`.
Intermediate data is cached in `data/` (gitignored).
