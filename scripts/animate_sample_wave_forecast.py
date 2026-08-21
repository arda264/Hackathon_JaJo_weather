"""Animate the 2x2 wind-sea/swell wave conditions multipanel plot.

Reads today's sample wave forecast (as produced by
scripts/get_sample_wave_forecast.py) from sample_forecast_data/ and renders
one frame per timestep of the same 2x2 layout used by
plot_wave_forecast_multipanel.py:

    - Left column:  wind-sea significant wave height (VHM0_WW, top, with
                     directional arrows from VMDR_WW) and wind-sea mean
                     wave period (VTM01_WW, bottom).
    - Right column: primary swell significant wave height (VHM0_SW1, top,
                     with directional arrows from VMDR_SW1) and primary
                     swell mean wave period (VTM01_SW1, bottom).

Colour scale convention: colorbar limits are shared between the two height
panels, and separately between the two period panels, and are kept FIXED
across all animation frames (computed once over the whole forecast period)
to avoid flicker/rescaling between frames.

Run with the `metocean` pixi environment, e.g.:
    pixi run -e metocean python scripts/animate_sample_wave_forecast.py
"""

import argparse
import io
from datetime import datetime
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import xarray as xr
from PIL import Image

# Height / period / mean-direction-from variable names for each wave component.
WIND_SEA = {"height": "VHM0_WW", "period": "VTM01_WW", "direction": "VMDR_WW"}
SWELL = {"height": "VHM0_SW1", "period": "VTM01_SW1", "direction": "VMDR_SW1"}

ROOT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_SAMPLE_DIR = ROOT_DIR / "sample_forecast_data"
DEFAULT_FIGURES_DIR = ROOT_DIR / "sample_forecast_data" / "figures"

# Keep every QUIVER_STRIDE-th grid point when drawing directional arrows.
QUIVER_STRIDE = 5
# Milliseconds per frame in the output GIF.
FRAME_DURATION_MS = 200


def find_todays_forecast(sample_dir: Path = DEFAULT_SAMPLE_DIR) -> Path:
    """Return today's wave_forecast_<YYYYmmdd>.nc file from sample_dir."""
    today_str = datetime.now().strftime("%Y%m%d")
    candidate = sample_dir / f"wave_forecast_{today_str}.nc"
    if not candidate.exists():
        raise FileNotFoundError(
            f"No wave_forecast_{today_str}.nc file found in {sample_dir}. "
            "Run scripts/get_sample_wave_forecast.py first."
        )
    return candidate


def plot_height_with_direction(ax, height, direction, title, vmin, vmax):
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


def plot_period(ax, period, title, vmin, vmax):
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
        help="Path to the sample wave forecast NetCDF file (default: today's "
        f"wave_forecast_<YYYYmmdd>.nc in {DEFAULT_SAMPLE_DIR}).",
    )
    parser.add_argument(
        "--output-directory",
        type=Path,
        default=DEFAULT_FIGURES_DIR,
        help=f"Directory to save the animation to (default: {DEFAULT_FIGURES_DIR}).",
    )
    parser.add_argument(
        "--hour-step",
        type=int,
        default=1,
        help="Use every Nth hourly timestep as an animation frame (default: 1, i.e. all hourly frames).",
    )
    args = parser.parse_args()

    input_file = args.input_file or find_todays_forecast()
    print(f"Reading {input_file}")

    ds = xr.open_dataset(input_file).isel(time=slice(None, None, args.hour_step))

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
    print(
        f"Height colour scale: {height_vmin:.2f}-{height_vmax:.2f} m; "
        f"Period colour scale: {period_vmin:.2f}-{period_vmax:.2f} s"
    )

    frames = []
    for t in ds["time"].values:
        ds_t = ds.sel(time=t)
        timestamp = np.datetime_as_string(t, unit="m")

        fig, axes = plt.subplots(2, 2, figsize=(16, 7), constrained_layout=True)

        plot_height_with_direction(
            axes[0, 0],
            ds_t[WIND_SEA["height"]],
            ds_t[WIND_SEA["direction"]],
            "Wind-sea significant wave height & direction",
            vmin=height_vmin,
            vmax=height_vmax,
        )
        plot_period(
            axes[1, 0],
            ds_t[WIND_SEA["period"]],
            "Wind-sea mean wave period",
            vmin=period_vmin,
            vmax=period_vmax,
        )
        plot_height_with_direction(
            axes[0, 1],
            ds_t[SWELL["height"]],
            ds_t[SWELL["direction"]],
            "Swell significant wave height & direction",
            vmin=height_vmin,
            vmax=height_vmax,
        )
        plot_period(
            axes[1, 1],
            ds_t[SWELL["period"]],
            "Swell mean wave period",
            vmin=period_vmin,
            vmax=period_vmax,
        )

        fig.suptitle(f"Wave forecast \u2014 {timestamp}", fontsize=14)

        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=120)
        plt.close(fig)
        buf.seek(0)
        frames.append(Image.open(buf).convert("RGB"))
        print(f"  rendered frame {timestamp}")

    args.output_directory.mkdir(parents=True, exist_ok=True)
    first_timestamp = np.datetime_as_string(ds["time"].values[0], unit="h")
    last_timestamp = np.datetime_as_string(ds["time"].values[-1], unit="h")
    output_file = (
        args.output_directory
        / f"wave_forecast_multipanel_animation_{first_timestamp}_to_{last_timestamp}.gif"
    )
    frames[0].save(
        output_file,
        save_all=True,
        append_images=frames[1:],
        duration=FRAME_DURATION_MS,
        loop=0,
    )
    print(f"Saved animation to {output_file} ({len(frames)} frames)")


if __name__ == "__main__":
    main()
