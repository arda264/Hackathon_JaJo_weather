# DutchSail weather frontend

Static site — no build step, no dependencies.

- **`index.html`** — overview: the generated figures (sailing-window climatology,
  wind timeseries, forecast-blend evaluation) with light/dark variants that follow
  the theme.
- **`current.html`** — live current conditions: six Open-Meteo models fetched in one
  call and combined with the learned weights from
  `forecast_blend/results/weights.json` (speed weights for speed/gusts, direction
  weights on unit vectors for direction).
- **`wind.html`** — detailed wind: 7-day hourly blend drawn over every individual
  model, gusts, and model spread. Legend entries toggle models; every chart has a
  crosshair tooltip and a table view.
- **`tide.html`** — sea level with next high/low water, tidal stream, and wave
  height from the Open-Meteo Marine API.

## Run

From the **repository root** (the pages reference `../output/figures` and
`../forecast_blend/results`):

```
python -m http.server 8000
```

then open <http://localhost:8000/frontend/>. Opening `frontend/index.html` directly
from disk also works — the live pages call the Open-Meteo APIs over HTTPS.

## Notes

- Blend weights are embedded in `assets/common.js`; re-copy them from
  `forecast_blend/results/weights.json` after retraining.
- Locations are the four ERA5 grid points the blend was trained on.
- Theme toggle cycles auto → light → dark (persisted in `localStorage`).
