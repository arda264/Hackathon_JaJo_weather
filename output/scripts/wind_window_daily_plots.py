"""Per-day 0/1 charts of the sailing wind window, one subplot per month.

Same criterion and the same spatial definitions as ``wind_window_days.py``:
    18 <= wind speed <= 30 kts, AND
    wind direction FROM in [205, 235] deg OR [305, 335] deg,
    sustained for at least 6 consecutive hours,
with the primary definition requiring EVERY grid cell in the corridor to meet
the criterion simultaneously (definition C, ``all_cells``).

``wind_window_days.py`` keeps only monthly totals, so the daily flags behind
them are recomputed here, written to CSV, and drawn as a small-multiple grid:
one figure per region and year, twelve month subplots, one bar per day
(1 = window, 0 = no window).

Run from the repository root:
    python output/scripts/wind_window_daily_plots.py
"""

import argparse
import calendar
import json
import warnings
from pathlib import Path

import matplotlib
import numpy as np
import pandas as pd
import xarray as xr
from shapely.geometry import Point, shape
from shapely.prepared import prep

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

warnings.filterwarnings("ignore")

GRIB = "wind_data/ERA5hourly10m.grib"
GEOJSON = "geometry/50_75_100.geojson"
OUTDIR = "output/results"
FIGDIR = "output/figures/daily_windows"

SPEED_MIN_KT, SPEED_MAX_KT = 18.0, 30.0
SECTORS = [(205.0, 235.0), (305.0, 335.0)]
MIN_HOURS = 6
MS_TO_KT = 1.0 / 0.514444

PRIMARY = "all_cells_6h"

# how each daily flag is described in the figure subtitle
CRITERIA = {
    "all_cells_6h": "≥6 consecutive hours, every cell in the corridor at once",
    "all_cells_6h_cumulative": "≥6 hours (not necessarily consecutive), every cell at once",
    "any_cell_6h": "≥6 consecutive hours with at least one cell qualifying",
    "cell_sustained_6h": "≥6 consecutive hours sustained by some single cell",
    "region_mean_6h": "≥6 consecutive hours on the region-averaged wind vector",
}

# --- chart tokens (references/palette.md) ------------------------------------
SURFACE = "#fcfcfb"
INK_PRIMARY = "#0b0b0b"
INK_SECONDARY = "#52514e"
INK_MUTED = "#898781"
GRIDLINE = "#e1e0d9"
BASELINE = "#c3c2b7"
SERIES = "#2a78d6"  # the one data series: "window met"

plt.rcParams.update(
    {
        "font.family": "sans-serif",
        "font.sans-serif": ["Segoe UI", "DejaVu Sans", "sans-serif"],
        "figure.facecolor": SURFACE,
        "axes.facecolor": SURFACE,
        "savefig.facecolor": SURFACE,
    }
)


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


def daily_flags(grib: str, geojson: str) -> pd.DataFrame:
    """Per-day flags for every region and every spatial definition."""
    with open(geojson) as f:
        gj = json.load(f)

    polys = [shape(feat["geometry"]) for feat in gj["features"]]
    widths = np.array([p.bounds[2] - p.bounds[0] for p in polys])
    # nested corridors: label each by its width as a fraction of the widest one
    labels = [f"{round(w / widths.max() * 100):d}%" for w in widths]

    ds = xr.open_dataset(
        grib, engine="cfgrib", backend_kwargs={"indexpath": ""}, chunks={"time": 4000}
    )
    lon2d, lat2d = np.meshgrid(ds.longitude.values, ds.latitude.values)

    cell_sets = []
    for label, poly in zip(labels, polys):
        pp = prep(poly)
        inside = np.array(
            [pp.intersects(Point(x, y)) for x, y in zip(lon2d.ravel(), lat2d.ravel())]
        )
        iy, ix = np.unravel_index(np.where(inside)[0], lon2d.shape)
        cell_sets.append((label, iy, ix))

    # load every cell any region needs, once
    all_iy = np.concatenate([c[1] for c in cell_sets])
    all_ix = np.concatenate([c[2] for c in cell_sets])
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
    hours_per_day = np.bincount(np.searchsorted(days, times.normalize()), minlength=n_days)

    frames = []
    for label, iy, ix in cell_sets:
        cols = np.array([key_pos[(a, b)] for a, b in zip(iy.tolist(), ix.tolist())])
        ok = OK_CELL[:, cols]  # (time, n_cells_in_region)

        # A - region-averaged wind vector (reference only; not nesting-safe)
        mean_ok = qualifies(U[:, cols].mean(axis=1), V[:, cols].mean(axis=1))

        masks = {
            "all_cells_6h": ok.all(axis=1),   # C, primary
            "any_cell_6h": ok.any(axis=1),    # B
            "region_mean_6h": mean_ok,        # A
        }
        runs = {k: max_run_per_day(to_day_grid(m, n_days)) for k, m in masks.items()}

        # D - some single cell sustains its own >=6 h run inside the day
        cell_sustained = np.zeros(n_days, dtype=bool)
        for j in range(ok.shape[1]):
            cell_sustained |= max_run_per_day(to_day_grid(ok[:, j], n_days)) >= MIN_HOURS

        primary_grid = to_day_grid(masks["all_cells_6h"], n_days)
        daily = pd.DataFrame(
            {
                "all_cells_6h": (runs["all_cells_6h"] >= MIN_HOURS).astype(int),
                "all_cells_6h_cumulative": (primary_grid.sum(axis=1) >= MIN_HOURS).astype(int),
                "any_cell_6h": (runs["any_cell_6h"] >= MIN_HOURS).astype(int),
                "cell_sustained_6h": cell_sustained.astype(int),
                "region_mean_6h": (runs["region_mean_6h"] >= MIN_HOURS).astype(int),
                "qualifying_hours_all_cells": primary_grid.sum(axis=1),
                "hours_with_data": hours_per_day,
            },
            index=days,
        )
        daily.index.name = "date"
        daily = daily.reset_index()
        daily.insert(0, "region", label)
        frames.append(daily)

    return pd.concat(frames, ignore_index=True)


def plot_year(daily: pd.DataFrame, region: str, year: int, flag: str, path: Path) -> None:
    """One figure: 12 month subplots, one 0/1 bar per day."""
    sub = daily[(daily.region == region) & (daily.year == year)]

    fig, axes = plt.subplots(3, 4, figsize=(15.5, 6.2), sharey=True)
    fig.subplots_adjust(left=0.045, right=0.99, top=0.815, bottom=0.095, hspace=0.62, wspace=0.09)

    for month, ax in enumerate(axes.ravel(), start=1):
        ndays = calendar.monthrange(year, month)[1]
        m = sub[sub.month == month].set_index("day").reindex(range(1, ndays + 1))
        vals = m[flag]
        has_data = vals.notna()
        met = has_data & (vals == 1)
        days = np.arange(1, ndays + 1)

        if not has_data.any():
            # nothing measured: drop the axes entirely rather than draw an empty frame
            ax.set_axis_off()
            ax.set_title(
                f"{calendar.month_abbr[month]}   no data",
                fontsize=10,
                color=INK_MUTED,
                loc="left",
                pad=6,
            )
            continue

        # every evaluated day gets a recessive baseline tick, so "0" reads as
        # "measured, condition not met" rather than "no data"
        ax.bar(
            days[has_data.to_numpy()],
            np.full(has_data.sum(), 0.045),
            width=0.72,
            color=BASELINE,
            linewidth=0,
        )
        ax.bar(days[met.to_numpy()], np.ones(met.sum()), width=0.72, color=SERIES, linewidth=0)

        ax.axhline(1.0, color=GRIDLINE, linewidth=0.8, zorder=0)
        ax.set_ylim(0, 1.18)
        ax.set_xlim(0.3, ndays + 0.7)
        ax.set_yticks([0, 1])
        ax.set_yticklabels(["0", "1"], fontsize=8, color=INK_MUTED)
        ticks = [d for d in (1, 5, 10, 15, 20, 25, 30) if d <= ndays]
        ax.set_xticks(ticks)
        ax.set_xticklabels([str(t) for t in ticks], fontsize=8, color=INK_MUTED)
        ax.tick_params(length=0, pad=2)
        for side in ("top", "right", "left"):
            ax.spines[side].set_visible(False)
        ax.spines["bottom"].set_color(BASELINE)
        ax.spines["bottom"].set_linewidth(0.8)
        # a partial month stops the axis where the record stops
        ax.spines["bottom"].set_bounds(0.5, int(days[has_data.to_numpy()].max()) + 0.5)

        n = int(met.sum())
        ax.set_title(
            calendar.month_abbr[month],
            fontsize=10.5,
            color=INK_PRIMARY,
            loc="left",
            pad=6,
            weight="bold",
        )
        ax.text(
            1.0,
            1.055,
            f"{n} {'day' if n == 1 else 'days'}",
            transform=ax.transAxes,
            ha="right",
            va="bottom",
            fontsize=9,
            color=INK_SECONDARY,
        )

    total = int(sub[flag].sum())
    fig.suptitle(
        f"Sailing wind window by day — {region} corridor, {year}",
        x=0.045,
        y=0.955,
        ha="left",
        fontsize=15,
        color=INK_PRIMARY,
        weight="bold",
    )
    fig.text(
        0.045,
        0.888,
        f"1 = window met, 0 = not met.  Criterion: 18–30 kt from 205–235° or 305–335°, "
        f"{CRITERIA[flag]}.  {total} qualifying days this year.",
        ha="left",
        va="center",
        fontsize=10,
        color=INK_SECONDARY,
    )
    # binary legend: the bar height is the primary encoding, colour is redundant
    fig.text(0.045, 0.030, "■", fontsize=11, color=SERIES, ha="left", va="center")
    fig.text(0.058, 0.030, "window met (1)", fontsize=9, color=INK_SECONDARY, va="center")
    fig.text(0.155, 0.030, "■", fontsize=11, color=BASELINE, ha="left", va="center")
    fig.text(0.168, 0.030, "not met (0)", fontsize=9, color=INK_SECONDARY, va="center")

    fig.savefig(path, dpi=150)
    plt.close(fig)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--grib", default=GRIB)
    ap.add_argument("--geojson", default=GEOJSON)
    ap.add_argument("--outdir", default=OUTDIR)
    ap.add_argument("--figdir", default=FIGDIR)
    ap.add_argument(
        "--daily-csv",
        default=None,
        help="skip the GRIB and plot from an existing daily CSV",
    )
    ap.add_argument(
        "--flag",
        default=PRIMARY,
        choices=list(CRITERIA),
        help=f"which spatial definition to plot (default: {PRIMARY})",
    )
    args = ap.parse_args()

    outdir, figdir = Path(args.outdir), Path(args.figdir)
    figdir.mkdir(parents=True, exist_ok=True)

    if args.daily_csv:
        daily = pd.read_csv(args.daily_csv, parse_dates=["date"])
    else:
        daily = daily_flags(args.grib, args.geojson)
        outdir.mkdir(parents=True, exist_ok=True)
        # its own file: wind_window_days.py owns wind_window_days_daily.csv and
        # writes a different set of columns, which plot_wind_calendar.py reads
        csv_path = outdir / "wind_window_daily_flags.csv"
        daily.to_csv(csv_path, index=False)
        print(f"wrote {csv_path}  ({len(daily)} region-days)")

    daily["year"] = daily["date"].dt.year
    daily["month"] = daily["date"].dt.month
    daily["day"] = daily["date"].dt.day

    regions = list(dict.fromkeys(daily.region))
    for region in regions:
        slug = region.replace("%", "pct")
        for year in sorted(daily.loc[daily.region == region, "year"].unique()):
            suffix = "" if args.flag == PRIMARY else f"_{args.flag}"
            path = figdir / f"daily_window_{slug}_{year}{suffix}.png"
            plot_year(daily, region, int(year), args.flag, path)
            print(f"wrote {path}")

    print(f"\n{len(regions)} regions x years -> {figdir}")


if __name__ == "__main__":
    main()
