"""Plot depth-averaged current velocity (speed + direction) on a map.

Plots the first timestep of a currents forecast NetCDF file (as produced by
get_current_currents_forecast.py / get_currents_forecast.py). The
`cmems_mod_nws_phy-cur_anfc_1.5km-2D_PT1H-i` dataset provides 2D
depth-averaged currents (no vertical/depth dimension).

Run with the `metocean` pixi environment, e.g.:
    pixi run -e metocean python plot_currents.py
"""

import argparse
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import xarray as xr

DEFAULT_RESULTS_DIR = Path("output/results")
DEFAULT_FIGURES_DIR = Path("output/figures")

# Keep every QUIVER_STRIDE-th grid point when drawing directional arrows.
QUIVER_STRIDE = 5


def find_latest_forecast(results_dir: Path = DEFAULT_RESULTS_DIR) -> Path:
    """Return the most recently modified currents_forecast_*.nc file."""
    candidates = sorted(
        results_dir.glob("currents_forecast_*.nc"), key=lambda p: p.stat().st_mtime
    )
    if not candidates:
        raise FileNotFoundError(
            f"No currents_forecast_*.nc files found in {results_dir}. "
            "Run get_current_currents_forecast.py first."
        )
    return candidates[-1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input-file",
        type=Path,
        default=None,
        help="Path to the currents forecast NetCDF file (default: latest file "
        f"in {DEFAULT_RESULTS_DIR}).",
    )
    parser.add_argument(
        "--output-directory",
        type=Path,
        default=DEFAULT_FIGURES_DIR,
        help=f"Directory to save the plot to (default: {DEFAULT_FIGURES_DIR}).",
    )
    args = parser.parse_args()

    input_file = args.input_file or find_latest_forecast()
    print(f"Reading {input_file}")

    ds = xr.open_dataset(input_file).isel(time=0)
    timestamp = ds["time"].values
    timestamp_str = str(timestamp)[:19].replace(":", "").replace("-", "")

    u = ds["uo"]
    v = ds["vo"]
    speed = np.sqrt(u**2 + v**2)
    speed.name = "current_speed"

    fig, ax = plt.subplots(figsize=(10, 6), constrained_layout=True)
    speed.plot.pcolormesh(
        x="longitude",
        y="latitude",
        ax=ax,
        cmap="viridis",
        cbar_kwargs={"label": "Depth-averaged current speed (m/s)"},
    )

    u_sub = u.isel(
        longitude=slice(None, None, QUIVER_STRIDE),
        latitude=slice(None, None, QUIVER_STRIDE),
    )
    v_sub = v.isel(
        longitude=slice(None, None, QUIVER_STRIDE),
        latitude=slice(None, None, QUIVER_STRIDE),
    )
    ax.quiver(
        u_sub["longitude"],
        u_sub["latitude"],
        u_sub.values,
        v_sub.values,
        color="white",
        edgecolor="black",
        linewidth=0.4,
        scale=15,
        width=0.005,
    )

    ax.set_title(f"Depth-averaged current speed & direction\n{timestamp}")
    ax.set_xlabel("Longitude (\u00b0E)")
    ax.set_ylabel("Latitude (\u00b0N)")
    mean_lat = float(ds["latitude"].mean())
    ax.set_aspect(1 / np.cos(np.deg2rad(mean_lat)))

    args.output_directory.mkdir(parents=True, exist_ok=True)
    output_file = (
        args.output_directory / f"currents_{timestamp_str}.png"
    )
    fig.savefig(output_file, dpi=150)
    print(f"Saved plot to {output_file}")


if __name__ == "__main__":
    main()
