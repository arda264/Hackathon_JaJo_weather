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
- **`route.html`** — the record route, Lowestoft → IJmuiden: the optimised track and
  sampled wind on a Mapbox map, plus the out-of-sample robustness ranking from
  `route/app/gribs/robustness.json`. This is the former standalone `dutchsail_route`
  app, rewritten in this site's vanilla-JS style (the original used React from a CDN).

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

The deploy is **static only**. `route.html`'s **Update route** control needs a live
optimiser at `/api/route`, and that endpoint is **not deployed** — the page runs on
its stored sample route instead and says so in a banner.

It was tried and reverted: building `route/api/index.py` with `@vercel/python`
fails, because the optimiser needs `pygrib` to read the forecast GRIB and that
pulls in ECCODES, a native library the Vercel Python runtime does not provide. A
failing function build fails the **whole** deployment, so the site stops updating
entirely — which is worse than losing one button.

To bring the endpoint back you need a runtime that can install `pygrib` (a
container-based host, or a Vercel function with a custom image), then re-add to
`vercel.json`:

```json
{ "src": "route/api/index.py", "use": "@vercel/python",
  "config": { "includeFiles": "route/{route.py,polars.json,forecast/grib.grb2}" } }
```

listed **before** the `**/*` static entry, plus a rewrite from `/api/route`. Check
the rewrite destination — the legacy builder may want `/route/api/index` without
the extension.

## Notes

- Blend weights are embedded in `assets/common.js`; re-copy them from
  `forecast_blend/results/weights.json` after retraining.
- Locations are the four ERA5 grid points the blend was trained on.
- Theme toggle cycles auto → light → dark (persisted in `localStorage`).
- `route.html` posts to `/api/route` first and falls back to the stored
  `data/route-sample.json` whenever that endpoint is missing or errors — which is
  always the case when the site is opened from disk or served by
  `python -m http.server`. The page shows a banner when it is on the fallback, so the
  sample is never passed off as a live result. Regenerate it with
  `python route/export_sample_route.py`. It is built from the *synthetic* nominal
  wind field, not the forecast GRIB, because reading the GRIB needs `pygrib`.
- Mapbox GL is loaded from a CDN — the one external dependency on the site. If it is
  blocked, `route.html` degrades to a message and the numbers above the map still render.
