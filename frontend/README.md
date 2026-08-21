# DutchSail weather frontend

Static site — no build step, no dependencies.

- **`index.html`** — overview: live check whether the preferred sailing conditions
  are met (18–30 kt from 205–235° or 305–335°, ≥ 6 consecutive hours, judged on the
  blend) now and per day for the week ahead, plus the upcoming ECMWF wind forecast.
- **`current.html`** — live current conditions: six Open-Meteo models fetched in one
  call and combined with the learned weights from
  `forecast_blend/results/weights.json` (speed weights for speed/gusts, direction
  weights on unit vectors for direction).
- **`wind.html`** — detailed wind: 7-day hourly blend drawn over every individual
  model, gusts, and model spread, plus the generated climatology figures
  (sailing-window heatmap/calendars, wind timeseries). Legend entries toggle models;
  every chart has a crosshair tooltip and a table view.
- **`tide.html`** — sea level with next high/low water, tidal stream, and wave
  height from the Open-Meteo Marine API.
- **`forecast-blend.html`** — the blend itself: learned weights, held-out metrics
  table, and the evaluation figure.

## Run

From the **repository root** (the pages reference `../output/figures` and
`../forecast_blend/results`):

```
python -m http.server 8000
```

then open <http://localhost:8000/frontend/>. Opening `frontend/index.html` directly
from disk also works — the live pages call the Open-Meteo APIs over HTTPS.

## Deploy on Vercel

The site deploys as-is — no build step. The whole repo is served statically
(the pages reference figures in `output/` and `forecast_blend/`), and the root
`vercel.json` redirects `/` to `/frontend/`.

1. [vercel.com/new](https://vercel.com/new) → import this GitHub repo.
2. Framework preset **Other**, leave build command and output directory empty.
3. Deploy. The site lands on `https://<project>.vercel.app/` (→ `/frontend/`).

Or from the CLI: `npx vercel` from the repo root (then `npx vercel --prod`).

## Notes

- Blend weights are embedded in `assets/common.js`; re-copy them from
  `forecast_blend/results/weights.json` after retraining.
- Locations are the four ERA5 grid points the blend was trained on.
- Theme toggle cycles auto → light → dark (persisted in `localStorage`).
