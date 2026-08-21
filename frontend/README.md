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
  sampled wind on a Mapbox map, today's forecast figure, and the out-of-sample
  robustness ranking from `route/app/gribs/robustness.json`. This is the former
  standalone `dutchsail_route` app, rewritten in this site's vanilla-JS style (the
  original used React from a CDN). The track and the figure are **regenerated daily**
  by `.github/workflows/daily-forecast.yml` — see "Daily forecast" below.

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

## Daily forecast

`.github/workflows/daily-forecast.yml` runs at 11:30 UTC every day:

1. `route/fetch_forecast.py` downloads the newest published NOAA GFS 0.25° cycle —
   just 10 m u/v over the corridor bounding box, ~10 kB for 13 forecast hours, no API
   key. It walks backwards through cycles until one answers, so a late or skipped run
   still gets a valid forecast.
2. `route/daily_forecast.py` re-optimises the route against it and rewrites
   `frontend/data/route-today.json` plus `output/figures/daily/forecast_route_{light,dark}.png`.
3. The job commits those files, which is what triggers a Vercel redeploy.

Yesterday's outputs are **replaced, not archived** — the paths are fixed, so the page
never needs to know today's date. Run it by hand with the **Actions → Daily forecast
route → Run workflow** button, or locally:

```
python route/fetch_forecast.py && python route/daily_forecast.py
```

The daily job deliberately avoids `pygrib`: `daily_forecast.py` reads GRIB through
xarray/cfgrib (binary wheels, no system ECCODES) and injects its own `wind_at` into
`route.route`, so the optimiser never imports a GRIB library. That is why this runs
in CI when the Vercel function could not.

Each run commits ~210 kB of PNG, so the repo grows roughly 75 MB/year. If that
becomes a problem, drop the figure DPI in `daily_forecast.py` or render the chart
client-side from `route-today.json` instead.

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
