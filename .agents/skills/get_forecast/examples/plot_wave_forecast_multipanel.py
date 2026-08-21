"""Plot a 2x2 map of wind-sea and swell wave conditions.

Plots the first timestep of a wave forecast NetCDF file (as produced by
get_current_wave_forecast.py / get_wave_forecast.py) as a 2x2 grid:

    - Left column:  wind-sea significant wave height (VHM0_WW, top, with
                     directional arrows from VMDR_WW) and wind-sea mean
                     wave period (VTM01_WW, bottom).
    - Right column: primary swell significant wave height (VHM0_SW1, top,
                     with directional arrows from VMDR_SW1) and primary
                     swell mean wave period (VTM01_SW1, bottom).

Run with the `metocean` pixi environment, e.g.:
    pixi run -e metocean python plot_wave_forecast_multipanel.py
"""

import argparse
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import xarray as xr

# Height / period / mean-direction-from variable names for each wave component.
WIND_SEA = {"height": "VHM0_WW", "period": "VTM01_WW", "direction": "VMDR_WW"}
SWELL = {"height": "VHM0_SW1", "period": "VTM01_SW1", "direction": "VMDR_SW1"}

DEFAULT_RESULTS_DIR = Path("output/results")
DEFAULT_FIGURES_DIR = Path("output/figures")

# Keep every QUIVER_STRIDE-th grid point when drawing directional arrows.
QUIVER_STRIDE = 5


def find_latest_forecast(results_dir: Path = DEFAULT_RESULTS_DIR) -> Path:
    """Return the most recently modified wave_forecast_*.nc file."""
    candidates = sorted(
        results_dir.glob("wave_forecast_*.nc"), key=lambda p: p.stat().st_mtime
    )
    if not candidates:
        raise FileNotFoundError(
            f"No wave_forecast_*.nc files found in {results_dir}. "
            "Run get_current_wave_forecast.py first."
        )
    return candidates[-1]


def plot_height_with_direction(ax, height, direction, title, vmin=None, vmax=None):
    """Plot a significant wave height field with directional arrows.

    `direction` follows the oceanographic "from direction" convention
    (degrees clockwise from true north), so arrows are drawn pointing
    towards where the wave energy is propagating to.
    """
    height.plot.pcolormesh(
        x="longitude",
        y="latitude",
        ax=ax,
        cmap="viridis",
        vmin=vmin,
        vmax=vmax,
        cbar_kwargs={"label": f"{height.name} (m)"},
    )

    direction_sub = direction.isel(
        longitude=slice(None, None, QUIVER_STRIDE),
        latitude=slice(None, None, QUIVER_STRIDE),
    )
    theta = np.deg2rad(direction_sub.values)
    u = -np.sin(theta)
    v = -np.cos(theta)
    ax.quiver(
        direction_sub["longitude"],
        direction_sub["latitude"],
        u,
        v,
        color="white",
        edgecolor="black",
        linewidth=0.4,
        scale=25,
        width=0.004,
    )

    ax.set_title(title)
    ax.set_xlabel("Longitude (\u00b0E)")
    ax.set_ylabel("Latitude (\u00b0N)")
    mean_lat = float(height["latitude"].mean())
    ax.set_aspect(1 / np.cos(np.deg2rad(mean_lat)))


def plot_period(ax, period, title, vmin=None, vmax=None):
    period.plot.pcolormesh(
        x="longitude",
        y="latitude",
        ax=ax,
        cmap="cividis",
        vmin=vmin,
        vmax=vmax,
        cbar_kwargs={"label": f"{period.name} (s)"},
    )
    ax.set_title(title)
    ax.set_xlabel("Longitude (\u00b0E)")
    ax.set_ylabel("Latitude (\u00b0N)")
    mean_lat = float(period["latitude"].mean())
    ax.set_aspect(1 / np.cos(np.deg2rad(mean_lat)))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input-file",
        type=Path,
        default=None,
        help="Path to the forecast NetCDF file (default: latest file in "
        f"{DEFAULT_RESULTS_DIR}).",
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

    height_vmin = float(
        min(ds[WIND_SEA["height"]].min(), ds[SWELL["height"]].min())
    )
    height_vmax = float(
        max(ds[WIND_SEA["height"]].max(), ds[SWELL["height"]].max())
    )
    period_vmin = float(
        min(ds[WIND_SEA["period"]].min(), ds[SWELL["period"]].min())
    )
    period_vmax = float(
        max(ds[WIND_SEA["period"]].max(), ds[SWELL["period"]].max())
    )

    fig, axes = plt.subplots(2, 2, figsize=(16, 7), constrained_layout=True)

    plot_height_with_direction(
        axes[0, 0],
        ds[WIND_SEA["height"]],
        ds[WIND_SEA["direction"]],
        "Wind-sea significant wave height & direction",
        vmin=height_vmin,
        vmax=height_vmax,
    )
    plot_period(
        axes[1, 0],
        ds[WIND_SEA["period"]],
        "Wind-sea mean wave period",
        vmin=period_vmin,
        vmax=period_vmax,
    )
    plot_height_with_direction(
        axes[0, 1],
        ds[SWELL["height"]],
        ds[SWELL["direction"]],
        "Swell significant wave height & direction",
        vmin=height_vmin,
        vmax=height_vmax,
    )
    plot_period(
        axes[1, 1],
        ds[SWELL["period"]],
        "Swell mean wave period",
        vmin=period_vmin,
        vmax=period_vmax,
    )

    fig.suptitle(f"Wave forecast \u2014 {timestamp}", fontsize=14)

    args.output_directory.mkdir(parents=True, exist_ok=True)
    output_file = (
        args.output_directory / f"wave_forecast_multipanel_{timestamp_str}.png"
    )
    fig.savefig(output_file, dpi=150)
    print(f"Saved plot to {output_file}")


if __name__ == "__main__":
    main()
