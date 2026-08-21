#!/usr/bin/env python3
"""Optimise today's route against the latest forecast and draw the daily figure.

Reads the GRIB written by ``fetch_forecast.py``, runs ``route.route`` against it,
and replaces two outputs in place so the site always shows the newest run:

    frontend/data/route-today.json          the track the Route page draws
    output/figures/daily/forecast_route_{light,dark}.png

Uses xarray/cfgrib rather than pygrib -- ``route.route`` takes an injected
``wind_at``, so the optimiser never has to import a GRIB library itself, and this
runs anywhere xarray does.

    python route/daily_forecast.py
"""

from __future__ import annotations

import argparse
import bisect
import datetime as dt
import json
import math
from pathlib import Path

import matplotlib
matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import xarray as xr

import route as R

ROOT = Path(__file__).resolve().parents[1]
GRIB = Path(__file__).resolve().parent / "forecast" / "gfs_latest.grb2"
CYCLE_META = Path(__file__).resolve().parent / "forecast" / "cycle.json"
ROUTE_JSON = ROOT / "frontend" / "data" / "route-today.json"
FIG_DIR = ROOT / "output" / "figures" / "daily"

MS_TO_KT = 1.943844
DEFAULT_CURRENT = {"speed": 1.0, "toward": 45.0}

# the site's validated palette (frontend/assets/style.css), light and dark steps
THEMES = {
    "light": dict(surface="#fcfcfb", ink="#0b0b0b", ink2="#52514e", muted="#898781",
                  grid="#e1e0d9", wind="#2a78d6", boat="#eb6834"),
    "dark":  dict(surface="#1a1a19", ink="#ffffff", ink2="#c3c2b7", muted="#898781",
                  grid="#2c2c2a", wind="#3987e5", boat="#d95926"),
}


# ---------------------------------------------------------------- wind field

def wind_provider(path: Path = GRIB):
    """Return a route.py-compatible wind_at(point, elapsed_hours).

    Matches route.load_wind's conventions exactly: knots, meteorological
    "from" direction, nearest grid cell, linear in time.
    """
    ds = xr.open_dataset(path, engine="cfgrib", backend_kwargs={"indexpath": ""})
    lats = ds.latitude.values
    lons = ds.longitude.values
    hours = (ds.step.values / np.timedelta64(1, "h")).astype(float).tolist()
    u_all = ds.u10.values
    v_all = ds.v10.values

    def wind_at(point: R.Point, elapsed_hours: float):
        # clamp rather than raise: the optimiser may probe just past the horizon
        t = min(max(elapsed_hours, hours[0]), hours[-1])
        upper = min(bisect.bisect_left(hours, t), len(hours) - 1)
        lower = max(0, upper - 1)
        frac = 0.0 if upper == lower else (t - hours[lower]) / (hours[upper] - hours[lower])
        row = int(np.abs(lats - point.lat).argmin())
        col = int(np.abs(((lons - point.lon + 180) % 360) - 180).argmin())
        u = u_all[lower, row, col] + frac * (u_all[upper, row, col] - u_all[lower, row, col])
        v = v_all[lower, row, col] + frac * (v_all[upper, row, col] - v_all[lower, row, col])
        u_kt, v_kt = float(u) * MS_TO_KT, float(v) * MS_TO_KT
        return math.hypot(u_kt, v_kt), math.degrees(math.atan2(-u, -v)) % 360, u_kt, v_kt

    return wind_at, ds


# ---------------------------------------------------------------- the figure

def leg_speeds(points: list[list[float]]) -> list[float]:
    """Speed over ground per leg, knots (route steps are STEP_MINUTES apart)."""
    step_h = R.STEP_MINUTES / 60
    out = []
    for a, b in zip(points, points[1:]):
        d = R.distance_nm(R.Point(*a), R.Point(*b))
        out.append(d / step_h)
    return out


def draw(theme_name: str, payload: dict, ds, cycle: dt.datetime) -> Path:
    c = THEMES[theme_name]
    pts = payload["route"]
    vectors = payload["wind_vectors"]
    lat = [p[0] for p in pts]
    lon = [p[1] for p in pts]

    fig = plt.figure(figsize=(11, 4.6), dpi=130)
    fig.patch.set_facecolor(c["surface"])
    gs = fig.add_gridspec(1, 2, width_ratios=[1.35, 1], wspace=0.24,
                          left=0.06, right=0.975, top=0.80, bottom=0.15)

    # ---- panel A: the track, with the forecast wind field behind it
    ax = fig.add_subplot(gs[0, 0])
    ax.set_facecolor(c["surface"])

    mid = len(ds.step) // 2
    LON, LAT = np.meshgrid(ds.longitude.values, ds.latitude.values)
    u = ds.u10.values[mid] * MS_TO_KT
    v = ds.v10.values[mid] * MS_TO_KT
    ax.quiver(LON, LAT, u, v, color=c["muted"], alpha=0.55, width=0.0035,
              scale=260, headwidth=3.2, headlength=3.6, zorder=1)

    ax.plot(lon, lat, color=c["boat"], lw=2.4, solid_capstyle="round", zorder=3)
    ax.plot(lon[0], lat[0], "o", ms=8, color="#16803c", zorder=4)
    ax.plot(lon[-1], lat[-1], "o", ms=8, color="#c81e1e", zorder=4)
    ax.annotate("Lowestoft", (lon[0], lat[0]), textcoords="offset points",
                xytext=(6, 9), color=c["ink2"], fontsize=8.5)
    ax.annotate("IJmuiden", (R.DEFAULT_DESTINATION[1], R.DEFAULT_DESTINATION[0]),
                textcoords="offset points", xytext=(-6, 9), ha="right",
                color=c["ink2"], fontsize=8.5)

    # true geographic aspect at this latitude, and a tighter box so the corridor
    # fills the panel instead of floating in empty sea
    ax.set_aspect(1 / math.cos(math.radians(52.5)))
    ax.set_ylim(51.9, 53.1)
    ax.set_xlabel("longitude °E", color=c["ink2"], fontsize=9)
    ax.set_ylabel("latitude °N", color=c["ink2"], fontsize=9)
    ax.set_title(f"Optimised track · wind at +{int(mid)} h", color=c["ink"],
                 fontsize=10.5, loc="left", pad=6)
    ax.grid(True, color=c["grid"], lw=0.7, alpha=0.9)
    ax.set_axisbelow(True)

    # ---- panel B: wind and boat speed along the track (same unit, one axis)
    ax2 = fig.add_subplot(gs[0, 1])
    ax2.set_facecolor(c["surface"])
    t = [w["elapsed_hours"] for w in vectors]
    wind_kt = [w["speed_knots"] for w in vectors]
    boat = leg_speeds(pts)
    t_boat = [(a + b) / 2 for a, b in zip(t, t[1:])]

    ax2.plot(t, wind_kt, color=c["wind"], lw=2, solid_capstyle="round", label="Wind")
    ax2.plot(t_boat, boat, color=c["boat"], lw=2, solid_capstyle="round", label="Boat over ground")
    # the two lines converge at the right edge, so end-labels collide -- legend instead
    leg = ax2.legend(loc="lower right", frameon=False, fontsize=9, handlelength=1.6,
                     borderpad=0.2, labelspacing=0.3)
    for text in leg.get_texts():
        text.set_color(c["ink2"])

    ax2.set_xlabel("hours from start", color=c["ink2"], fontsize=9)
    ax2.set_ylabel("knots", color=c["ink2"], fontsize=9)
    ax2.set_title("Wind and boat speed along the track", color=c["ink"],
                  fontsize=10.5, loc="left", pad=6)
    ax2.set_ylim(0, max(max(wind_kt), max(boat)) * 1.25)
    ax2.set_xlim(0, t[-1])
    ax2.grid(True, color=c["grid"], lw=0.7, alpha=0.9)
    ax2.set_axisbelow(True)

    for a in (ax, ax2):
        for s in a.spines.values():
            s.set_color(c["grid"])
        a.tick_params(colors=c["ink2"], labelsize=8.5)

    reached = payload["reached_destination"]
    outcome = (f"{payload['duration_hours']:.2f} h to IJmuiden"
               if reached else
               f"{payload['duration_hours']:.2f} h, stopped {payload['remaining_nm']:.1f} nm short")
    fig.suptitle(f"Lowestoft → IJmuiden · GFS {cycle:%Y-%m-%d %H:%M} UTC · {outcome}",
                 color=c["ink"], fontsize=12.5, x=0.06, ha="left", y=0.945)
    fig.text(0.06, 0.885, "Regenerated daily from the newest GFS cycle. "
             "Arrows show where the wind blows toward.",
             color=c["muted"], fontsize=8.5, ha="left")

    FIG_DIR.mkdir(parents=True, exist_ok=True)
    out = FIG_DIR / f"forecast_route_{theme_name}.png"
    fig.savefig(out, facecolor=c["surface"], bbox_inches="tight", pad_inches=0.25)
    plt.close(fig)
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--current-speed", type=float, default=DEFAULT_CURRENT["speed"])
    ap.add_argument("--current-toward", type=float, default=DEFAULT_CURRENT["toward"])
    args = ap.parse_args()

    if not GRIB.exists():
        raise SystemExit(f"{GRIB} missing — run route/fetch_forecast.py first")

    meta = json.loads(CYCLE_META.read_text()) if CYCLE_META.exists() else {}
    cycle = dt.datetime.fromisoformat(meta["cycle"]) if meta.get("cycle") else dt.datetime.now(dt.timezone.utc)

    wind_at, ds = wind_provider()
    current = {"speed": args.current_speed, "toward": args.current_toward}
    result = R.route({"current": current}, R.load_polars(), wind_at)
    payload = R.result_json(result, wind_at)
    payload |= {
        "source": "gfs",
        "cycle": cycle.isoformat(),
        "generated": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "current": current,
        "note": (f"Optimised against NOAA GFS {cycle:%Y-%m-%d %H:%M} UTC, "
                 f"current {current['speed']:.0f} kt toward {current['toward']:.0f} T."),
    }
    ROUTE_JSON.parent.mkdir(parents=True, exist_ok=True)
    ROUTE_JSON.write_text(json.dumps(payload, indent=2) + "\n")

    figs = [draw(name, payload, ds, cycle) for name in THEMES]
    print(f"{len(payload['route'])} legs, {payload['duration_hours']} h, "
          f"reached={payload['reached_destination']}")
    print(f"  -> {ROUTE_JSON.relative_to(ROOT)}")
    for f in figs:
        print(f"  -> {f.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
