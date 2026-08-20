"""
Directional speed histograms from rasterized DCSM-FM monthly output.

Reads wind or current u/v components, selects nearest grid point, divides
observations into 8 directional sectors (N/NE/E/SE/S/SW/W/NW), and plots
one speed frequency histogram per sector in a compass-layout 3×3 grid.

Run with:
  pixi run --environment metocean python output/scripts/directional_histogram.py
"""

import matplotlib
matplotlib.use("Agg")

import glob
import os

import matplotlib.pyplot as plt
import numpy as np
import xarray as xr

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
DATA_DIR    = "output/results"
OUTDIR      = "output/figures"
PATTERN     = os.path.join(DATA_DIR, "DCSM-FM_rasterized_1nm_2025-*.nc")

LON         = 3.0
LAT         = 52.0

U_VAR       = "mesh2d_windx"
V_VAR       = "mesh2d_windy"
SPEED_UNIT  = "m/s"
CONVENTION  = "met"    # "met" = wind FROM (meteorological); "ocean" = current TO

N_BINS      = 20       # histogram bins per sector
CALM_THRESH = 0.5      # m/s

os.makedirs(OUTDIR, exist_ok=True)

# ---------------------------------------------------------------------------
# 1. Load data
# ---------------------------------------------------------------------------
files = sorted(glob.glob(PATTERN))
assert files, f"No files found matching {PATTERN}"
ds = xr.open_mfdataset(files, combine="by_coords")
pt = ds[[U_VAR, V_VAR]].sel(x=LON, y=LAT, method="nearest").compute()
ds.close()

u = pt[U_VAR].values.ravel()
v = pt[V_VAR].values.ravel()
actual_lon = float(pt.x)
actual_lat = float(pt.y)

if CONVENTION == "met":
    direction = (np.degrees(np.arctan2(-u, -v)) + 360) % 360
else:
    direction = (np.degrees(np.arctan2(u, v)) + 360) % 360
speed = np.sqrt(u**2 + v**2)

valid = ~(np.isnan(direction) | np.isnan(speed))
direction, speed = direction[valid], speed[valid]

# ---------------------------------------------------------------------------
# 2. Define 8 sectors
# ---------------------------------------------------------------------------
SECTORS = [
    ("N",  337.5, 22.5),
    ("NE",  22.5, 67.5),
    ("E",   67.5, 112.5),
    ("SE", 112.5, 157.5),
    ("S",  157.5, 202.5),
    ("SW", 202.5, 247.5),
    ("W",  247.5, 292.5),
    ("NW", 292.5, 337.5),
]

def in_sector(d, lo, hi):
    """Return boolean mask for directions in sector [lo, hi), wrapping at 360."""
    if lo < hi:
        return (d >= lo) & (d < hi)
    return (d >= lo) | (d < hi)   # wraps through North

# ---------------------------------------------------------------------------
# 3. Plot: 3×3 compass layout (centre cell = statistics summary)
# ---------------------------------------------------------------------------
# compass positions in a 3×3 grid: (row, col) for N, NE, E, SE, S, SW, W, NW
POSITIONS = [(0,1), (0,2), (1,2), (2,2), (2,1), (2,0), (1,0), (0,0)]

speed_max  = np.percentile(speed[speed >= CALM_THRESH], 99)
bin_edges  = np.linspace(CALM_THRESH, speed_max, N_BINS + 1)
total      = len(speed)

# Pre-compute counts for all sectors so we can set a shared y-axis limit
sector_data = []
for name, lo, hi in SECTORS:
    mask = in_sector(direction, lo, hi) & (speed >= CALM_THRESH)
    counts, _ = np.histogram(speed[mask], bins=bin_edges)
    sector_data.append((name, speed[mask], len(speed[mask]) / total * 100, counts))

ymax = max(counts.max() for *_, counts in sector_data) * 1.1  # 10% headroom

fig, axes = plt.subplots(3, 3, figsize=(12, 10))

for (name, spd_sec, occ_pct, _), (row, col) in zip(sector_data, POSITIONS):
    ax = axes[row, col]
    ax.hist(spd_sec, bins=bin_edges, color="steelblue", edgecolor="white",
            linewidth=0.4, density=False)
    ax.set_xlim(CALM_THRESH, speed_max)
    ax.set_ylim(0, ymax)
    ax.set_title(f"{name}  ({occ_pct:.1f}%)", fontsize=10, fontweight="bold")
    ax.set_xlabel(f"Speed ({SPEED_UNIT})", fontsize=8)
    ax.set_ylabel("Count", fontsize=8)
    ax.tick_params(labelsize=7)
    ax.grid(True, alpha=0.3)

# Centre cell: overall stats
ax_c = axes[1, 1]
ax_c.axis("off")
calm_pct = (speed < CALM_THRESH).sum() / total * 100
stats_text = (
    f"lon={actual_lon:.2f}°E\nlat={actual_lat:.2f}°N\n\n"
    f"N = {total}\n"
    f"Calm: {calm_pct:.1f}%\n(<{CALM_THRESH} {SPEED_UNIT})\n\n"
    f"Mean:  {speed.mean():.2f} {SPEED_UNIT}\n"
    f"P50:   {np.percentile(speed, 50):.2f} {SPEED_UNIT}\n"
    f"P95:   {np.percentile(speed, 95):.2f} {SPEED_UNIT}\n"
    f"Max:   {speed.max():.2f} {SPEED_UNIT}"
)
ax_c.text(0.5, 0.5, stats_text, transform=ax_c.transAxes,
          ha="center", va="center", fontsize=9,
          bbox=dict(boxstyle="round", facecolor="lightyellow", alpha=0.8))

convention_label = "FROM (meteorological)" if CONVENTION == "met" else "TO (oceanographic)"
fig.suptitle(
    f"Directional speed histograms  |  direction {convention_label}\n"
    f"{U_VAR.replace('mesh2d_', '')} / {V_VAR.replace('mesh2d_', '')}",
    fontsize=12, y=1.01,
)
plt.tight_layout()

figfile = os.path.join(OUTDIR, "directional_histogram.png")
plt.savefig(figfile, dpi=150, bbox_inches="tight")
print(f"Saved: {figfile}")
