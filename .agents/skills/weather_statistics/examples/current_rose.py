"""
Current velocity rose from rasterized DCSM-FM monthly output.

Reads current u/v components from monthly NetCDF files, selects the nearest
grid point to a specified lon/lat, computes oceanographic current direction
(TO), and draws a 16-sector rose coloured by speed class using windrose.

Oceanographic convention: direction the current flows TO.
  dir = (degrees(arctan2(u, v)) + 360) % 360

Run with:
  pixi run --environment metocean python output/scripts/current_rose.py
"""

import matplotlib
matplotlib.use("Agg")

import glob
import os

import matplotlib.pyplot as plt
import numpy as np
import xarray as xr
from windrose import WindroseAxes

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
DATA_DIR    = "output/results"
OUTDIR      = "output/figures"
PATTERN     = os.path.join(DATA_DIR, "DCSM-FM_rasterized_1nm_2025-*.nc")

LON         = 3.0       # target longitude (°E)
LAT         = 52.0      # target latitude (°N)

N_SECTORS   = 16        # number of directional bins
N_CLASSES   = 5         # number of speed classes
CALM_THRESH = 0.05      # m/s — calm threshold for currents

U_VAR       = "mesh2d_ucx"
V_VAR       = "mesh2d_ucy"
SPEED_UNIT  = "m/s"

os.makedirs(OUTDIR, exist_ok=True)

# ---------------------------------------------------------------------------
# 1. Load data and select nearest grid point
# ---------------------------------------------------------------------------
files = sorted(glob.glob(PATTERN))
assert files, f"No files found matching {PATTERN}"
print(f"Loading {len(files)} file(s) …")

ds = xr.open_mfdataset(files, combine="by_coords")
pt = ds[[U_VAR, V_VAR]].sel(x=LON, y=LAT, method="nearest").compute()
ds.close()

u = pt[U_VAR].values.ravel()
v = pt[V_VAR].values.ravel()
actual_lon = float(pt.x)
actual_lat = float(pt.y)
print(f"Grid point: lon={actual_lon:.3f}°  lat={actual_lat:.3f}°  N={len(u)}")

# ---------------------------------------------------------------------------
# 2. Compute oceanographic direction (TO) and speed
# ---------------------------------------------------------------------------
direction = (np.degrees(np.arctan2(u, v)) + 360) % 360
speed     = np.sqrt(u**2 + v**2)

valid     = ~(np.isnan(direction) | np.isnan(speed))
direction, speed = direction[valid], speed[valid]

calm_pct = (speed < CALM_THRESH).sum() / len(speed) * 100

# ---------------------------------------------------------------------------
# 3. Speed bins (equal-frequency quantiles, excluding calm)
# ---------------------------------------------------------------------------
speed_noncalm = speed[speed >= CALM_THRESH]
bins = np.quantile(speed_noncalm, np.linspace(0, 1, N_CLASSES + 1))
bins[0] = CALM_THRESH  # first bin edge must equal calm_limit

# ---------------------------------------------------------------------------
# 4. Plot with windrose
# ---------------------------------------------------------------------------
fig = plt.figure(figsize=(8, 8))
ax  = WindroseAxes.from_ax(fig=fig)

ax.bar(direction, speed, normed=True, opening=0.9,
       bins=bins, nsector=N_SECTORS,
       calm_limit=CALM_THRESH,
       cmap=plt.cm.Blues, edgecolor="white", linewidth=0.4)

ax.set_legend(title=f"Current speed ({SPEED_UNIT})", loc="lower left",
              bbox_to_anchor=(-0.15, -0.15), fontsize=8)

ax.set_title(
    f"Current rose  (direction TO)\n"
    f"lon={actual_lon:.2f}°E, lat={actual_lat:.2f}°N  |  "
    f"N={len(speed)}  |  calm={calm_pct:.1f}% (<{CALM_THRESH} {SPEED_UNIT})",
    fontsize=10, pad=14,
)

figfile = os.path.join(OUTDIR, "current_rose.png")
plt.savefig(figfile, dpi=150, bbox_inches="tight")
print(f"Saved: {figfile}")
