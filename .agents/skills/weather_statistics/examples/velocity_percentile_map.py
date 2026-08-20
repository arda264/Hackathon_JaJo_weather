"""
Spatial map of a percentile of a variable (e.g. current speed magnitude,
wind speed magnitude, wave height) from rasterized DCSM-FM / SWAN monthly
NetCDF output, for a given year.

Works for:
- Vector magnitude variables (e.g. current ucx/ucy, wind windx/windy):
  set U_VAR and V_VAR, magnitude = sqrt(u^2 + v^2).
- Scalar variables (e.g. wave height hs): set U_VAR only and leave V_VAR = None.

Colorbar convention: always cap the colorbar upper limit (vmax) at the 99th
percentile of the values shown in the plot (vmin=0), regardless of which
percentile is being computed/plotted. This avoids a few extreme outliers
from washing out the spatial contrast.

Run with:
  pixi run --environment metocean python output/scripts/velocity_percentile_map.py
"""
import os
import glob
import numpy as np
import xarray as xr
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
DATA_DIR   = "/p/11212774-004-2d-dcsm-fm/dflowfm2d-noordzee_0_5nm-j25_6-v1a/computations/hindcast_for_hackathon/hydro_regrid"
FILE_VAR   = "uc"          # variable tag used in the file name, e.g. dcsm_uc_2025-01_30min.nc
FILE_GLOB  = f"dcsm_{FILE_VAR}_{{year}}-{{month:02d}}_30min.nc"

U_VAR      = "ucx"         # vector x-component (or scalar variable name if V_VAR is None)
V_VAR      = "ucy"         # vector y-component; set to None for scalar variables

YEAR       = 2025
PERCENTILE = 95            # percentile to compute (0-100)

OUT_FIGURES = "output/figures"
OUT_RESULTS = "output/results"
os.makedirs(OUT_FIGURES, exist_ok=True)
os.makedirs(OUT_RESULTS, exist_ok=True)


def month_files(year):
    files = {}
    for month in range(1, 13):
        pattern = os.path.join(DATA_DIR, FILE_GLOB.format(year=year, month=month))
        matches = [f for f in glob.glob(pattern) if not f.endswith(".aux.xml")]
        if matches:
            files[month] = matches[0]
    return files


def main():
    files = month_files(YEAR)
    months = sorted(files)
    print(f"Found {len(months)} months of {FILE_VAR} data for {YEAR}: {months}")
    assert months, f"No files found for pattern {FILE_GLOB} in {DATA_DIR}"

    chunks = []
    lon = lat = None

    for m in months:
        ds = xr.open_dataset(files[m])
        if lon is None:
            lon = ds["x"].values
            lat = ds["y"].values

        if V_VAR is not None:
            u = ds[U_VAR].values
            v = ds[V_VAR].values
            values = np.sqrt(u ** 2 + v ** 2)  # magnitude (time, y, x)
        else:
            values = ds[U_VAR].values  # scalar (time, y, x)

        chunks.append(values)
        ds.close()
        print(f"  processed month {m}: {values.shape[0]} timesteps")

    values_all = np.concatenate(chunks, axis=0)  # (time_total, y, x)
    print(f"Total timesteps: {values_all.shape[0]}")

    pctl_field = np.nanpercentile(values_all, PERCENTILE, axis=0)

    # ---------------------------------------------------------------------
    # Save result
    # ---------------------------------------------------------------------
    var_label = f"{U_VAR}_{V_VAR}_magnitude" if V_VAR is not None else U_VAR
    da = xr.DataArray(
        pctl_field, coords={"y": lat, "x": lon}, dims=["y", "x"],
        name=f"p{PERCENTILE}_{var_label}",
        attrs={
            "long_name": f"{PERCENTILE}th percentile of {var_label}",
            "year": YEAR,
            "source": f"percentile({PERCENTILE}) over {YEAR}, files: {FILE_GLOB}",
        },
    )
    nc_path = os.path.join(OUT_RESULTS, f"p{PERCENTILE}_{var_label}_{YEAR}.nc")
    da.to_netcdf(nc_path)
    print(f"Saved: {nc_path}")

    # ---------------------------------------------------------------------
    # Plot — colorbar upper limit is ALWAYS the 99th percentile of the
    # plotted field (not necessarily the same as PERCENTILE above), and
    # vmin is fixed at 0. This is a fixed convention for all map plots.
    # ---------------------------------------------------------------------
    vmax = np.nanpercentile(pctl_field, 99)
    fig, ax = plt.subplots(figsize=(8, 7))
    pcm = ax.pcolormesh(lon, lat, pctl_field, shading="auto", cmap="viridis",
                         vmin=0, vmax=vmax)
    fig.colorbar(pcm, ax=ax, label=f"P{PERCENTILE} {var_label}")
    ax.set_xlabel("Longitude (°E)")
    ax.set_ylabel("Latitude (°N)")
    ax.set_title(f"{PERCENTILE}th percentile of {var_label} - DCSM-FM 0.5nm 2D\nYear {YEAR}")
    ax.set_aspect(1.6)
    fig.tight_layout()
    fig_path = os.path.join(OUT_FIGURES, f"p{PERCENTILE}_{var_label}_{YEAR}.png")
    fig.savefig(fig_path, dpi=150)
    plt.close(fig)
    print(f"Saved: {fig_path}")


if __name__ == "__main__":
    main()
