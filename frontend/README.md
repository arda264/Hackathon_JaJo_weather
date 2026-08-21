# DutchSail weather frontend

Static site — no build step, no dependencies.

**The browser makes no forecast API calls.** All forecast data is fetched — and
every graph rendered — by the Claude agent: `python agent/run_agent.py` makes **one
API call to Claude**, and the agent (following the skills in `.agents/skills/`)
downloads the data, computes the blend and the sailing-window verdict, and writes
`output/figures/agent/*_{light,dark}.png` plus `output/results/agent/summary.json`.
The pages display those files. See [`agent/README.md`](../agent/README.md).

- **`index.html`** — overview: whether the preferred sailing conditions are met
  (18–30 kt from 205–235° or 305–335°, ≥ 6 consecutive hours, judged on the blend)
  at the agent's run hour and per day for the week ahead, plus the agent's 7-day
  wind figure.
- **`current.html`** — conditions at the agent's run hour: six models combined with
  the learned weights from `forecast_blend/results/weights.json`, the next-24-hours
  figure, and the per-model table.
- **`wind.html`** — detailed wind: the agent's 7-day figure (blend over every
  individual model, gusts, model spread), plus the generated climatology figures
  (sailing-window heatmap/calendars, wind timeseries).
- **`tide.html`** — sea level with next high/low water, tidal stream, and wave
  height, plus Copernicus Marine quick-look maps when the agent ran with
  credentials.
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

For the map on `route.html`, put your Mapbox public token in `.env` at the repo
root (copy `.env.example`) and generate the gitignored token file once:

```
python scripts/write_mapbox_token.py
```

## Deploy on Vercel

The whole repo is served statically (the pages reference figures in `output/` and
`forecast_blend/`), and the root `vercel.json` redirects `/` to `/frontend/`. The
only build step is the `buildCommand` in `vercel.json`, which writes
`frontend/assets/mapbox-token.js` from the `MAPBOX_TOKEN` environment variable —
the token is never committed (GitHub push protection on this repo rejects it).

1. [vercel.com/new](https://vercel.com/new) → import this GitHub repo.
2. Framework preset **Other** — build command, output directory, and install
   command all come from `vercel.json`.
3. Project → Settings → Environment Variables → add `MAPBOX_TOKEN` with your
   Mapbox public (`pk.`) token. Without it the site still deploys; only the
   route map falls back to its "no token" message.
4. Deploy. The site lands on `https://<project>.vercel.app/` (→ `/frontend/`).

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

## Agent pipeline (replaces the browser's forecast API calls)

`python agent/run_agent.py` is the project's **single Claude API call**. It starts
one agentic run (`claude-opus-5` with shell/read/write tools); the agent reads the
skills in `.agents/skills/` (`get-forecast`, `weather-statistics`), fetches
Open-Meteo wind + marine data and — with credentials — the Copernicus Marine
forecasts, computes the blend and the window verdicts, and renders every graph in
light and dark. Outputs (all committed, since the site is static):

- `output/figures/agent/wind_forecast_{light,dark}.png` — index, wind
- `output/figures/agent/wind_next24_{light,dark}.png` — current
- `output/figures/agent/tide_{light,dark}.png` — tide
- `output/figures/agent/{currents_map,waves_map}_{light,dark}.png` — tide (optional)
- `output/results/agent/summary.json` — tiles, verdicts, and the model table

## API calls

Every network call the site makes. The browser no longer contacts any forecast
API — the former `fetchWind()`/`fetchMarine()` calls to Open-Meteo were replaced
by the agent pipeline above.

**All data fetching lives in `output/scripts/api.js`** — the single data-access layer.
Pages and `assets/common.js` never call `fetch()` directly; they call the functions
below (`fetchAgentSummary`, `fetchLiveRoute`, `fetchStoredRoute`, `fetchRouteSummary`,
`fetchRobustness`). To change an endpoint, a parameter, or a fallback order, change
`output/scripts/api.js`. The only network activity outside it is the Mapbox GL
library `<script>`/`<link>` in `route.html`'s head and the tiles that library
loads itself.

### External (browser → third-party)

| Call | Made by | What / how |
| --- | --- | --- |
| `GET https://api.mapbox.com/mapbox-gl-js/v3.26.0/mapbox-gl.{js,css}` | `route.html` `<head>` | Mapbox GL library from the CDN — the site's only external script. If blocked, the map degrades to a message; the rest of the page still works. |
| Mapbox style + tile requests (`api.mapbox.com`, `events.mapbox.com`) | Mapbox GL at runtime on `route.html` | Loads `mapbox://styles/mapbox/outdoors-v12` plus its vector tiles, sprites, and glyphs, authenticated with the `pk.` token from `assets/mapbox-token.js`. Skipped entirely when no token is configured. |

### Same-origin (browser → this site)

| Call | Made by | What / how |
| --- | --- | --- |
| `GET output/results/agent/summary.json` | `index.html`, `current.html`, `wind.html`, `tide.html` via `fetchAgentSummary()` in `output/scripts/api.js` | The agent's machine-readable summary (blend now, day verdicts, model table, tide numbers). Cache-busted with a timestamp query because the file is rewritten in place. |
| `POST /api/route` (JSON `{current}`, 45 s timeout) | `route.html` **Update route** button via `fetchLiveRoute()` in `output/scripts/api.js` | The live optimiser. **Not deployed** (see above) — the request fails and the page falls back to the stored route, with a banner. |
| `GET frontend/data/route-today.json` | `route.html` on load via `fetchStoredRoute()` in `output/scripts/api.js` | Today's optimised route, rewritten daily by CI. |
| `GET frontend/data/route-sample.json` | `route.html` fallback via `fetchStoredRoute()` in `output/scripts/api.js` | Synthetic sample route, used only when `route-today.json` is missing and the API errors. |
| `GET route/app/gribs/summary.json` | `route.html` on load via `fetchRouteSummary()` in `output/scripts/api.js` | Forecast-cycle metadata for the header line. |
| `GET route/app/gribs/robustness.json` | `route.html` on load via `fetchRobustness()` in `output/scripts/api.js` | Out-of-sample robustness ranking table. |

The generated figures (`output/figures/…`, PNG) are loaded as plain `<img>`
elements, not fetches.

### CI (GitHub Actions → third-party)

| Call | Made by | What / how |
| --- | --- | --- |
| `GET https://nomads.ncep.noaa.gov/cgi-bin/filter_gfs_0p25.pl` | `route/fetch_forecast.py` in `.github/workflows/daily-forecast.yml` | NOAA GFS 0.25° GRIB filter: 10 m u/v wind only, corridor bounding box 51.5–53.5°N / 1.0–5.0°E, 13 forecast hours (~10 kB total). Walks back through cycles until one answers. No key. |

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

- The agent reads the blend weights from `forecast_blend/results/weights.json` on
  every run — nothing to re-copy after retraining; just rerun the agent.
- The agent works at the mid-corridor ERA5 grid point (52.5°N 3.0°E); the point is
  recorded in `summary.json` and shown on each page.
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
- The Mapbox token comes from `MAPBOX_TOKEN` in `.env` (local, via
  `scripts/write_mapbox_token.py`) or in Vercel's environment variables (deploy) —
  both routes generate the gitignored `assets/mapbox-token.js`. Use a `pk.`
  **public** token (made to be embedded client-side) and scope it to the site's
  URLs in the Mapbox dashboard if abuse is a concern. The map uses the stock
  `mapbox/outdoors-v12` style, which any token can load.
