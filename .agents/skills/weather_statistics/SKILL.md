---
name: weather-statistics
description: Use this skill when asked to derive statistics from model or observed meteorological or ocean data, including wind roses, current velocity roses, wave roses, directional histograms, exceedance curves, speed/direction frequency tables, weather window analysis.
---

# Weather Statistics Skill

Use this skill for computing and visualising weather statistics from Delft3D-FM and SWAN
rasterized output, meteorological data (ERA5), or any otrher gridded/point dataset containing wind,
current, or wave data.

When this skill is used, begin your response with:

[Using weather-statistics skill]

## When to use

Trigger this skill for requests such as:

- "Make a wind rose for location X"
- "Analyze weather windows for variables X and Y"
- "Show current velocity rose for the bbox"
- "Plot directional histograms of wind speed"
- "Compute exceedance probability for current speed"
- "Summarise metocean statistics for a point / area"

## Before running any script

Always confirm the following with the user if not already provided:

1. **Data source** — ?
2. **Location** — a single lon/lat point, or spatially averaged over an area?
3. **Variable(s)** — wind (windx/windy), current (ucx/ucy), waves (Hs/Tp/dir)?
4. **Time period** — which months or date range?
5. **Directional convention** — meteorological (direction FROM, default for wind) or
   oceanographic (direction TO, default for currents)?

## Data loading

- Prefer rasterized monthly NetCDF files if available.
- Open with `xarray.open_mfdataset(..., combine="by_coords")` for multiple months and variables.
- Select the nearest grid point with `.sel(x=lon, y=lat, method="nearest")`.
- For spatial averages, use `.mean(dim=["x", "y"])` after selecting the bbox.
- Always reduce to a 1-D time series before computing statistics.

## Direction conventions

- **Wind (meteorological)**: direction the wind blows FROM.
  `dir = (np.degrees(np.arctan2(-u, -v)) + 360) % 360`
- **Current (oceanographic)**: direction the current flows TO.
  `dir = (np.degrees(np.arctan2(u, v)) + 360) % 360`
- **Waves**: direction the wave comes FROM.

## Python environment

Scripts in this skill use the **`metocean` pixi environment**, which includes `windrose`, `scipy`, and `cmocean` in addition to the base packages.

Run scripts with:
```bash
pixi run --environment metocean python output/scripts/my_script.py
```

## Preferred packages

- `numpy`, `xarray`, `pandas` for data handling
- `windrose` for rose diagrams
- `matplotlib` and `cmocean` for styling
- `scipy.stats` for exceedance / CDF calculations

## Examples

Always inspect the relevant example before writing new scripts:

| Task | Example script |
|------|---------------|
| Wind rose at a point | `examples/wind_rose.py` |
| Current velocity rose at a point | `examples/current_rose.py` |
| Directional speed histograms | `examples/directional_histogram.py` |
| Spatial map of a percentile (e.g. current/wind speed, wave height) | `examples/velocity_percentile_map.py` |
| Animated GIF of current/wind/wave maps over a day | `examples/hydro_wave_wind_animation.py` |

## Wave steepness 
Wave steepness is calculated as follows:

Steepness = Hs / (g * Tm01**2 / (2 * pi))

Where:
- `Hs` is the significant wave height
- `g` is the acceleration due to gravity
- `Tm01` is the mean wave period
- `pi` is the mathematical constant π

## Rose plots (wind / current / wave)

- Use example script `examples/wind_rose.py` or `examples/current_rose.py` as a starting point.
- Use `windrose.WindroseAxes.from_ax()` for rose diagrams.
- Always pass `calm_limit=CALM_THRESH` and set `bins[0] = CALM_THRESH` — windrose requires the first bin edge to equal the calm limit.
- Stack bars by speed class (e.g. 5 classes with equal quantile boundaries).
- North (0°) must be at the top of the polar plot: set `ax.set_theta_zero_location("N")`
  and `ax.set_theta_direction(-1)` for clockwise azimuth convention.
- Label cardinal directions (N, NE, E, SE, S, SW, W, NW) on the polar axis.
- Include a legend showing speed class ranges and units.
- Include a text annotation with calm percentage (speeds below a threshold).
- Use `ax.set_rlabel_position(112.5)` to avoid label overlap with bars.

## Directional histograms

- Use example script `examples/directional_histogram.py` as a starting point.
- Default directional bins: N (337.5–22.5°), NE, E, SE, S, SW, W, NW (8 sectors).
- Plot one subplot per directional bin, showing speed frequency distribution.
- Use consistent x-axis limits across all subpanels for easy comparison.
- Annotate each panel with the direction label and occurrence frequency (%).

## Spatial percentile maps

- When asked to make a **map plot of a percentile** of any variable (e.g. current
  speed, wind speed, wave height) — whether RMS, P95, P99, or any other statistic —
  use `examples/velocity_percentile_map.py` as the starting point. It works for both
  vector-magnitude variables (u/v components) and scalar variables.
- Colorbar convention: always set `vmin=0` and cap `vmax` at the **99th percentile of
  the values shown in the plot**, regardless of which percentile is being computed.

## Animated maps (GIF) of current / wind / wave conditions

- When asked to animate current, wind, and/or wave condition maps over a period
  (e.g. a day), use `examples/hydro_wave_wind_animation.py` as the starting point.
  It reproduces the 3-panel layout (current speed+direction, wind speed+direction,
  significant wave height+direction) from `example_script_from_user/plot_hydro_and_wave_data.ipynb`.
- One frame per hydro timestep (30-min); nearest hourly wave timestep per frame.
- Keep colour scales fixed across all frames (`vmin=0`, `vmax` = P99 over the whole
  animated period) to avoid flicker/rescaling between frames.
- Render frames to an in-memory PNG buffer and assemble with `PIL.Image.save(...,
  save_all=True, append_images=..., duration=<ms per frame>, loop=0)` — no extra
  `imageio` dependency needed since Pillow is already available.

## Output

- Save figures to `output/figures/`.
- Save frequency tables to `output/results/` as CSV.
