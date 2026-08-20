"""
Template: animated GIF of hydro/wave/wind hindcast conditions for a single day.

Reuses the same 3-panel figure layout as the original user example notebook
(example_script_from_user/plot_hydro_and_wave_data.ipynb):
  - Panel 1: current speed (colour) + current direction (quiver)
  - Panel 2: wind speed (colour) + wind direction (quiver)
  - Panel 3: significant wave height (colour) + wave direction (quiver)

One frame per available hydro timestep (30-min) for the target day; the
nearest hourly wave timestep is used per frame.

Colour scale convention: vmin=0, vmax = 99th percentile of that variable's
values over the whole animated day (kept fixed across all frames to avoid
flicker/rescaling between frames).

To reuse for a different day: change the DAY constant below (the MONTH,
file lookups, and data selection all derive from it automatically).
To change animation speed: adjust FPS_DURATION_MS (ms per frame).

Run with:
  pixi run --environment metocean python output/scripts/animate_day_conditions.py
"""
import os
import glob
import numpy as np
import xarray as xr
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from PIL import Image
import io

HYDRO_DIR = "/p/11212774-004-2d-dcsm-fm/dflowfm2d-noordzee_0_5nm-j25_6-v1a/computations/hindcast_for_hackathon/hydro_regrid"
WAVE_DIR = "/p/11212774-004-2d-dcsm-fm/dflowfm2d-noordzee_0_5nm-j25_6-v1a/computations/hindcast_for_hackathon/waves_regrid"

OUT_FIGURES = "output/figures"
os.makedirs(OUT_FIGURES, exist_ok=True)

DAY = "2009-12-02"  # <-- change this to animate a different day (YYYY-MM-DD)
MONTH = DAY[:7]

LOWESTOFT = [1.75, 52.48]
IJMUIDEN = [4.55, 52.46]

SKIP = 5  # quiver decimation
FPS_DURATION_MS = 400  # ms per frame in the gif


def find_file(pattern):
    matches = [f for f in glob.glob(pattern) if not f.endswith(".aux.xml")]
    assert matches, f"No file found for pattern {pattern}"
    return matches[0]


def main():
    uc_file = find_file(os.path.join(HYDRO_DIR, f"dcsm_uc_{MONTH}_30min.nc"))
    windx_file = find_file(os.path.join(HYDRO_DIR, f"dcsm_windx_{MONTH}_*.nc"))
    windy_file = find_file(os.path.join(HYDRO_DIR, f"dcsm_windy_{MONTH}_*.nc"))
    wave_file = find_file(os.path.join(WAVE_DIR, f"waves_{MONTH}.nc"))

    ds_uc = xr.open_dataset(uc_file)
    ds_windx = xr.open_dataset(windx_file)
    ds_windy = xr.open_dataset(windy_file)
    ds = xr.merge([ds_uc, ds_windx[["windx"]], ds_windy[["windy"]]])
    ds_wave = xr.open_dataset(wave_file)

    ds = ds.sel(time=DAY)
    ds_wave_day = ds_wave.sel(time=DAY)

    print(f"Hydro timesteps for {DAY}: {ds.time.size}")
    print(f"Wave timesteps for {DAY}: {ds_wave_day.time.size}")

    # ---------------------------------------------------------------------
    # Derived quantities (following example_script_from_user notebook)
    # ---------------------------------------------------------------------
    ds["umag"] = np.sqrt(ds["ucx"] ** 2 + ds["ucy"] ** 2)
    ds["windmag"] = np.sqrt(ds["windx"] ** 2 + ds["windy"] ** 2)

    # wave propagation vector from theta0 (direction FROM, nautical convention)
    ds_wave_day = ds_wave_day.copy()
    ds_wave_day["dirx"] = -np.sin(np.radians(ds_wave_day["theta0"]))
    ds_wave_day["diry"] = -np.cos(np.radians(ds_wave_day["theta0"]))

    # ---------------------------------------------------------------------
    # Fixed colour scales: vmin=0, vmax = P99 over the whole day
    # ---------------------------------------------------------------------
    umag_vmax = float(np.nanpercentile(ds["umag"].values, 99))
    windmag_vmax = float(np.nanpercentile(ds["windmag"].values, 99))
    hs_vmax = float(np.nanpercentile(ds_wave_day["hs"].values, 99))
    print(f"Colour scale vmax: umag={umag_vmax:.2f} m/s, "
          f"windmag={windmag_vmax:.2f} m/s, hs={hs_vmax:.2f} m")

    ds_q_full = ds.isel(x=slice(None, None, SKIP), y=slice(None, None, SKIP))
    ds_wave_q_full = ds_wave_day.isel(x=slice(None, None, SKIP), y=slice(None, None, SKIP))

    # ---------------------------------------------------------------------
    # Render one frame per hydro timestep
    # ---------------------------------------------------------------------
    frames = []
    times = ds.time.values

    for t in times:
        t_wave = ds_wave_day.sel(time=t, method="nearest").time.values

        ds_t = ds.sel(time=t)
        ds_q_t = ds_q_full.sel(time=t)
        ds_wave_t = ds_wave_day.sel(time=t_wave)
        ds_wave_q_t = ds_wave_q_full.sel(time=t_wave)

        fig, axs = plt.subplots(figsize=(10, 10), nrows=3, ncols=1,
                                 constrained_layout=True)

        ds_t["umag"].plot(ax=axs[0], cmap="turbo", vmin=0, vmax=umag_vmax)
        ds_q_t.plot.quiver(ax=axs[0], x="x", y="y", u="ucx", v="ucy",
                            scale=50, add_guide=False,
                            color="k", width=0.001, headwidth=4, headlength=5)
        axs[0].set_title("Current magnitude + direction")

        ds_t["windmag"].plot(ax=axs[1], cmap="turbo", vmin=0, vmax=windmag_vmax)
        ds_q_t.plot.quiver(ax=axs[1], x="x", y="y", u="windx", v="windy",
                            scale=1000, add_guide=False,
                            color="k", width=0.001, headwidth=4, headlength=5)
        axs[1].set_title("Wind magnitude + direction")

        ds_wave_t["hs"].plot(ax=axs[2], cmap="turbo", vmin=0, vmax=hs_vmax)
        ds_wave_q_t.plot.quiver(ax=axs[2], x="x", y="y", u="dirx", v="diry",
                                scale=50, add_guide=False,
                                color="k", width=0.001, headwidth=4, headlength=5)
        axs[2].set_title("Significant wave height + direction")

        for ax in axs:
            ax.scatter(*LOWESTOFT, color="k", marker="x", s=50)
            ax.scatter(*IJMUIDEN, color="k", marker="x", s=50)
            ax.text(LOWESTOFT[0], LOWESTOFT[1] - 0.05, "Lowestoft", color="k",
                    fontsize=10, ha="center", va="top")
            ax.text(IJMUIDEN[0], IJMUIDEN[1] - 0.05, "IJmuiden", color="k",
                    fontsize=10, ha="center", va="top")

        ts = np.datetime_as_string(t, unit="m").replace("T", " ")
        fig.suptitle(f"North Sea hindcast, {ts}")

        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=110)
        plt.close(fig)
        buf.seek(0)
        frames.append(Image.open(buf).convert("RGB"))
        print(f"  rendered frame {ts}")

    gif_path = os.path.join(OUT_FIGURES, f"North_Sea_hindcast_animation_{DAY}.gif")
    frames[0].save(
        gif_path, save_all=True, append_images=frames[1:],
        duration=FPS_DURATION_MS, loop=0,
    )
    print(f"Saved: {gif_path} ({len(frames)} frames)")


if __name__ == "__main__":
    main()
