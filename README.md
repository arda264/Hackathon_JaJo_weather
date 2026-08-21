# DutchSail

Weather analysis and route planning for a sailing record attempt in the southern
North Sea, **Lowestoft → IJmuiden**. Hackathon project.

The question the whole repo answers: *on which days is the wind in the corridor
strong enough, from the right quarter, for long enough — and what track should
the boat sail when it is?* Everything else is plumbing around that.

Three halves (it's that kind of project):

- **Climatology** — five years of ERA5 over the corridor, turned into "how often
  does a usable window actually occur" figures and CSVs (`output/`).
- **Forecast** — a learned six-model blend (`forecast_blend/`), refreshed daily by
  a Claude agent (`agent/`) that fetches the data and draws every graph the site
  shows.
- **Route** (`route/`) — the optimiser, the robustness suite that ranks tracks by
  how well they survive a wrong forecast, and the LLM brief. Merged in from the
  standalone `dutchsail_route` repo as a git subtree, so its history is in this log.

---

## Quick start

The site is static — no build step, no npm, no server-side code. Serve the
**repository root** (not `frontend/`), because the pages reference
`output/figures/`, `output/results/`, `forecast_blend/results/`, and
`route/app/gribs/`:

```sh
python -m http.server 8000     # then open http://localhost:8000/frontend/
```

That's enough to browse everything that's committed. To *regenerate* the data you
need Python and, for the live forecast, an Anthropic API key — see
[Running the pipelines](#running-the-pipelines).

---

## Repository layout

| Path | What lives there |
|---|---|
| `frontend/` | The static site — seven linked pages (plus two superseded files), `assets/style.css`, `assets/common.js`. No framework. |
| `agent/` | `run_agent.py`, the project's single Claude API call. Fetches forecasts and renders every figure the site shows. |
| `.agents/` | **Skills** the agent reads before it works — `get_forecast` and `weather_statistics`, each a `SKILL.md` plus runnable examples. |
| `output/scripts/` | Climatology scripts, plus `api.js` — the front end's one data-access layer. |
| `output/figures/`, `output/results/` | Generated PNGs, CSVs, and `agent/summary.json`. Committed, because the site is served statically. |
| `forecast_blend/` | Fits the six-model blend weights against ERA5; `results/weights.json` is the artifact everything else consumes. |
| `route/` | Route optimiser, robustness suite, daily-forecast job, LLM brief. Has its own `README.md` and `CLAUDE.md`. |
| `scripts/` | Sample Copernicus downloads, the area-of-interest postprocessors and animators, Mapbox token writer. |
| `geometry/` | The corridor polygons (`area_of_interest.geojson`, `50_75_100.geojson`). |
| `sample_forecast_data/` | Checked-in NetCDF samples plus their `postprocessed/` CSVs and `figures/` PNGs and GIFs, so the wave and current work can be done offline. |
| `credentials/` | Copernicus Marine credentials. **Gitignored** — never commit it. |
| `.github/workflows/` | Two scheduled jobs: `agent-refresh.yml` (05:30 UTC) and `daily-forecast.yml` (11:30 UTC). |

### `.agents/` vs `agent/` — they are different things

An easy trip-up, since the names differ by one character and a dot:

- **`.agents/`** is the *skills library* — reference material. `.agents/skills/get_forecast/`
  documents how to pull Copernicus Marine wave and current forecasts and plot them;
  `.agents/skills/weather_statistics/` covers wind roses, directional histograms, and
  percentile maps. Nothing here runs on its own; the agent reads it.
- **`agent/`** (singular) is the *runner* — `run_agent.py`, the script you actually
  execute. It builds a prompt that includes a one-line index of every skill in
  `.agents/skills/`, then lets the agent go read the ones it needs.

So: `.agents/` is what the agent knows, `agent/` is what the agent is.

---

## The site

| Page | What it shows |
|---|---|
In nav order:

| Page | What it shows |
|---|---|
| `index.html` | Are the preferred conditions there — now, and for the week ahead |
| `wind.html` | 7-day hourly outlook per model, plus the climatology figures |
| `tidalcurrent.html` | Sea level, next high/low water, tidal stream, wave height, and the currents corridor map |
| `waves.html` | Wind-sea and swell over the crossing area — the Copernicus corridor map and the area-of-interest timeseries |
| `history.html` | Past conditions for the crossing area. **Scaffold only** — header, nav, and an empty content div; nothing renders yet |
| `forecast-blend.html` | The learned weights and what accuracy they buy |
| `route.html` | The optimised track on a map, and its robustness ranking |

**Two files are superseded but still in the tree:** `tide.html` (replaced by
`tidalcurrent.html`) and `current.html` (blended wind right now). Neither is linked
from the nav any more — the only links to them are in their own stale headers — so
they're reachable only by typing the URL. `current.html` is the sole page that
displays the `wind_next24` figure, which the agent still generates every run.

**The browser makes no forecast API calls.** That used to be the design; it isn't
anymore. Pages read PNGs as plain `<img>` tags and pull numbers from
`output/results/agent/summary.json`. All fetching is funnelled through
`output/scripts/api.js` (`fetchAgentSummary`, `fetchStoredRoute`, `fetchLiveRoute`,
`fetchRouteSummary`, `fetchRobustness`) — change an endpoint there, nowhere else.
The only third-party traffic left is Mapbox GL on the route page.

`frontend/README.md` has the exhaustive call-by-call table and the Vercel details.

---

## Where the numbers come from

Five upstream sources, each used for exactly one job:

| Source | Used for | Where it's wired |
|---|---|---|
| **Open-Meteo Forecast API** — six models, hourly, 7 days | Wind speed / direction / gusts, blended into the headline verdict | `agent/run_agent.py` § Data sources |
| **Open-Meteo Marine API** — hourly, 5 days | Sea level, tidal stream, **significant wave height** | `agent/run_agent.py` § Data sources |
| **Copernicus Marine** — NW Shelf 1.5 km | The corridor wave and current **map figures**, and the wind-sea/swell breakdown behind the wave warnings | `.agents/skills/get_forecast/`, `scripts/get_sample_*.py`, `scripts/postprocess_*.py` |
| **NOAA GFS 0.25°** — GRIB filter, ~10 kB/cycle | The daily route optimisation | `route/fetch_forecast.py` |
| **ERA5 reanalysis** — hourly 10 m wind | Ground truth for the climatology and the blend weights | `output/scripts/`, `forecast_blend/train_blend.py` |

### Wind — Open-Meteo, six models

```
GET https://api.open-meteo.com/v1/forecast
  ?latitude=52.5&longitude=3.0
  &hourly=wind_speed_10m,wind_direction_10m,wind_gusts_10m
  &models=ecmwf_ifs025,gfs_global,icon_eu,meteofrance_arpege_europe,
          knmi_harmonie_arome_netherlands,ukmo_global_deterministic_10km
  &wind_speed_unit=ms&timeformat=unixtime&forecast_days=7
```

No API key. Response `hourly` keys come back suffixed per model id. Speed and
gusts are blended with the `speed` weights from `forecast_blend/results/weights.json`
(weighted mean over the models that reported, weights renormalised); direction is
blended on **unit vectors** and recovered with `atan2`, because 350° and 10° must
average to 0°, not 180°. Model spread = max − min speed across models per hour.

### Waves and tide — Open-Meteo Marine

```
GET https://marine-api.open-meteo.com/v1/marine
  ?latitude=52.5&longitude=3.0
  &hourly=sea_level_height_msl,wave_height,ocean_current_velocity,
          ocean_current_direction
  &timeformat=unixtime&forecast_days=5
```

No key. Current velocity arrives in km/h and is converted to knots (`kt = kmh / 1.852`).
This is the source of **the single wave-height number** — panel (c) of the `tide`
figure, with the current-hour value written to `summary.json` as `tide.wave_height_m`.
It's one total significant height, with no wind-sea/swell split; for that, see
Copernicus below.

### Waves and currents (maps) — Copernicus Marine

A different, higher-resolution source, used for the two corridor map figures and for
everything that needs wind-sea and swell separated:

- **Waves** — dataset `cmems_mod_nws_wav_anfc_1.5km_PT1H-i`, variables `VHM0_SW1`
  (swell significant height), `VHM0_WW` (wind-sea significant height), plus the
  matching periods `VTM01_*` and directions `VMDR_*`. Note it's split into swell
  and wind-sea rather than one total *Hs*.
- **Currents** — dataset `cmems_mod_nws_phy-cur_anfc_1.5km-2D_PT1H-i`, variables `uo`
  and `vo` (eastward/northward components; speed and direction are derived).
- Bounding box: 1.670–4.713°E, 52.219–52.998°N.

Copernicus needs an account. Credentials live at
`credentials/.copernicusmarine-credentials` (gitignored); **without them the agent
skips `currents_map` and `waves_map` and records why in `summary.json` → `notes`.**
Everything else still works. To create the file locally:

```sh
pixi run -e copernicus python scripts/get_sample_wave_forecast.py
```

It prompts for your username and password, writes the credentials, and downloads a
week of wave data into `sample_forecast_data/`.

> **`copernicusmarine` 2.x quirk**, learned the hard way and worth knowing before you
> debug it again: `login()` writes to `configuration_file_directory`, while the
> `credentials_file` argument only controls where `subset()` *reads* from — and
> `login()` returns `False` on bad credentials instead of raising. Both are handled
> in `scripts/get_sample_wave_forecast.py`.

### The sailing-window criterion

`weather_window_definition.md` is the domain expert's spec and the authority here.
The structure it sets out is **wind gates the window; waves and currents are
context** you report once the wind gate is open. The track runs west → east, which
is what "opposing" means below.

**Wind — the gate.** All three must hold:

- **Speed** 18–30 kt (`1 kt = 0.514444 m/s`)
- **Direction** 205–235° **or** 305–335° (degrees from north, coming *from*)
- **Sustained ≥ 6 consecutive hours** within a local day

Evaluated at the corridor mid-point, lat **52.5**, lon **3.0** for the live agent,
and over `geometry/area_of_interest.geojson` for the climatology. Always state the
m/s ↔ kt conversion when you report a number — the spec asks for it explicitly.

**Waves — no hard limit, but three warnings.** Raise a flag when:

| Condition | Warning |
|---|---|
| Wind-sea *Hs* > 2 m | Potentially too high |
| *Hs* > 0.5 m opposing the track (0–180° in absolute terms) | Opposing waves |
| Wind-sea *Hs* > 1 m **and** steepness > 0.05 | Steep wind-sea |

Steepness is `Hs / (g·Tm01² / 2π)`, computed for wind-sea and swell separately by
`scripts/postprocess_wave_conditions_area_of_interest.py`. The definition file carries
the full interpretation table, from "< 0.015, long swell, gentle motion" up to
"> 0.070, close to breaking". Alongside the warnings, report wind-sea height and
direction — absolute **and** relative to the boat's heading — and whether there's
significant swell.

**Tidal currents — context only.** Never limiting. Report the range of conditions
during the favourable window, and the timing and direction of the peak velocities.

---

## Running the pipelines

### Environments

Python is managed with **pixi** (`pyproject.toml`), which declares three environments:

| Environment | Contents | For |
|---|---|---|
| `default` | numpy, pandas, xarray, geopandas, netcdf4, dask | Climatology and general work |
| `metocean` | + windrose, scipy, cmocean | The statistics figures |
| `copernicus` | Python 3.13, `copernicusmarine`, `h5py` | Copernicus downloads only |

```sh
pixi run check-env            # or check-metocean / check-copernicus
```

The environments are declared for **linux-64**. On Windows or macOS `pixi run` may
refuse to solve — fall back to any Python 3.11+ with
`pip install requests numpy pandas xarray netcdf4 matplotlib copernicusmarine`.
`route/` has its own `requirements.txt` (and a slimmer `requirements-daily.txt` for CI).

### The agent — the daily refresh

```sh
pip install anthropic
export ANTHROPIC_API_KEY=sk-ant-...     # Windows: set ANTHROPIC_API_KEY=...
python agent/run_agent.py
```

One agentic run on `claude-opus-5` with four tools (shell, read, write, list) and an
output contract. It reads the skills, fetches the data, computes the blend, and writes:

| Artifact | Shown on |
|---|---|
| `output/figures/agent/wind_forecast_{light,dark}.png` | index, wind |
| `output/figures/agent/wind_next24_{light,dark}.png` | `current.html` only — superseded, so nothing in the nav shows it |
| `output/figures/agent/tide_{light,dark}.png` | tidal current |
| `output/figures/agent/currents_map_{light,dark}.png` | tidal current (needs Copernicus) |
| `output/figures/agent/waves_map_{light,dark}.png` | waves (needs Copernicus) |
| `output/results/agent/summary.json` | every page — tiles, verdicts, model table |

Every figure comes in a light and a dark variant, ~1400 px wide, palette matched to
`frontend/assets/style.css`. Figure timestamps are labelled UTC. A full refresh takes
a few minutes. Scope it down with a custom instruction:

```sh
python agent/run_agent.py "Only regenerate the tide figure"
```

Commit the refreshed figures and `summary.json` to publish them — the site is static,
so the commit *is* the deploy. `agent/README.md` documents the contract in full.

### Sample wave and current data

A second, offline track that works straight from the checked-in NetCDF in
`sample_forecast_data/` — no Anthropic key, no live fetch. All four need the
`metocean` environment:

```sh
pixi run -e metocean python scripts/postprocess_wave_conditions_area_of_interest.py
pixi run -e metocean python scripts/postprocess_currents_conditions_area_of_interest.py
pixi run -e metocean python scripts/animate_sample_wave_forecast.py
pixi run -e metocean python scripts/animate_sample_currents_forecast.py
```

The postprocessors clip the forecast to `geometry/area_of_interest.geojson`, take the
spatial mean per timestep, and write CSV (and NetCDF, for waves) to
`sample_forecast_data/postprocessed/` plus a timeseries PNG to
`sample_forecast_data/figures/`. The wave one is where **steepness** is computed —
four rows: height, period, mean direction, steepness, with swell in blue and wind-sea
in red. The animators render one frame per timestep as a GIF; both **fix their colour
limits over the whole period** so the scale doesn't flicker between frames. Refresh
the underlying data with `scripts/get_sample_{wave,currents}_forecast.py`
(`copernicus` environment).

### Climatology and blend

```sh
python output/scripts/wind_window_days.py       # sailing-window climatology
python output/scripts/wind_timeseries.py        # daily/monthly wind series
python output/scripts/plot_wind_windows.py      # the window figures
python forecast_blend/fetch_forecasts.py        # archived past forecasts, six models
python forecast_blend/train_blend.py            # fit weights against ERA5
```

`train_blend.py` solves two constrained least-squares problems (SLSQP over the
probability simplex, so `w ≥ 0, Σw = 1`) — one on speeds, one on direction unit
vectors. The simplex constraint is what makes a weight readable as "how much to
trust this model". Needs ERA5 at `wind_data/ERA5hourly10m.grib` (gitignored, large).

### Route

All from the repository root:

```sh
python route/route.py --self-test           # sanity checks
python route/route.py route/input.json      # optimise against forecast/*.grb2 (pygrib)
python route/robustness.py --synthetic      # full synthetic run, no pygrib (~6 min)
python route/export_sample_route.py         # refresh frontend/data/route-sample.json
```

The **Update route** button on `route.html` calls a live optimiser at `/api/route`
that isn't deployed; served locally the page falls back to the stored route and says
so in a banner. See `route/CLAUDE.md` for the method and the course gotchas.

---

## Secrets and credentials

| Name | Where it lives | Needed for |
|---|---|---|
| `ANTHROPIC_API_KEY` | Env var locally; GitHub Actions secret in CI | The agent. The only required secret. |
| `COPERNICUSMARINE_CREDENTIALS` | GitHub Actions secret (contents of the local credentials file) | The two Copernicus map figures. Optional. |
| `MAPBOX_TOKEN` | `.env` locally; **Vercel** env var in prod | The route map. A public `pk.` token. |

Three rules worth internalising:

1. **Never put `ANTHROPIC_API_KEY` in Vercel.** The deploy is static and never runs
   the agent — the key belongs in Actions only.
2. **Never commit a Mapbox token.** GitHub push protection rejects it. It lives in
   `.env` (gitignored) and in Vercel; `scripts/write_mapbox_token.py` turns it into
   `frontend/assets/mapbox-token.js` locally, and `vercel.json`'s `buildCommand`
   does the same at deploy time. Both outputs are gitignored.
3. `credentials/` is gitignored wholesale. Copy the file's *contents* into the
   Actions secret rather than committing the file.

Start from `.env.example`.

---

## Automation

Two scheduled workflows, deliberately offset so they never push at the same time:

**`agent-refresh.yml` — 05:30 UTC daily.** Installs the runner and the libraries the
agent uses, recreates the Copernicus credentials from the secret if it's set, runs
`agent/run_agent.py`, and commits whatever changed under `output/figures/agent/` and
`output/results/agent/summary.json`. 45-minute timeout, one run at a time. Every
command the agent executes is echoed in the log, which makes failures easy to read.

**`daily-forecast.yml` — 11:30 UTC daily.** `route/fetch_forecast.py` pulls the newest
published NOAA GFS 0.25° cycle (10 m u/v over 51.5–53.5°N / 1.0–5.0°E, 13 forecast
hours, ~10 kB, no key — it walks back through cycles until one answers), then
`route/daily_forecast.py` re-optimises and rewrites `frontend/data/route-today.json`
and `output/figures/daily/forecast_route_{light,dark}.png`.

Both can be triggered by hand from **Actions → Run workflow**. Yesterday's outputs
are **replaced, not archived** — paths are fixed, so no page ever needs to know
today's date.

Each workflow's commit is what triggers the Vercel redeploy.

---

## Deployment

Vercel, static, from the repository root. `vercel.json` sets no framework, no install
step, and a one-line build command that writes the Mapbox token file; `/` redirects to
`/frontend/`. The only environment variable Vercel needs is `MAPBOX_TOKEN`.

---

## Gotchas

- **`output/figures/*` is gitignored with one exception** — `!output/figures/agent/`.
  Keep that negation, or the refresh workflow's commit step will silently miss the
  new PNGs and the site will quietly serve stale figures.
- **`.gitignore` lists `.agents/`, but the skills are already tracked.** Git ignores
  `.gitignore` for paths it already knows, so the existing skills are safe — but a
  **new** file under `.agents/` will not show up in `git status`. Add it with
  `git add -f`, or CI will run without it.
- **Missing Copernicus credentials are not an error.** The agent skips two figures and
  notes why. Don't debug a "broken" run that's actually just unauthenticated.
- **`tide.html` and `current.html` are dead but not deleted.** They still carry their
  own pre-restructure nav, so following a link inside them lands you in the old site
  layout. Delete them, or redirect them to `tidalcurrent.html`.
- **`waves.html` hard-codes a dated sample filename** —
  `sample_forecast_data/figures/wave_conditions_area_of_interest_2026-08-21T14_to_…png`.
  Everything else in the project uses fixed paths precisely so no page needs to know
  the date, so regenerating that figure on another day silently breaks the image
  unless you also edit the page. Worth converging on a stable filename.
- **Serve the repo root, not `frontend/`.** The pages reach up into `output/` and
  `route/` with relative paths.
- **`route/` is a subtree**, not a submodule — its history is interleaved into this
  repo's log, which makes `git log` noisier than you'd expect.

## Further reading

| Document | Covers |
|---|---|
| `agent/README.md` | The agent contract, its outputs, and the Actions setup step by step |
| `frontend/README.md` | Every network call the site makes, and the Vercel deploy |
| `forecast_blend/README.md` | The blending maths and an honest evaluation of what it buys |
| `route/README.md`, `route/CLAUDE.md` | The routing pipeline, method, and course facts |
| `weather_window_definition.md` | The window criterion in the domain expert's own words |
| `.agents/skills/*/SKILL.md` | How to pull and plot Copernicus data, and the stats figures |
