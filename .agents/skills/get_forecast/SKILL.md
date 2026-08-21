---
name: get-forecast
description: Use this skill when asked to download, fetch, or update a forecast (wave, wind, or current) from Copernicus Marine Service for the North Sea Record area, e.g. "download the current wave forecast", "get the latest forecast", "update the forecast data", or "plot the wave forecast".
---

# Get Forecast Skill

Use this skill for downloading near-real-time forecast data from the
Copernicus Marine Service and (optionally) producing a quick-look plot of it.

When this skill is used, begin your response with:

[Using get-forecast skill]

## When to use

Trigger this skill for requests such as:

- "Download the current wave forecast"
- "Get the latest wind/wave forecast for the crossing area"
- "Update the forecast data"
- "Plot the wave forecast" (first, ensure a fresh forecast has been downloaded)

## Python environment

Forecast downloads require the **`copernicus` pixi environment** (Python 3.13,
`copernicusmarine` + `h5py`). Plotting uses the **`metocean` pixi environment**
(`xarray`, `matplotlib`, `windrose`, `scipy`, `cmocean`).

```bash
pixi run -e copernicus python <script>.py   # downloading
pixi run -e metocean python <script>.py     # plotting
```

## Credentials

Copernicus Marine credentials are stored at `credentials/.copernicusmarine-credentials`
(base64-encoded ini file, **do not commit this file** — it is gitignored).
Pass the path directly via the `credentials_file` argument of
`copernicusmarine.subset()`/`copernicusmarine.open_dataset()` — the client decodes
the base64 file itself, so there is **no need to manually decode it**:

```python
copernicusmarine.subset(
    ...,
    credentials_file="credentials/.copernicusmarine-credentials",
)
```

If the credentials file does not exist yet, prompt the user for their
Copernicus Marine username and password (use `getpass.getpass` for the
password so it isn't echoed), then create the file with
`copernicusmarine.login`:

```python
copernicusmarine.login(
    username=username,
    password=password,
    credentials_file=credentials_file,
    force_overwrite=True,
)
```

See `ensure_credentials()` in `examples/get_current_wave_forecast.py` for the
full pattern: check-if-exists -> prompt -> `login()` -> return the path to use
for the actual `subset()`/`open_dataset()` call.

## Downloading a forecast

- Use `examples/get_current_wave_forecast.py` as the starting point for any new
  download script (wave, wind, or current). It shows the pattern of:
  - Using `datetime.now()` as `start_datetime` and `start_datetime + timedelta(days=N)`
    as `end_datetime`, so the request always reflects the *current* forecast
    rather than hardcoded dates.
  - Passing `credentials_file` instead of `username`/`password`.
  - Writing to `output/results/` with a filename that embeds the download
    timestamp, e.g. `wave_forecast_<YYYYmmddTHHMMSS>.nc`.
- Bounding box for the North Sea Record crossing area (Lowestoft \u2192 IJmuiden):
  - `minimum_longitude=1.6701955318171018`
  - `maximum_longitude=4.713201098204792`
  - `minimum_latitude=52.2187035064974`
  - `maximum_latitude=52.99847368288424`
- Wave forecast dataset: `cmems_mod_nws_wav_anfc_1.5km_PT1H-i`, variables
  `VMDR_SW1, VTM01_SW1, VHM0_SW1, VHM0_WW, VTM01_WW, VMDR_WW` (swell and
  wind-sea height/period/mean-direction-from).
- Tidal/ocean currents forecast: use `examples/get_current_currents_forecast.py`
  as the starting point. Dataset `cmems_mod_nws_phy-cur_anfc_1.5km-2D_PT1H-i`
  ("hourly-instantaneous horizontal velocity (2D)"), variables `uo, vo`
  (eastward/northward current velocity components). This dataset is **2D
  depth-averaged (no depth dimension)** and hourly (144 timesteps for a
  6-day forecast) at 1.5 km resolution — do **not** pass `minimum_depth`/
  `maximum_depth`. Output filenames follow the same pattern, e.g.
  `currents_forecast_<YYYYmmddTHHMMSS>.nc`.
- For wind forecasts, ask the user for the relevant dataset ID and variable
  names if not already known/available in the workspace, but reuse the same
  bounding box and the "download from now" pattern.
- Default forecast horizon is 6 days ahead; expose it as a `--forecast-days`
  CLI argument.

## Plotting a downloaded forecast

- Use `examples/plot_wave_forecast_multipanel.py` as the starting point for
  quick-look plots of downloaded wave forecasts. It:
  - Auto-discovers the most recently downloaded `wave_forecast_*.nc` file in
    `output/results/` (or accepts `--input-file`).
  - Plots the first timestep as a 2x2 grid: wind-sea height+direction (top
    left), wind-sea period (bottom left), swell height+direction (top right),
    swell period (bottom right).
  - Draws direction arrows (subsampled every 5 grid points) from the
    `VMDR_*` "direction from" fields, converted to propagation vectors via
    `u = -sin(theta), v = -cos(theta)`.
  - Uses **shared colorbar limits** across the two height panels, and
    separately across the two period panels, so left/right columns are
    directly comparable.
  - Corrects the map aspect ratio for latitude with
    `ax.set_aspect(1 / cos(radians(mean_latitude)))`.
  - Saves to `output/figures/` with the plotted timestep embedded in the
    filename, e.g. `wave_forecast_multipanel_<YYYYmmddTHHMMSS>.png`.
- Use `examples/plot_currents.py` as the starting point for
  quick-look plots of downloaded currents forecasts. It:
  - Auto-discovers the most recently downloaded `currents_forecast_*.nc` file
    in `output/results/` (or accepts `--input-file`).
  - Plots the first timestep (no depth selection needed — the dataset is 2D
    depth-averaged).
  - Plots current speed (`sqrt(uo**2 + vo**2)`) as a colormap, with quiver
    arrows drawn directly from `uo`/`vo` (these are true velocity
    components, so **no from/to direction conversion is needed**, unlike the
    wave `VMDR_*` fields).
  - Tune the quiver `scale` argument to the typical current speed magnitude
    for this dataset (tidal currents here reach ~0.1-1.1 m/s, noticeably
    higher than the older daily-mean 7 km dataset) so arrows are visible —
    a `scale` tuned for a different speed range will make arrows disappear
    or overlap into an unreadable mess.
  - Saves to `output/figures/currents_<YYYYmmddTHHMMSS>.png`.
- Use `examples/animate_currents.py` as the starting point for
  animating the full downloaded forecast period (e.g. "animate the currents
  forecast for the full week"). It:
  - Since the dataset is hourly (144 timesteps over 6 days), by default
    renders **every hourly timestep** (`--hour-step 1`); increase
    `--hour-step` to reduce render time/frame count if a coarser animation
    is acceptable.
  - Each frame has a map panel (top) plus a timeseries subplot (bottom)
    showing current speed at the centre grid point of the domain for the
    full forecast period, with a moving red dot marking the current
    timestep — makes the tidal cycle easy to see alongside the spatial
    pattern.
  - Uses a **fixed colour scale** (`vmin=0`, `vmax` = P99 of speed over the
    *whole* period, computed once up front) so the scale doesn't
    flicker/rescale between frames.
  - Renders each frame to an in-memory PNG buffer and assembles them with
    `PIL.Image.save(..., save_all=True, append_images=..., duration=<ms per
    frame>, loop=0)` — no extra `imageio` dependency needed since Pillow is
    already available.
  - Saves to `output/figures/currents_animation_<first_timestamp>_to_<last_timestamp>.gif`.

## Output

- Save downloaded NetCDF files to `output/results/`.
- Save figures to `output/figures/`.
