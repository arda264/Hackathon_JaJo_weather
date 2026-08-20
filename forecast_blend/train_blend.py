"""Learn per-forecast-model blend weights against ERA5 "real" wind data.

Six weather models' archived forecasts (fetched by ``fetch_forecasts.py`` from
the Open-Meteo Historical Forecast API) are compared with ERA5 hourly 10 m wind
(u10/v10) at the same grid points inside the area of interest. The model learns
one weight per forecast source so that the weighted blend

    u_blend = sum_m w_m * u_m ,   v_blend = sum_m w_m * v_m ,
    w_m >= 0 ,  sum_m w_m = 1

is as close as possible (least squares on the wind *vector*) to ERA5. The
simplex constraint keeps the weights interpretable: w_m is literally "how much
to trust model m".

Evaluation is honest: weights are fit on the first 75% of the record
(chronological) and every reported score is from the held-out final 25%,
compared against each individual model, the equal-weight ensemble, and an
unconstrained least-squares reference.

Outputs (forecast_blend/results/):
    weights.json      learned weights + training metadata
    metrics.csv       per-source test metrics (vector RMSE, speed RMSE/MAE,
                      direction MAE, bias)
    blend_evaluation_{light,dark}.png   weights + test-RMSE comparison figure

Run from the repository root (after fetch_forecasts.py):
    python forecast_blend/train_blend.py
"""

import json
from pathlib import Path

import matplotlib
import numpy as np
import pandas as pd
from scipy.optimize import minimize

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

HERE = Path(__file__).parent
GRIB = r"C:\Users\ardac\Desktop\wind_data\ERA5hourly10m.grib"
FORECASTS = HERE / "data" / "forecasts.csv"
TRUTH_CACHE = HERE / "data" / "era5_truth.csv"
RESULTS = HERE / "results"

POINTS = [(52.0, 2.5), (52.0, 4.0), (52.5, 3.0), (53.0, 3.5)]
TRAIN_FRACTION = 0.75
MS_TO_KT = 1.0 / 0.514444

SOURCES = ["ecmwf", "gfs", "icon", "arpege", "harmonie", "ukmo"]
LONG_NAME = {
    "ecmwf": "ECMWF IFS 0.25°",
    "gfs": "NOAA GFS",
    "icon": "DWD ICON-EU",
    "arpege": "Météo-France ARPEGE",
    "harmonie": "KNMI HARMONIE-AROME",
    "ukmo": "UKMO Global 10 km",
}

DPI = 200
SCALE = DPI / 96.0

# design tokens shared with output/scripts/* (validated with the dataviz
# palette validator in both modes)
THEMES = {
    "light": dict(
        surface="#fcfcfb", primary="#0b0b0b", secondary="#52514e",
        muted="#898781", grid="#e1e0d9", axis="#c3c2b7",
        bar="#86b6ef", accent="#104281", faint="#d7d6cd",
    ),
    "dark": dict(
        surface="#1a1a19", primary="#ffffff", secondary="#c3c2b7",
        muted="#898781", grid="#2c2c2a", axis="#383835",
        bar="#3987e5", accent="#9ec5f4", faint="#3d3d3a",
    ),
}


# --- data --------------------------------------------------------------------
def load_truth():
    """ERA5 u10/v10 at the evaluation points, hourly, cached to CSV."""
    if TRUTH_CACHE.exists():
        return pd.read_csv(TRUTH_CACHE, parse_dates=["time"])

    import xarray as xr
    ds = xr.open_dataset(GRIB, engine="cfgrib", backend_kwargs={"indexpath": ""},
                         chunks={"time": 4000})
    lats = xr.DataArray([p[0] for p in POINTS], dims="point")
    lons = xr.DataArray([p[1] for p in POINTS], dims="point")
    pick = ds[["u10", "v10"]].sel(latitude=lats, longitude=lons)
    u = pick.u10.compute().values
    v = pick.v10.compute().values
    times = pd.DatetimeIndex(ds.time.values)

    frames = []
    for i, (lat, lon) in enumerate(POINTS):
        frames.append(pd.DataFrame({
            "time": times, "lat": lat, "lon": lon,
            "u_era5": u[:, i], "v_era5": v[:, i],
        }))
    truth = pd.concat(frames, ignore_index=True)
    truth.to_csv(TRUTH_CACHE, index=False)
    return truth


def load_merged():
    fc = pd.read_csv(FORECASTS, parse_dates=["time"])
    truth = load_truth()
    df = fc.merge(truth, on=["time", "lat", "lon"], how="inner")
    df = df.dropna().sort_values(["time", "lat", "lon"]).reset_index(drop=True)
    return df


# --- weight fitting ----------------------------------------------------------
def fit_simplex_weights(X, y):
    """Least squares over the probability simplex: w >= 0, sum w = 1."""
    n = X.shape[1]
    XtX, Xty = X.T @ X, X.T @ y

    def loss(w):
        return float(w @ XtX @ w - 2.0 * w @ Xty + y @ y)

    def grad(w):
        return 2.0 * (XtX @ w - Xty)

    res = minimize(
        loss, np.full(n, 1.0 / n), jac=grad, method="SLSQP",
        bounds=[(0.0, 1.0)] * n,
        constraints=[{"type": "eq", "fun": lambda w: w.sum() - 1.0,
                      "jac": lambda w: np.ones_like(w)}],
        options={"maxiter": 500, "ftol": 1e-12},
    )
    if not res.success:
        raise RuntimeError(f"weight optimisation failed: {res.message}")
    w = np.clip(res.x, 0.0, None)
    return w / w.sum()


# --- metrics -----------------------------------------------------------------
def speed(u, v):
    return np.hypot(u, v)


def direction_from(u, v):
    return (np.degrees(np.arctan2(-u, -v)) + 360.0) % 360.0


def angular_error(d1, d2):
    diff = np.abs(d1 - d2) % 360.0
    return np.minimum(diff, 360.0 - diff)


def evaluate(u_pred, v_pred, u_true, v_true):
    """Test metrics for one prediction source, in m/s and degrees."""
    vec_rmse = float(np.sqrt(np.mean((u_pred - u_true) ** 2
                                     + (v_pred - v_true) ** 2)))
    sp_pred, sp_true = speed(u_pred, v_pred), speed(u_true, v_true)
    windy = sp_true > 2.0  # direction is meaningless in near-calm air
    dir_err = angular_error(direction_from(u_pred, v_pred)[windy],
                            direction_from(u_true, v_true)[windy])
    return dict(
        vector_rmse_ms=vec_rmse,
        speed_rmse_ms=float(np.sqrt(np.mean((sp_pred - sp_true) ** 2))),
        speed_mae_ms=float(np.mean(np.abs(sp_pred - sp_true))),
        speed_bias_ms=float(np.mean(sp_pred - sp_true)),
        direction_mae_deg=float(np.mean(dir_err)),
    )


# --- figure ------------------------------------------------------------------
def make_figure(weights, metrics, split_time, n_train, n_test, mode):
    t = THEMES[mode]
    plt.rcParams.update({
        "font.family": "sans-serif",
        "font.sans-serif": ["Segoe UI", "DejaVu Sans", "Arial"],
        "figure.facecolor": t["surface"], "axes.facecolor": t["surface"],
        "savefig.facecolor": t["surface"], "text.color": t["primary"],
        "axes.labelcolor": t["secondary"], "xtick.color": t["muted"],
        "ytick.color": t["muted"], "axes.edgecolor": t["axis"],
        "axes.linewidth": 1.0 * SCALE,
        "xtick.major.size": 0, "ytick.major.size": 0,
    })

    fig, (ax_w, ax_r) = plt.subplots(1, 2, figsize=(13.5, 5.2), dpi=DPI)
    fig.subplots_adjust(left=0.16, right=0.97, top=0.80, bottom=0.155, wspace=0.42)

    # panel 1: learned weights, one bar per forecast model
    order = np.argsort(weights)[::-1]
    names = [LONG_NAME[SOURCES[i]] for i in order]
    vals = weights[order]
    y = np.arange(len(vals))[::-1]
    ax_w.barh(y, vals, height=0.62, color=t["bar"], edgecolor="none", zorder=3)
    for yi, v in zip(y, vals):
        ax_w.text(v + 0.012, yi, f"{v:.2f}", va="center", ha="left",
                  fontsize=9, color=t["secondary"])
    ax_w.set_yticks(y, names, fontsize=9)
    ax_w.set_xlim(0, max(0.5, vals.max() * 1.22))
    ax_w.xaxis.grid(True, color=t["grid"], linewidth=1.0 * SCALE)
    ax_w.set_axisbelow(True)
    ax_w.set_xlabel("learned weight", fontsize=9)
    ax_w.set_title("Learned blend weights", fontsize=10.5, fontweight="600",
                   color=t["primary"], loc="left", pad=8)
    for side in ("top", "right", "left"):
        ax_w.spines[side].set_visible(False)

    # panel 2: held-out vector RMSE, blend vs every individual model
    rows = [(LONG_NAME.get(s, s), metrics[s]["vector_rmse_ms"], s)
            for s in SOURCES]
    rows.append(("Equal-weight mean", metrics["equal"]["vector_rmse_ms"], "equal"))
    rows.append(("Learned blend", metrics["blend"]["vector_rmse_ms"], "blend"))
    rows.sort(key=lambda r: r[1])
    y = np.arange(len(rows))[::-1]
    colors = [t["accent"] if key == "blend" else t["bar"] for _, _, key in rows]
    ax_r.barh(y, [r[1] for r in rows], height=0.62, color=colors,
              edgecolor="none", zorder=3)
    for yi, (_, v, _) in zip(y, rows):
        ax_r.text(v + 0.012, yi, f"{v:.2f}", va="center", ha="left",
                  fontsize=9, color=t["secondary"])
    ax_r.set_yticks(y, [r[0] for r in rows], fontsize=9)
    ax_r.set_xlim(0, max(r[1] for r in rows) * 1.16)
    ax_r.xaxis.grid(True, color=t["grid"], linewidth=1.0 * SCALE)
    ax_r.set_axisbelow(True)
    ax_r.set_xlabel("wind-vector RMSE vs ERA5 (m/s), held-out test", fontsize=9)
    ax_r.set_title("Held-out accuracy (lower is better)", fontsize=10.5,
                   fontweight="600", color=t["primary"], loc="left", pad=8)
    for side in ("top", "right", "left"):
        ax_r.spines[side].set_visible(False)

    fig.text(0.012, 0.955, "Forecast-model blending against ERA5",
             fontsize=15, fontweight="600", color=t["primary"])
    fig.text(0.012, 0.895,
             "Non-negative weights (summing to 1) fit on hourly 10 m wind vectors, "
             f"{len(POINTS)} North Sea points · train to {split_time:%Y-%m-%d} "
             f"({n_train:,} samples), test after ({n_test:,} samples)",
             fontsize=9.5, color=t["secondary"])
    fig.text(0.012, 0.022,
             "Truth: ERA5 hourly u10/v10 · Forecasts: Open-Meteo Historical "
             "Forecast API (archived model runs) · highlighted bar: learned blend",
             fontsize=7.5, color=t["muted"])

    RESULTS.mkdir(parents=True, exist_ok=True)
    fig.savefig(RESULTS / f"blend_evaluation_{mode}.png", dpi=DPI)
    plt.close(fig)


# --- main --------------------------------------------------------------------
def main():
    df = load_merged()
    print(f"merged dataset: {len(df):,} samples "
          f"({df.time.min()} .. {df.time.max()}, {len(POINTS)} points)")

    # chronological split so the test set is strictly in the future
    cut = df.time.quantile(TRAIN_FRACTION)
    train, test = df[df.time <= cut], df[df.time > cut]

    ucols = [f"u_{s}" for s in SOURCES]
    vcols = [f"v_{s}" for s in SOURCES]

    # stack u and v rows: one weight vector must serve both components
    X_train = np.vstack([train[ucols].to_numpy(), train[vcols].to_numpy()])
    y_train = np.concatenate([train["u_era5"].to_numpy(),
                              train["v_era5"].to_numpy()])
    w = fit_simplex_weights(X_train, y_train)

    # unconstrained least squares, as a reference only
    w_ols, *_ = np.linalg.lstsq(X_train, y_train, rcond=None)

    Xu, Xv = test[ucols].to_numpy(), test[vcols].to_numpy()
    u_true, v_true = test["u_era5"].to_numpy(), test["v_era5"].to_numpy()

    metrics = {}
    for i, s in enumerate(SOURCES):
        metrics[s] = evaluate(Xu[:, i], Xv[:, i], u_true, v_true)
    eq = np.full(len(SOURCES), 1.0 / len(SOURCES))
    metrics["equal"] = evaluate(Xu @ eq, Xv @ eq, u_true, v_true)
    metrics["blend"] = evaluate(Xu @ w, Xv @ w, u_true, v_true)
    metrics["ols_reference"] = evaluate(Xu @ w_ols, Xv @ w_ols, u_true, v_true)

    RESULTS.mkdir(parents=True, exist_ok=True)
    with open(RESULTS / "weights.json", "w") as f:
        json.dump({
            "weights": {s: round(float(wi), 6) for s, wi in zip(SOURCES, w)},
            "sources": {s: LONG_NAME[s] for s in SOURCES},
            "constraint": "w >= 0, sum(w) = 1 (least squares on u,v vectors)",
            "truth": "ERA5 hourly 10 m u/v",
            "points": POINTS,
            "train_until": str(cut),
            "n_train_hours": int(len(train)),
            "n_test_hours": int(len(test)),
            "ols_reference_weights": {s: round(float(wi), 6)
                                      for s, wi in zip(SOURCES, w_ols)},
        }, f, indent=2)

    mdf = pd.DataFrame(metrics).T
    mdf.index.name = "source"
    mdf.round(4).to_csv(RESULTS / "metrics.csv")

    for mode in ("light", "dark"):
        make_figure(w, metrics, cut, len(train), len(test), mode)

    print(f"\nlearned weights (train <= {cut:%Y-%m-%d %H:%M}):")
    for s, wi in sorted(zip(SOURCES, w), key=lambda p: -p[1]):
        print(f"  {LONG_NAME[s]:22s} {wi:6.3f}")

    print("\nheld-out test metrics (vs ERA5):")
    show = mdf[["vector_rmse_ms", "speed_rmse_ms", "speed_mae_ms",
                "speed_bias_ms", "direction_mae_deg"]].round(3)
    print(show.sort_values("vector_rmse_ms").to_string())

    best_single = min(SOURCES, key=lambda s: metrics[s]["vector_rmse_ms"])
    gain = (1 - metrics["blend"]["vector_rmse_ms"]
            / metrics[best_single]["vector_rmse_ms"]) * 100
    print(f"\nblend vs best single model ({LONG_NAME[best_single]}): "
          f"{gain:+.1f}% vector-RMSE improvement on held-out data")
    print(f"\nwrote {RESULTS}/weights.json, metrics.csv, "
          f"blend_evaluation_light.png, blend_evaluation_dark.png")


if __name__ == "__main__":
    main()
