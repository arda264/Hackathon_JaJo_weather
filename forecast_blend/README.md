# Forecast-model blending against ERA5

Learns **one weight per weather forecast model** so their blended 10 m wind
forecast matches the "real" data (ERA5 reanalysis, `wind_data/ERA5hourly10m.grib`)
as closely as possible over the southern North Sea corridor.

## How it works

1. **`fetch_forecasts.py`** downloads *archived past forecasts* from the free
   [Open-Meteo Historical Forecast API](https://open-meteo.com/en/docs/historical-forecast-api)
   (no API key) for six models — ECMWF IFS 0.25°, NOAA GFS, DWD ICON-EU,
   Météo-France ARPEGE Europe, KNMI HARMONIE-AROME NL, UKMO Global 10 km — at four
   ERA5 grid points inside `geometry/area_of_interest.geojson`, hourly,
   2024-07-02 → 2026-08-13 (the common availability window of all six models).
   Speed/direction are converted to u/v components so vectors can be blended.
2. **`train_blend.py`** extracts ERA5 u10/v10 truth at the same points, merges
   on time+location, and solves the constrained least-squares problem

   ```
   min_w  Σ ‖ Σ_m w_m·(u_m, v_m)  −  (u_ERA5, v_ERA5) ‖²
   s.t.   w_m ≥ 0,  Σ_m w_m = 1
   ```

   (SLSQP over the probability simplex). The constraint keeps weights
   interpretable: `w_m` is literally how much to trust model *m*.

## Honest evaluation

Weights are fit on the **first 75 %** of the record (chronological); every
reported number comes from the **held-out final 25 %**. The blend is compared
against each individual model, the equal-weight ensemble, and an unconstrained
OLS reference. Metrics: wind-vector RMSE, speed RMSE/MAE/bias, direction MAE
(hours with ERA5 speed > 2 m/s only).

## Outputs (`results/`)

- `weights.json` — learned weights + training metadata
- `metrics.csv` — held-out metrics per source
- `blend_evaluation_{light,dark}.png` — weights + accuracy comparison

## Run

```
python forecast_blend/fetch_forecasts.py   # ~24 API calls, a few minutes
python forecast_blend/train_blend.py       # first run reads the 1 GB GRIB once
```

Requires: `numpy pandas scipy matplotlib requests xarray cfgrib eccodes`.
Intermediate data is cached in `data/` (gitignored).
