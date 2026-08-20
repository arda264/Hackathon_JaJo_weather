"""Over-time series of wind speed and wind direction against the sailing criterion.

Same criterion and the same regions as ``wind_window_days.py``:
    18 <= wind speed <= 30 kts, AND
    wind direction FROM in [205, 235] deg OR [305, 335] deg,
    sustained for at least 6 consecutive hours,
with the primary definition requiring EVERY grid cell in the corridor to meet the
criterion simultaneously (definition C, ``all_cells``), evaluated for the three
nested corridors of geometry/50_75_100.geojson (50% inside 75% inside 100%).

``wind_window_days.py`` reduces the record to a per-day yes/no. This script keeps
the two underlying quantities and plots them along the calendar, so the criterion
bands can be read as *bands* rather than as a flag:

  1. wind_speed_timeseries      daily corridor wind speed vs the 18-30 kt band
  2. wind_direction_timeseries  daily corridor wind direction vs the two sectors
  3. wind_condition_share       monthly share of hours meeting speed / direction /
                                both, corridor-wide - which half of the criterion
                                is the binding one, and when

Each figure is one panel per corridor (a small-multiple, so the nested corridors
are never mixed on one set of marks) and is rendered in a light and a dark variant.

Spatial reduction
    Speed and direction are plotted from the corridor-mean wind *vector* (mean u,
    mean v over the corridor's grid cells, then converted), which is the quantity a
    single "what was the wind doing" trace should show. The shaded criterion bands
    and the qualifying-day marks come from the strict all-cells test, unchanged
    from wind_window_days.py, so the marks stay comparable with the other figures.

Run from the repository root:
    python output/scripts/wind_timeseries.py
"""

import argparse
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

import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402

warnings.filterwarnings("ignore")

GRIB = "wind_data/ERA5hourly10m.grib"
GEOJSON = "geometry/50_75_100.geojson"
OUTDIR = "output/results"
FIGDIR = "output/figures"

SPEED_MIN_KT, SPEED_MAX_KT = 18.0, 30.0
SECTORS = [(205.0, 235.0), (305.0, 335.0)]
MIN_HOURS = 6
MS_TO_KT = 1.0 / 0.514444

REGIONS = ["100%", "75%", "50%"]
DPI = 200
SCALE = DPI / 96.0  # CSS px -> device px, so the 2px/4px specs hold visually

CRITERION = (f"{SPEED_MIN_KT:.0f}–{SPEED_MAX_KT:.0f} kt from 205–235° or "
             f"305–335°, ≥{MIN_HOURS} consecutive hours, every cell at once")
SOURCE = ("ERA5 hourly 10 m wind (u10/v10), 0.25° grid at 52.5°N · corridor-mean "
          "wind vector · 2021-01-01 to 2026-08-14")

# --- design tokens (dataviz references/palette.md; validated with
#     scripts/validate_palette.js --ordinal and --pairs all in both modes) ------
THEMES = {
    "light": dict(
        surface="#fcfcfb", plane="#f9f9f7", primary="#0b0b0b", secondary="#52514e",
        muted="#898781", grid="#e1e0d9", axis="#c3c2b7",
        ordinal=["#86b6ef", "#2a78d6", "#104281"],          # 100%, 75%, 50%
        cat=["#2a78d6", "#eb6834", "#1baf7a"],              # speed, direction, both
        band="#ecebe4", faint="#d7d6cd", trace_alpha=0.32,
    ),
    "dark": dict(
        surface="#1a1a19", plane="#0d0d0d", primary="#ffffff", secondary="#c3c2b7",
        muted="#898781", grid="#2c2c2a", axis="#383835",
        ordinal=["#9ec5f4", "#3987e5", "#184f95"],
        cat=["#3987e5", "#d95926", "#199e70"],
        # the deepest ordinal step needs more of itself to clear the dark surface
        band="#272725", faint="#3d3d3a", trace_alpha=0.5,
    ),
}


def style(t):
    plt.rcParams.update({
        "font.family": "sans-serif",
        "font.sans-serif": ["Segoe UI", "DejaVu Sans", "Arial"],
        "figure.facecolor": t["surface"],
        "axes.facecolor": t["surface"],
        "savefig.facecolor": t["surface"],
        "text.color": t["primary"],
        "axes.labelcolor": t["secondary"],
        "xtick.color": t["muted"],
        "ytick.color": t["muted"],
        "axes.edgecolor": t["axis"],
        "axes.linewidth": 1.0 * SCALE,
        "xtick.major.size": 0,
        "ytick.major.size": 0,
    })


def from_top(fig, inches):
    """Figure-fraction y for a distance measured in inches from the top edge."""
    return 1.0 - inches / fig.get_figheight()


def titles(fig, t, title, subtitle):
    fig.text(0.012, from_top(fig, 0.30), title, ha="left", va="center",
             fontsize=15, fontweight="600", color=t["primary"])
    fig.text(0.012, from_top(fig, 0.62), subtitle, ha="left", va="center",
             fontsize=9.5, color=t["secondary"])


def footer(fig, t, extra=""):
    fig.text(0.012, 0.14 / fig.get_figheight(), SOURCE + extra, ha="left", va="center",
             fontsize=7.5, color=t["muted"])


def note(fig, t, text):
    """Mark key, one line under the subtitle - never inside the plotting area."""
    fig.text(0.012, from_top(fig, 0.92), text, ha="left", va="center",
             fontsize=8.5, color=t["muted"])


def legend_row(fig, t, labels, colors, y_in=0.92):
    """Swatch + label key; text stays in ink tokens, never the series colour."""
    y, x = from_top(fig, y_in), 0.012
    h = 0.018 * 5.6 / fig.get_figheight()
    for label, color in zip(labels, colors):
        fig.patches.append(plt.Rectangle((x, y - h / 2), 0.010, h, transform=fig.transFigure,
                                         facecolor=color, edgecolor="none", zorder=5))
        fig.text(x + 0.015, y, label, fontsize=8.5, color=t["secondary"], va="center")
        x += 0.015 + 0.0062 * len(label) + 0.022


def edge_label(ax, t, y, text, swatch=None):
    """Label just outside the right spine, in the figure's right margin.

    An optional swatch carries series identity; the text itself stays in ink
    tokens so identity is never colour-alone.
    """
    x = 1.006
    if swatch:
        ax.plot([x + 0.003], [y], marker="s", markersize=6, color=swatch,
                transform=ax.get_yaxis_transform(), clip_on=False, zorder=5)
        x += 0.011
    ax.text(x, y, text, transform=ax.get_yaxis_transform(), fontsize=8.5,
            color=t["secondary"], va="center", ha="left", clip_on=False)


def stack_labels(values, min_gap):
    """Nudge label positions apart so right-edge labels never overlap."""
    y = np.array(values, dtype=float)
    order = np.argsort(y)
    for prev, cur in zip(order, order[1:]):
        if y[cur] - y[prev] < min_gap:
            y[cur] = y[prev] + min_gap
    return y


def time_axis(ax, t, days, label_x=True, xlim=None):
    ax.set_xlim(*(xlim if xlim else (days[0], days[-1])))
    ax.xaxis.set_major_locator(mdates.YearLocator())
    ax.xaxis.set_minor_locator(mdates.MonthLocator(bymonth=(4, 7, 10)))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    ax.tick_params(length=0, labelsize=8.5)
    ax.tick_params(axis="x", which="minor", length=0)
    ax.xaxis.grid(True, which="major", color=t["grid"], linewidth=1.0 * SCALE)
    ax.set_axisbelow(True)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(t["axis"])
    if not label_x:
        ax.set_xticklabels([])


# --- criterion helpers (identical to wind_window_days.py) --------------------
def speed_kt(u, v):
    return np.hypot(u, v) * MS_TO_KT


def direction_from(u, v):
    """Meteorological direction the wind blows FROM, degrees."""
    return (np.degrees(np.arctan2(-u, -v)) + 360.0) % 360.0


def in_sectors(direction):
    ok = np.zeros(np.shape(direction), dtype=bool)
    for lo, hi in SECTORS:
        ok |= (direction >= lo) & (direction <= hi)
    return ok


def in_speed_band(u, v):
    s = speed_kt(u, v)
    return (s >= SPEED_MIN_KT) & (s <= SPEED_MAX_KT)


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


# --- data --------------------------------------------------------------------
def build_series(grib, geojson):
    """Daily and monthly frames, one row per region per period."""
    with open(geojson) as f:
        gj = json.load(f)

    polys = [shape(feat["geometry"]) for feat in gj["features"]]
    widths = np.array([p.bounds[2] - p.bounds[0] for p in polys])
    labels = [f"{round(w / widths.max() * 100):d}%" for w in widths]

    ds = xr.open_dataset(grib, engine="cfgrib", backend_kwargs={"indexpath": ""},
                         chunks={"time": 4000})

    lon2d, lat2d = np.meshgrid(ds.longitude.values, ds.latitude.values)
    cell_sets = []
    for label, poly in zip(labels, polys):
        pp = prep(poly)
        inside = np.array([pp.intersects(Point(x, y))
                           for x, y in zip(lon2d.ravel(), lat2d.ravel())])
        iy, ix = np.unravel_index(np.where(inside)[0], lon2d.shape)
        cell_sets.append((label, poly, iy, ix))

    # load every cell any region needs, once
    keys = sorted({(a, b) for c in cell_sets
                   for a, b in zip(c[2].tolist(), c[3].tolist())})
    key_pos = {k: i for i, k in enumerate(keys)}
    pick = ds[["u10", "v10"]].isel(
        latitude=xr.DataArray(np.array([k[0] for k in keys]), dims="cell"),
        longitude=xr.DataArray(np.array([k[1] for k in keys]), dims="cell"),
    )
    U = pick.u10.compute().values.astype("float64")  # (time, cell)
    V = pick.v10.compute().values.astype("float64")

    ok_speed_cell = in_speed_band(U, V)
    ok_dir_cell = in_sectors(direction_from(U, V))

    times = pd.DatetimeIndex(ds.time.values)
    days = pd.DatetimeIndex(np.unique(times.normalize()))
    n_days = len(days)
    day_of = np.searchsorted(days, times.normalize())

    daily_records, monthly_records, meta = [], [], []

    for label, poly, iy, ix in cell_sets:
        cols = np.array([key_pos[(a, b)] for a, b in zip(iy.tolist(), ix.tolist())])
        meta.append((label, poly.bounds, len(cols)))

        # corridor-mean wind vector -> the trace that gets plotted
        um, vm = U[:, cols].mean(axis=1), V[:, cols].mean(axis=1)
        s_hourly = speed_kt(um, vm)

        # strict all-cells tests -> the criterion marks
        ok_speed = ok_speed_cell[:, cols].all(axis=1)
        ok_dir = ok_dir_cell[:, cols].all(axis=1)
        ok_both = ok_speed & ok_dir

        met = max_run_per_day(to_day_grid(ok_both, n_days)) >= MIN_HOURS

        # daily resultant vector -> one representative speed/direction per day
        u_day = np.bincount(day_of, um, minlength=n_days) / np.bincount(day_of, minlength=n_days)
        v_day = np.bincount(day_of, vm, minlength=n_days) / np.bincount(day_of, minlength=n_days)
        dir_day = direction_from(u_day, v_day)

        daily = pd.DataFrame({
            "region": label,
            "date": days,
            "mean_speed_kt": np.bincount(day_of, s_hourly, minlength=n_days)
            / np.bincount(day_of, minlength=n_days),
            "max_speed_kt": pd.Series(s_hourly).groupby(day_of).max().to_numpy(),
            "min_speed_kt": pd.Series(s_hourly).groupby(day_of).min().to_numpy(),
            "resultant_speed_kt": speed_kt(u_day, v_day),
            "direction_deg": dir_day,
            "direction_in_sector": in_sectors(dir_day).astype(int),
            "hours_speed_ok": np.bincount(day_of, ok_speed, minlength=n_days).astype(int),
            "hours_direction_ok": np.bincount(day_of, ok_dir, minlength=n_days).astype(int),
            "hours_both_ok": np.bincount(day_of, ok_both, minlength=n_days).astype(int),
            "hours_with_data": np.bincount(day_of, minlength=n_days).astype(int),
            "met": met.astype(int),
        })
        daily_records.append(daily)

        g = daily.groupby([daily.date.dt.year, daily.date.dt.month])
        monthly = g.agg(
            hours_speed_ok=("hours_speed_ok", "sum"),
            hours_direction_ok=("hours_direction_ok", "sum"),
            hours_both_ok=("hours_both_ok", "sum"),
            hours_with_data=("hours_with_data", "sum"),
            mean_speed_kt=("mean_speed_kt", "mean"),
            days_met=("met", "sum"),
        )
        monthly.index.names = ["year", "month"]
        monthly = monthly.reset_index()
        for col in ("speed", "direction", "both"):
            monthly[f"pct_hours_{col}"] = (
                100.0 * monthly[f"hours_{col}_ok"] / monthly["hours_with_data"]
            )
        monthly.insert(0, "region", label)
        monthly_records.append(monthly)

    return (pd.concat(daily_records, ignore_index=True),
            pd.concat(monthly_records, ignore_index=True),
            labels, times, meta)


# --- figure 1: wind speed over time ------------------------------------------
def fig_speed(daily, mode):
    t = THEMES[mode]
    style(t)

    fig, axes = plt.subplots(3, 1, figsize=(15.5, 8.6), dpi=DPI, sharex=True)
    fig.subplots_adjust(left=0.05, right=0.885, top=0.835, bottom=0.075, hspace=0.30)

    top = float(np.ceil(daily.mean_speed_kt.max() / 5) * 5)
    for ax, region, color in zip(axes, REGIONS, t["ordinal"]):
        sub = daily[daily.region == region].set_index("date")
        x = sub.index

        ax.axhspan(SPEED_MIN_KT, SPEED_MAX_KT, color=t["band"], zorder=0)
        ax.set_ylim(0, top)
        ax.set_yticks(np.arange(0, top + 1, 10))
        ax.yaxis.grid(True, color=t["grid"], linewidth=1.0 * SCALE)
        time_axis(ax, t, x, label_x=(region == REGIONS[-1]))

        # daily value recedes; the 30-day mean carries the shape
        ax.plot(x, sub.mean_speed_kt, lw=0.8 * SCALE, color=color,
                alpha=t["trace_alpha"], zorder=2)
        ax.plot(x, sub.mean_speed_kt.rolling(30, center=True, min_periods=10).mean(),
                lw=2.0 * SCALE, color=color, zorder=3)

        # qualifying days as a rug on the baseline - the criterion, not the trace
        met = x[sub.met.to_numpy() == 1]
        ax.vlines(met, 0, top * 0.055, color=color, lw=1.0 * SCALE, alpha=0.9, zorder=4)

        ax.set_ylabel("kt", fontsize=9, color=t["secondary"], labelpad=6)
        ax.set_title(f"{region} corridor", fontsize=10.5, fontweight="600",
                     color=t["primary"], loc="left", pad=6)

    for ax in axes:
        edge_label(ax, t, (SPEED_MIN_KT + SPEED_MAX_KT) / 2,
                   f"{SPEED_MIN_KT:.0f}–{SPEED_MAX_KT:.0f} kt\ntarget")
        edge_label(ax, t, top * 0.028, "qualifying days")

    note(fig, t, "thin line: daily mean · thick line: 30-day centred mean · "
                 "rug on the baseline: day meeting the full criterion")
    titles(fig, t, "Wind speed over time, by corridor",
           "Corridor-mean 10 m wind speed against the "
           f"{SPEED_MIN_KT:.0f}–{SPEED_MAX_KT:.0f} kt sailing band. "
           f"Rug marks days meeting the full criterion ({CRITERION}).")
    footer(fig, t)
    fig.savefig(f"{FIGDIR}/wind_speed_timeseries_{mode}.png", dpi=DPI)
    plt.close(fig)


# --- figure 2: wind direction over time --------------------------------------
def fig_direction(daily, mode):
    t = THEMES[mode]
    style(t)

    fig, axes = plt.subplots(3, 1, figsize=(15.5, 8.6), dpi=DPI, sharex=True)
    fig.subplots_adjust(left=0.05, right=0.885, top=0.835, bottom=0.075, hspace=0.30)

    for ax, region, color in zip(axes, REGIONS, t["ordinal"]):
        sub = daily[daily.region == region].set_index("date")
        x = sub.index
        d = sub.direction_deg.to_numpy()
        met = sub.met.to_numpy() == 1

        for lo, hi in SECTORS:
            ax.axhspan(lo, hi, color=t["band"], zorder=0)
        ax.set_ylim(0, 360)
        ax.set_yticks([0, 90, 180, 270, 360], ["N", "E", "S", "W", "N"], fontsize=8.5)
        ax.yaxis.grid(True, color=t["grid"], linewidth=1.0 * SCALE)
        time_axis(ax, t, x, label_x=(region == REGIONS[-1]))

        inside = in_sectors(d)
        ax.scatter(x[~inside], d[~inside], s=2.2 * SCALE, color=t["faint"],
                   linewidths=0, zorder=2)
        ax.scatter(x[inside], d[inside], s=3.6 * SCALE, color=color,
                   linewidths=0, zorder=3)
        # days that clear the whole criterion: ringed in the surface so they read
        # as marks rather than as a denser part of the cloud
        ax.scatter(x[met], d[met], s=34 * SCALE, facecolor=color,
                   edgecolor=t["surface"], linewidths=1.1 * SCALE, zorder=4)

        ax.set_ylabel("from", fontsize=9, color=t["secondary"], labelpad=6)
        ax.set_title(f"{region} corridor", fontsize=10.5, fontweight="600",
                     color=t["primary"], loc="left", pad=6)

    for ax in axes:
        for lo, hi in SECTORS:
            edge_label(ax, t, (lo + hi) / 2, f"{lo:.0f}–{hi:.0f}°\nsector")

    note(fig, t, "dot: daily mean direction, coloured inside a sector and grey outside · "
                 "ringed dot: day meeting the full criterion")
    titles(fig, t, "Wind direction over time, by corridor",
           "Corridor-mean 10 m wind direction (FROM) against the two sailing sectors. "
           f"Ringed dots meet the full criterion ({CRITERION}).")
    footer(fig, t)
    fig.savefig(f"{FIGDIR}/wind_direction_timeseries_{mode}.png", dpi=DPI)
    plt.close(fig)


# --- figure 3: which half of the criterion binds, month by month -------------
def fig_share(monthly, mode):
    t = THEMES[mode]
    style(t)

    series = [("pct_hours_speed", f"speed in {SPEED_MIN_KT:.0f}–{SPEED_MAX_KT:.0f} kt"),
              ("pct_hours_direction", "direction in sector"),
              ("pct_hours_both", "both (criterion hours)")]

    fig, axes = plt.subplots(3, 1, figsize=(15.5, 8.6), dpi=DPI, sharex=True)
    fig.subplots_adjust(left=0.05, right=0.845, top=0.835, bottom=0.075, hspace=0.30)

    monthly = monthly.copy()
    monthly["date"] = pd.to_datetime(dict(year=monthly.year, month=monthly.month, day=15))
    top = float(np.ceil(monthly[[c for c, _ in series]].to_numpy().max() / 10) * 10)
    span = (monthly.date.min() - pd.Timedelta(days=14),
            monthly.date.max() + pd.Timedelta(days=16))

    for ax, region in zip(axes, REGIONS):
        sub = monthly[monthly.region == region].sort_values("date")
        x = sub.date.to_numpy()
        ax.set_ylim(0, top)
        ax.set_yticks(np.arange(0, top + 1, 20))
        ax.yaxis.grid(True, color=t["grid"], linewidth=1.0 * SCALE)
        time_axis(ax, t, x, label_x=(region == REGIONS[-1]), xlim=span)

        for (col, _), color in zip(series, t["cat"]):
            ax.plot(x, sub[col], lw=2.0 * SCALE, color=color, zorder=3,
                    solid_capstyle="round")

        # direct labels at the right edge, nudged apart - identity is never colour-alone
        ends = [sub[col].iloc[-1] for col, _ in series]
        for (_, label), color, y in zip(series, t["cat"], stack_labels(ends, top * 0.075)):
            edge_label(ax, t, y, label, swatch=color)

        ax.set_ylabel("% of hours", fontsize=9, color=t["secondary"], labelpad=6)
        ax.set_title(f"{region} corridor", fontsize=10.5, fontweight="600",
                     color=t["primary"], loc="left", pad=6)

    legend_row(fig, t, [label for _, label in series], t["cat"])
    titles(fig, t, "Which half of the criterion binds, month by month",
           "Share of hours in each month where the whole corridor meets the speed band, "
           "the direction sectors, and both at once (hourly test, no 6-hour run required).")
    footer(fig, t)
    fig.savefig(f"{FIGDIR}/wind_condition_share_{mode}.png", dpi=DPI)
    plt.close(fig)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--grib", default=GRIB)
    p.add_argument("--geojson", default=GEOJSON)
    p.add_argument("--from-csv", action="store_true",
                   help="redraw from the CSVs of a previous run (skips the GRIB read)")
    args = p.parse_args()

    Path(OUTDIR).mkdir(parents=True, exist_ok=True)
    Path(FIGDIR).mkdir(parents=True, exist_ok=True)

    if args.from_csv:
        daily = pd.read_csv(f"{OUTDIR}/wind_timeseries_daily.csv", parse_dates=["date"])
        monthly = pd.read_csv(f"{OUTDIR}/wind_timeseries_monthly.csv")
        times, meta = None, []
    else:
        daily, monthly, labels, times, meta = build_series(args.grib, args.geojson)
        daily.to_csv(f"{OUTDIR}/wind_timeseries_daily.csv", index=False)
        monthly.to_csv(f"{OUTDIR}/wind_timeseries_monthly.csv", index=False)

    for mode in ("light", "dark"):
        fig_speed(daily, mode)
        fig_direction(daily, mode)
        fig_share(monthly, mode)

    if meta:
        print("Regions (cell-centre selection):")
        for label, bounds, n in meta:
            print(f"  {label:>4}  lon {bounds[0]:.3f}-{bounds[2]:.3f}  "
                  f"lat {bounds[1]:.3f}-{bounds[3]:.3f}  -> {n} grid cells")
        print(f"\nPeriod: {times[0]} .. {times[-1]}  "
              f"({len(times)} hourly steps, {daily.date.nunique()} days)")

    summary = daily.groupby("region").agg(
        mean_speed_kt=("mean_speed_kt", "mean"),
        days_direction_in_sector=("direction_in_sector", "sum"),
        days_met=("met", "sum"),
    ).reindex(REGIONS).round(2)
    print("\nDaily series summary (whole record):")
    print(summary.to_string())

    print("\nMean % of hours meeting each half of the criterion (corridor-wide):")
    print(monthly.groupby("region")[["pct_hours_speed", "pct_hours_direction",
                                     "pct_hours_both"]].mean().reindex(REGIONS)
          .round(2).to_string())

    print("\nWrote:")
    for f in ("wind_timeseries_daily.csv", "wind_timeseries_monthly.csv"):
        print(f"  {OUTDIR}/{f}")
    for f in ("wind_speed_timeseries", "wind_direction_timeseries", "wind_condition_share"):
        print(f"  {FIGDIR}/{f}_light.png, {FIGDIR}/{f}_dark.png")


if __name__ == "__main__":
    main()
