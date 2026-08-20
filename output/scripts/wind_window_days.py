"""Count days per month/year with a qualifying sailing wind window.

Criterion (per region, per calendar day):
    18 <= wind speed <= 30 kts, AND
    wind direction FROM in [205, 235] deg OR [305, 335] deg,
    sustained for at least 6 consecutive hours.

Data : ERA5-style hourly 10 m wind (u10/v10) GRIB, 0.25 deg grid.
Areas: geometry/50_75_100.geojson (three nested corridor polygons).

Spatial aggregation
-------------------
The criterion is a threshold test, so *how* the region is collapsed to a decision
changes the answer, and only per-cell rules respect the fact that the polygons
are nested (50% inside 75% inside 100%). Four definitions are computed:

  A  region_mean  region-averaged wind vector, then test.  NOT monotone under
                  nesting - the mean over 6 cells is a different quantity than
                  the mean over 8, so a subset region can score higher. Kept for
                  reference only; do not use it to compare the three corridors.
  B  any_cell     each hour, at least one cell qualifies. The qualifying cell may
                  differ from hour to hour, so the window can drift.
  C  all_cells    each hour, every cell qualifies simultaneously.  <-- PRIMARY
                  Uniform conditions corridor-wide. Wider corridor = fewer days.
  D  cell_sust    some single cell holds its own >=6 h run within the day.

PRIMARY is C: a day counts only if the whole corridor meets the criterion at
once, for 6 consecutive hours.
"""

import json
import warnings

import numpy as np
import pandas as pd
import xarray as xr
from shapely.geometry import Point, shape
from shapely.prepared import prep

warnings.filterwarnings("ignore")

GRIB = "wind_data/ERA5hourly10m.grib"
GEOJSON = "geometry/50_75_100.geojson"
OUTDIR = "output/results"

SPEED_MIN_KT, SPEED_MAX_KT = 18.0, 30.0
SECTORS = [(205.0, 235.0), (305.0, 335.0)]
MIN_HOURS = 6
MS_TO_KT = 1.0 / 0.514444

PRIMARY = "days_all_cells_6h"


def qualifies(u, v):
    """Hourly boolean mask; u, v may be any shape."""
    speed_kt = np.hypot(u, v) * MS_TO_KT
    direction = (np.degrees(np.arctan2(-u, -v)) + 360.0) % 360.0  # meteorological, FROM
    in_dir = np.zeros(direction.shape, dtype=bool)
    for lo, hi in SECTORS:
        in_dir |= (direction >= lo) & (direction <= hi)
    return (speed_kt >= SPEED_MIN_KT) & (speed_kt <= SPEED_MAX_KT) & in_dir


def to_day_grid(mask, n_days):
    """Reshape a continuous hourly mask to (n_days, 24), zero-padding the tail."""
    padded = np.zeros(n_days * 24, dtype=bool)
    padded[: len(mask)] = mask
    return padded.reshape(n_days, 24)


def max_run_per_day(grid):
    """Longest run of consecutive True in each row, vectorised over days."""
    run = np.zeros(grid.shape, dtype=np.int16)
    run[:, 0] = grid[:, 0]
    for k in range(1, grid.shape[1]):
        run[:, k] = (run[:, k - 1] + 1) * grid[:, k]
    return run.max(axis=1)


# --- regions -----------------------------------------------------------------
with open(GEOJSON) as f:
    gj = json.load(f)

polys = [shape(feat["geometry"]) for feat in gj["features"]]
widths = np.array([p.bounds[2] - p.bounds[0] for p in polys])
# nested corridors: label each by its width as a fraction of the widest one
labels = [f"{round(w / widths.max() * 100):d}%" for w in widths]

# --- data --------------------------------------------------------------------
ds = xr.open_dataset(
    GRIB, engine="cfgrib", backend_kwargs={"indexpath": ""}, chunks={"time": 4000}
)

lon2d, lat2d = np.meshgrid(ds.longitude.values, ds.latitude.values)
cell_sets = []
for label, poly in zip(labels, polys):
    pp = prep(poly)
    inside = np.array([pp.intersects(Point(x, y)) for x, y in zip(lon2d.ravel(), lat2d.ravel())])
    iy, ix = np.unravel_index(np.where(inside)[0], lon2d.shape)
    cell_sets.append((label, poly, iy, ix))

# load every cell any region needs, once
all_iy = np.concatenate([c[2] for c in cell_sets])
all_ix = np.concatenate([c[3] for c in cell_sets])
keys = sorted({(a, b) for a, b in zip(all_iy.tolist(), all_ix.tolist())})
key_pos = {k: i for i, k in enumerate(keys)}
sel_iy = np.array([k[0] for k in keys])
sel_ix = np.array([k[1] for k in keys])

pick = ds[["u10", "v10"]].isel(
    latitude=xr.DataArray(sel_iy, dims="cell"), longitude=xr.DataArray(sel_ix, dims="cell")
)
U = pick.u10.compute().values.astype("float64")  # (time, cell)
V = pick.v10.compute().values.astype("float64")
OK_CELL = qualifies(U, V)  # per-cell hourly mask

times = pd.DatetimeIndex(ds.time.values)
days = pd.DatetimeIndex(np.unique(times.normalize()))
n_days = len(days)
hours_per_day = np.bincount(
    np.searchsorted(days, times.normalize()), minlength=n_days
)

records = []
daily_records = []
meta = []

for label, poly, iy, ix in cell_sets:
    cols = np.array([key_pos[(a, b)] for a, b in zip(iy.tolist(), ix.tolist())])
    ok = OK_CELL[:, cols]  # (time, n_cells_in_region)
    meta.append((label, poly.bounds, len(cols),
                 np.unique(ds.latitude.values[iy]), np.unique(ds.longitude.values[ix])))

    # A - region-averaged wind vector (reference only; not nesting-safe)
    mean_ok = qualifies(U[:, cols].mean(axis=1), V[:, cols].mean(axis=1))

    masks = {
        "days_all_cells_6h": ok.all(axis=1),   # C, primary
        "days_any_cell_6h": ok.any(axis=1),    # B
        "days_region_mean_6h": mean_ok,        # A
    }
    runs = {k: max_run_per_day(to_day_grid(m, n_days)) for k, m in masks.items()}

    # D - some single cell sustains its own >=6 h run inside the day
    cell_sustained = np.zeros(n_days, dtype=bool)
    for j in range(ok.shape[1]):
        cell_sustained |= max_run_per_day(to_day_grid(ok[:, j], n_days)) >= MIN_HOURS

    primary_grid = to_day_grid(masks["days_all_cells_6h"], n_days)
    daily = pd.DataFrame(
        {
            "days_all_cells_6h": runs["days_all_cells_6h"] >= MIN_HOURS,
            "days_all_cells_6h_cumulative": primary_grid.sum(axis=1) >= MIN_HOURS,
            "days_any_cell_6h": runs["days_any_cell_6h"] >= MIN_HOURS,
            "days_cell_sustained_6h": cell_sustained,
            "days_region_mean_6h": runs["days_region_mean_6h"] >= MIN_HOURS,
            "qualifying_hours_all_cells": primary_grid.sum(axis=1),
            "hours_with_data": hours_per_day,
        },
        index=days,
    )

    # per-day export: met flag plus whether the day sits in a run of >=2 met days
    met = daily["days_all_cells_6h"].to_numpy()
    prev_met = np.concatenate(([False], met[:-1]))
    next_met = np.concatenate((met[1:], [False]))
    daily_records.append(pd.DataFrame({
        "region": label,
        "date": days,
        "met": met.astype(int),
        "back_to_back": (met & (prev_met | next_met)).astype(int),
        "max_run_hours": runs["days_all_cells_6h"],
        "qualifying_hours": primary_grid.sum(axis=1),
        "hours_with_data": hours_per_day,
    }))

    g = daily.groupby([daily.index.year, daily.index.month])
    out = g.agg(
        days_all_cells_6h=("days_all_cells_6h", "sum"),
        days_all_cells_6h_cumulative=("days_all_cells_6h_cumulative", "sum"),
        days_any_cell_6h=("days_any_cell_6h", "sum"),
        days_cell_sustained_6h=("days_cell_sustained_6h", "sum"),
        days_region_mean_6h=("days_region_mean_6h", "sum"),
        qualifying_hours_all_cells=("qualifying_hours_all_cells", "sum"),
    ).astype(int)
    out["days_in_month_with_data"] = g.size()
    out.index.names = ["year", "month"]
    out = out.reset_index()
    out.insert(0, "region", label)
    records.append(out)

result = pd.concat(records, ignore_index=True)
result.to_csv(f"{OUTDIR}/wind_window_days_by_month.csv", index=False)

daily_all = pd.concat(daily_records, ignore_index=True)
daily_all.to_csv(f"{OUTDIR}/wind_window_days_daily.csv", index=False)

# wide pivot: one table per region, years x months, primary definition
with open(f"{OUTDIR}/wind_window_days_pivot.txt", "w") as f:
    f.write("Days with >=6 consecutive hours of 18-30 kt from 205-235 deg or 305-335 deg,\n"
            "with EVERY grid cell in the corridor meeting the criterion simultaneously.\n")
    for label in labels:
        sub = result[result.region == label]
        piv = sub.pivot(index="year", columns="month", values=PRIMARY)
        piv.columns = [pd.Timestamp(2000, m, 1).strftime("%b") for m in piv.columns]
        f.write(f"\n=== Region {label} corridor ===\n")
        f.write(piv.to_string())
        f.write("\n")

# monthly climatology over full years only
full_years = [y for y in result.year.unique() if y != 2026]
clim = (
    result[result.year.isin(full_years)]
    .groupby(["region", "month"])[PRIMARY]
    .mean()
    .round(2)
    .reset_index()
    .rename(columns={PRIMARY: "mean_days_per_month"})
)
clim.to_csv(f"{OUTDIR}/wind_window_climatology.csv", index=False)

# --- report ------------------------------------------------------------------
print("Regions (cell-centre selection):")
for label, bounds, n, lats, lons in meta:
    print(f"  {label:>4}  lon {bounds[0]:.3f}-{bounds[2]:.3f}  lat {bounds[1]:.3f}-{bounds[3]:.3f}"
          f"  -> {n} grid cells; lat={lats}, lon={lons[0]}..{lons[-1]}")

print(f"\nPeriod: {times[0]} .. {times[-1]}  ({len(times)} hourly steps, {n_days} days)")

totals = result.groupby("region")[
    ["days_all_cells_6h", "days_any_cell_6h", "days_cell_sustained_6h", "days_region_mean_6h"]
].sum().reindex(labels)
print("\nTotals over full record, by spatial definition:")
print(totals.to_string())

print("\nNesting check (50% subset of 75% subset of 100%):")
for col in totals.columns:
    v = totals[col].tolist()
    if v[0] <= v[1] <= v[2]:
        verdict = "OK - monotone (wider corridor = fewer days)"
    elif v[0] >= v[1] >= v[2]:
        verdict = "OK - monotone (wider corridor = more days)"
    else:
        verdict = "NOT MONOTONE - not nesting-safe"
    print(f"  {col:<26} {v}  {verdict}")

with open(f"{OUTDIR}/wind_window_days_pivot.txt") as f:
    print("\n" + f.read())

print("Monthly climatology (mean days/month, 2021-2025 full years):")
print(
    clim.pivot(index="month", columns="region", values="mean_days_per_month")
    .reindex(columns=labels)
    .to_string()
)
