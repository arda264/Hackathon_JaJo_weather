"""Check wave conditions within the area of interest for the sample forecast.

Reads today's sample wave forecast (as produced by
scripts/get_sample_wave_forecast.py) from sample_forecast_data/, subsets it
to the polygon defined in geometry/area_of_interest.geojson, and computes the
spatial mean of every wave variable within that area for each timestep.

Produces a 4-row timeseries plot (wave height / period / mean direction /
steepness), with swell (VHM0_SW1, VTM01_SW1, VMDR_SW1) drawn in blue and
wind-sea (VHM0_WW, VTM01_WW, VMDR_WW) drawn in red. Also computes wave
steepness (Hs / (g * Tm01^2 / (2*pi))) for both wind-sea and swell, and
saves the full aggregated timeseries (heights, periods, directions,
steepness) as a NetCDF file to sample_forecast_data/preprocessed/.

Run with the `metocean` pixi environment, e.g.:
    pixi run -e metocean python scripts/check_wave_conditions_area_of_interest.py
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
DEFAULT_PREPROCESSED_DIR = ROOT_DIR / "sample_forecast_data" / "preprocessed"
DEFAULT_GEOJSON = ROOT_DIR / "geometry" / "area_of_interest.geojson"

WIND_SEA = {"height": "VHM0_WW", "period": "VTM01_WW", "direction": "VMDR_WW"}
SWELL = {"height": "VHM0_SW1", "period": "VTM01_SW1", "direction": "VMDR_SW1"}


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


def circular_mean_direction(direction_deg: xr.DataArray, dims) -> xr.DataArray:
    """Spatial mean of a "direction from" field (degrees), using circular averaging."""
    theta = np.deg2rad(direction_deg)
    mean_sin = np.sin(theta).mean(dim=dims)
    mean_cos = np.cos(theta).mean(dim=dims)
    mean_theta = np.arctan2(mean_sin, mean_cos)
    return (np.rad2deg(mean_theta) + 360) % 360


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
        "--preprocessed-directory",
        type=Path,
        default=DEFAULT_PREPROCESSED_DIR,
        help="Directory to save the aggregated timeseries NetCDF to "
        f"(default: {DEFAULT_PREPROCESSED_DIR}).",
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
            "No grid points from the wave forecast fall inside the area of "
            "interest polygon -- check that the two datasets overlap."
        )
    print(f"{n_points} grid points fall within the area of interest")

    ds_masked = ds.where(mask)
    spatial_dims = ("latitude", "longitude")

    mean_vars = {}
    for group in (WIND_SEA, SWELL):
        for key in ("height", "period"):
            var = group[key]
            mean_vars[var] = ds_masked[var].mean(dim=spatial_dims, skipna=True)
        direction_var = group["direction"]
        mean_vars[direction_var] = circular_mean_direction(
            ds_masked[direction_var], dims=spatial_dims
        )

    times = ds["time"].values

    g = 9.81
    steepness_vars = {}
    for group, name in ((WIND_SEA, "wind_sea"), (SWELL, "swell")):
        hs = mean_vars[group["height"]]
        tm01 = mean_vars[group["period"]]
        steepness = hs / (g * tm01**2 / (2 * np.pi))
        steepness_vars[f"steepness_{name}"] = steepness

    output_ds = xr.Dataset(
        data_vars={
            "VHM0_WW": ("time", mean_vars[WIND_SEA["height"]].values),
            "VTM01_WW": ("time", mean_vars[WIND_SEA["period"]].values),
            "VMDR_WW": ("time", mean_vars[WIND_SEA["direction"]].values),
            "VHM0_SW1": ("time", mean_vars[SWELL["height"]].values),
            "VTM01_SW1": ("time", mean_vars[SWELL["period"]].values),
            "VMDR_SW1": ("time", mean_vars[SWELL["direction"]].values),
            "steepness_wind_sea": ("time", steepness_vars["steepness_wind_sea"].values),
            "steepness_swell": ("time", steepness_vars["steepness_swell"].values),
        },
        coords={"time": times},
    )
    output_ds["VHM0_WW"].attrs = {"long_name": "Wind-sea significant wave height", "units": "m"}
    output_ds["VTM01_WW"].attrs = {"long_name": "Wind-sea mean wave period", "units": "s"}
    output_ds["VMDR_WW"].attrs = {"long_name": "Wind-sea mean wave direction (from, circular mean)", "units": "degrees"}
    output_ds["VHM0_SW1"].attrs = {"long_name": "Swell significant wave height", "units": "m"}
    output_ds["VTM01_SW1"].attrs = {"long_name": "Swell mean wave period", "units": "s"}
    output_ds["VMDR_SW1"].attrs = {"long_name": "Swell mean wave direction (from, circular mean)", "units": "degrees"}
    output_ds["steepness_wind_sea"].attrs = {
        "long_name": "Wind-sea wave steepness (Hs / (g * Tm01^2 / (2 pi)))",
        "units": "dimensionless",
    }
    output_ds["steepness_swell"].attrs = {
        "long_name": "Swell wave steepness (Hs / (g * Tm01^2 / (2 pi)))",
        "units": "dimensionless",
    }
    output_ds.attrs = {
        "description": (
            "Spatially averaged (arithmetic mean for height/period, circular mean "
            "for direction) wave conditions within the area of interest defined in "
            f"{args.geojson_file.name}."
        ),
        "source_file": str(input_file),
    }

    args.preprocessed_directory.mkdir(parents=True, exist_ok=True)
    start_str = np.datetime_as_string(times[0], unit="h")
    end_str = np.datetime_as_string(times[-1], unit="h")
    nc_output_file = (
        args.preprocessed_directory
        / f"wave_conditions_area_of_interest_{start_str}_to_{end_str}.nc"
    )
    output_ds.to_netcdf(nc_output_file)
    print(f"Saved timeseries NetCDF to {nc_output_file}")

    fig, axes = plt.subplots(4, 1, figsize=(12, 12), sharex=True, constrained_layout=True)

    axes[0].plot(times, mean_vars[SWELL["height"]], color="blue", label="Swell")
    axes[0].plot(times, mean_vars[WIND_SEA["height"]], color="red", label="Wind-sea")
    axes[0].set_ylabel("Significant wave height (m)")
    axes[0].set_title("Mean significant wave height in area of interest")
    axes[0].legend()

    axes[1].plot(times, mean_vars[SWELL["period"]], color="blue", label="Swell")
    axes[1].plot(times, mean_vars[WIND_SEA["period"]], color="red", label="Wind-sea")
    axes[1].set_ylabel("Mean wave period (s)")
    axes[1].set_title("Mean wave period in area of interest")
    axes[1].legend()

    axes[2].plot(
        times, mean_vars[SWELL["direction"]], color="blue", marker=".", linestyle="none",
        label="Swell",
    )
    axes[2].plot(
        times, mean_vars[WIND_SEA["direction"]], color="red", marker=".", linestyle="none",
        label="Wind-sea",
    )
    axes[2].set_ylabel("Mean direction (\u00b0 from)")
    axes[2].set_ylim(0, 360)
    axes[2].set_title("Mean wave direction in area of interest")
    axes[2].legend()

    axes[3].plot(times, steepness_vars["steepness_swell"], color="blue", label="Swell")
    axes[3].plot(times, steepness_vars["steepness_wind_sea"], color="red", label="Wind-sea")
    axes[3].set_ylabel("Wave steepness")
    axes[3].set_title("Mean wave steepness in area of interest")
    axes[3].set_xlabel("Time")
    axes[3].legend()
    fig.autofmt_xdate()

    args.output_directory.mkdir(parents=True, exist_ok=True)
    start_str = np.datetime_as_string(times[0], unit="h")
    end_str = np.datetime_as_string(times[-1], unit="h")
    output_file = (
        args.output_directory
        / f"wave_conditions_area_of_interest_{start_str}_to_{end_str}.png"
    )
    fig.savefig(output_file, dpi=150)
    print(f"Saved plot to {output_file}")


if __name__ == "__main__":
    main()
