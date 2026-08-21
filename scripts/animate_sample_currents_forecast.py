"""Animate depth-averaged current speed/direction with a timeseries subplot.

Reads today's sample currents forecast (as produced by
scripts/get_sample_currents_forecast.py) from sample_forecast_data/ and
renders one frame per timestep with two panels: a map of current
speed/direction on top, and a timeseries of current speed at the centre grid
point of the domain for the full forecast period on the bottom, with a
moving red dot marking the current timestep.

Colour scale convention: vmin=0, vmax = 99th percentile of the current speed
over the whole animated period (kept fixed across all frames to avoid
flicker/rescaling between frames).

Run with the `metocean` pixi environment, e.g.:
    pixi run -e metocean python scripts/animate_sample_currents_forecast.py
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

ROOT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_SAMPLE_DIR = ROOT_DIR / "sample_forecast_data"
DEFAULT_FIGURES_DIR = ROOT_DIR / "sample_forecast_data" / "figures"

# Keep every QUIVER_STRIDE-th grid point when drawing directional arrows.
QUIVER_STRIDE = 5
# Milliseconds per frame in the output GIF.
FRAME_DURATION_MS = 200


def find_todays_forecast(sample_dir: Path = DEFAULT_SAMPLE_DIR) -> Path:
    """Return today's currents_forecast_<YYYYmmdd>.nc file from sample_dir."""
    today_str = datetime.now().strftime("%Y%m%d")
    candidate = sample_dir / f"currents_forecast_{today_str}.nc"
    if not candidate.exists():
        raise FileNotFoundError(
            f"No currents_forecast_{today_str}.nc file found in {sample_dir}. "
            "Run scripts/get_sample_currents_forecast.py first."
        )
    return candidate


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input-file",
        type=Path,
        default=None,
        help="Path to the sample currents forecast NetCDF file (default: "
        f"today's currents_forecast_<YYYYmmdd>.nc in {DEFAULT_SAMPLE_DIR}).",
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

    ds_full = xr.open_dataset(input_file)
    ds = ds_full.isel(time=slice(None, None, args.hour_step))

    speed = np.sqrt(ds["uo"] ** 2 + ds["vo"] ** 2)
    speed_vmax = float(np.nanpercentile(speed.values, 99))
    print(f"Colour scale: vmin=0, vmax={speed_vmax:.3f} m/s (P99 over full period)")

    mean_lat = float(ds["latitude"].mean())
    aspect = 1 / np.cos(np.deg2rad(mean_lat))

    # Centre point of the domain, used for the timeseries subplot.
    center_lon = float(ds["longitude"].isel(longitude=ds.sizes["longitude"] // 2))
    center_lat = float(ds["latitude"].isel(latitude=ds.sizes["latitude"] // 2))
    center_speed_full = np.sqrt(
        ds_full["uo"].sel(longitude=center_lon, latitude=center_lat) ** 2
        + ds_full["vo"].sel(longitude=center_lon, latitude=center_lat) ** 2
    )
    center_times = center_speed_full["time"].values
    print(f"Timeseries point: lon={center_lon:.4f}, lat={center_lat:.4f}")

    u_sub_full = ds["uo"].isel(
        longitude=slice(None, None, QUIVER_STRIDE),
        latitude=slice(None, None, QUIVER_STRIDE),
    )
    v_sub_full = ds["vo"].isel(
        longitude=slice(None, None, QUIVER_STRIDE),
        latitude=slice(None, None, QUIVER_STRIDE),
    )

    frames = []
    for t in ds["time"].values:
        speed_t = speed.sel(time=t)
        u_t = u_sub_full.sel(time=t)
        v_t = v_sub_full.sel(time=t)

        fig, (ax, ax_ts) = plt.subplots(
            2,
            1,
            figsize=(10, 8.5),
            constrained_layout=True,
            gridspec_kw={"height_ratios": [3, 1]},
        )
        speed_t.plot.pcolormesh(
            x="longitude",
            y="latitude",
            ax=ax,
            cmap="viridis",
            vmin=0,
            vmax=speed_vmax,
            cbar_kwargs={"label": "Depth-averaged current speed (m/s)"},
        )
        ax.quiver(
            u_t["longitude"],
            u_t["latitude"],
            u_t.values,
            v_t.values,
            color="white",
            edgecolor="black",
            linewidth=0.4,
            scale=15,
            width=0.005,
        )
        ax.plot(center_lon, center_lat, "r*", markersize=12, markeredgecolor="black")

        timestamp = np.datetime_as_string(t, unit="m")
        ax.set_title(f"Depth-averaged current speed & direction\n{timestamp}")
        ax.set_xlabel("Longitude (\u00b0E)")
        ax.set_ylabel("Latitude (\u00b0N)")
        ax.set_aspect(aspect)

        ax_ts.plot(center_times, center_speed_full.values, color="tab:blue")
        ax_ts.plot(t, float(center_speed_full.sel(time=t)), "ro", markersize=8)
        ax_ts.set_title(
            f"Current speed at centre point (lon={center_lon:.2f}\u00b0E, "
            f"lat={center_lat:.2f}\u00b0N)"
        )
        ax_ts.set_xlabel("Time")
        ax_ts.set_ylabel("Speed (m/s)")
        ax_ts.set_xlim(center_times[0], center_times[-1])
        ax_ts.tick_params(axis="x", rotation=30)

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
        / f"currents_animation_{first_timestamp}_to_{last_timestamp}.gif"
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
