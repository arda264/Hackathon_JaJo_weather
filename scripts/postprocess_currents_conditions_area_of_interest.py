"""Check current conditions within the area of interest for the sample forecast.

Reads today's sample currents forecast (as produced by
scripts/get_sample_currents_forecast.py) from sample_forecast_data/, subsets
it to the polygon defined in geometry/area_of_interest.geojson, and computes
the spatial mean current velocity (magnitude and direction) within that area
for each timestep.

Produces a 2-row timeseries plot (current speed / current direction),
and saves the aggregated timeseries (speed, direction, and the underlying
eastward/northward components) as a CSV file to
sample_forecast_data/postprocessed/.

Run with the `metocean` pixi environment, e.g.:
    pixi run -e metocean python scripts/postprocess_currents_conditions_area_of_interest.py
"""

import argparse
from datetime import datetime
from pathlib import Path

import geopandas as gpd
import matplotlib.pyplot as plt
import numpy as np
import shapely
import xarray as xr

ROOT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_SAMPLE_DIR = ROOT_DIR / "sample_forecast_data"
DEFAULT_FIGURES_DIR = ROOT_DIR / "sample_forecast_data" / "figures"
DEFAULT_POSTPROCESSED_DIR = ROOT_DIR / "sample_forecast_data" / "postprocessed"
DEFAULT_GEOJSON = ROOT_DIR / "geometry" / "area_of_interest.geojson"


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


def area_of_interest_mask(ds: xr.Dataset, geojson_file: Path) -> xr.DataArray:
    """Return a boolean 2D (latitude, longitude) mask for points inside the AOI."""
    gdf = gpd.read_file(geojson_file)
    polygon = gdf.union_all()

    lon2d, lat2d = np.meshgrid(ds["longitude"].values, ds["latitude"].values)
    inside = shapely.contains_xy(polygon, lon2d, lat2d)

    return xr.DataArray(
        inside,
        dims=("latitude", "longitude"),
        coords={"latitude": ds["latitude"], "longitude": ds["longitude"]},
    )


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
        "--geojson-file",
        type=Path,
        default=DEFAULT_GEOJSON,
        help=f"Path to the area of interest GeoJSON file (default: {DEFAULT_GEOJSON}).",
    )
    parser.add_argument(
        "--output-directory",
        type=Path,
        default=DEFAULT_FIGURES_DIR,
        help=f"Directory to save the plot to (default: {DEFAULT_FIGURES_DIR}).",
    )
    parser.add_argument(
        "--postprocessed-directory",
        type=Path,
        default=DEFAULT_POSTPROCESSED_DIR,
        help="Directory to save the aggregated timeseries CSV to "
        f"(default: {DEFAULT_POSTPROCESSED_DIR}).",
    )
    args = parser.parse_args()

    input_file = args.input_file or find_todays_forecast()
    print(f"Reading {input_file}")
    ds = xr.open_dataset(input_file)

    print(f"Subsetting to area of interest from {args.geojson_file}")
    mask = area_of_interest_mask(ds, args.geojson_file)
    n_points = int(mask.sum())
    if n_points == 0:
        raise ValueError(
            "No grid points from the currents forecast fall inside the area "
            "of interest polygon -- check that the two datasets overlap."
        )
    print(f"{n_points} grid points fall within the area of interest")

    ds_masked = ds.where(mask)
    spatial_dims = ("latitude", "longitude")

    mean_uo = ds_masked["uo"].mean(dim=spatial_dims, skipna=True)
    mean_vo = ds_masked["vo"].mean(dim=spatial_dims, skipna=True)

    speed = np.sqrt(mean_uo**2 + mean_vo**2)
    # Oceanographic convention: direction the current flows towards, measured
    # clockwise from true north.
    direction = (np.rad2deg(np.arctan2(mean_uo, mean_vo)) + 360) % 360

    times = ds["time"].values

    output_ds = xr.Dataset(
        data_vars={
            "uo": ("time", mean_uo.values),
            "vo": ("time", mean_vo.values),
            "speed": ("time", speed.values),
            "direction": ("time", direction.values),
        },
        coords={"time": times},
    )
    output_ds["uo"].attrs = {"long_name": "Mean eastward current velocity", "units": "m s-1"}
    output_ds["vo"].attrs = {"long_name": "Mean northward current velocity", "units": "m s-1"}
    output_ds["speed"].attrs = {"long_name": "Mean current speed", "units": "m s-1"}
    output_ds["direction"].attrs = {
        "long_name": "Mean current direction (towards, clockwise from true north)",
        "units": "degrees",
    }
    output_ds.attrs = {
        "description": (
            "Spatially averaged current velocity (magnitude and direction) "
            "within the area of interest defined in "
            f"{args.geojson_file.name}."
        ),
        "source_file": str(input_file),
    }

    args.postprocessed_directory.mkdir(parents=True, exist_ok=True)
    start_str = np.datetime_as_string(times[0], unit="h")
    end_str = np.datetime_as_string(times[-1], unit="h")
    csv_output_file = (
        args.postprocessed_directory
        / f"currents_conditions_area_of_interest_{start_str}_to_{end_str}.csv"
    )
    output_ds.to_dataframe().to_csv(csv_output_file, float_format="%.3f")
    print(f"Saved timeseries CSV to {csv_output_file}")

    fig, axes = plt.subplots(2, 1, figsize=(12, 8), sharex=True, constrained_layout=True)

    axes[0].plot(times, speed, color="teal")
    axes[0].set_ylabel("Current speed (m/s)")
    axes[0].set_title("Mean current speed in area of interest")

    axes[1].plot(times, direction, color="teal", marker=".", linestyle="none")
    axes[1].set_ylabel("Direction (\u00b0 towards, from N)")
    axes[1].set_ylim(0, 360)
    axes[1].set_title("Mean current direction in area of interest")
    axes[1].set_xlabel("Time")
    fig.autofmt_xdate()

    args.output_directory.mkdir(parents=True, exist_ok=True)
    output_file = (
        args.output_directory
        / f"currents_conditions_area_of_interest_{start_str}_to_{end_str}.png"
    )
    fig.savefig(output_file, dpi=150)
    print(f"Saved plot to {output_file}")


if __name__ == "__main__":
    main()
