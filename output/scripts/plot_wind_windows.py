"""Render PNG figures for the sailing-wind-window analysis.

Reads output/results/wind_window_days_by_month.csv (written by wind_window_days.py)
and renders three figures, each in a light and a dark variant:

  1. wind_window_heatmap    year x month grid of qualifying days, one panel per corridor
  2. wind_window_seasonality mean days per month across 2021-2025
  3. wind_window_annual      days per year, full years only

Encoding notes
  The three corridors are nested (50% inside 75% inside 100%), so they are an
  ordered scale, not nominal identity -> single-hue ordinal blue ramp, widest
  corridor lightest. Validated with scripts/validate_palette.js --ordinal in
  both modes.
"""

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.colors import LinearSegmentedColormap
from matplotlib.path import Path
from matplotlib.patches import PathPatch

RESULTS = "output/results/wind_window_days_by_month.csv"
FIGDIR = "output/figures"
DPI = 200
SCALE = DPI / 96.0  # CSS px -> device px, so the 24px/4px/2px specs hold visually

PRIMARY = "days_all_cells_6h"  # definition C - every cell in the corridor at once

REGIONS = ["100%", "75%", "50%"]
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
FULL_YEARS = [2021, 2022, 2023, 2024, 2025]

CRITERION = "18–30 kt from 205–235° or 305–335°, ≥6 consecutive hours, every cell at once"
SOURCE = ("ERA5 hourly 10 m wind (u10/v10), 0.25° grid at 52.5°N · criterion met simultaneously "
          "by every grid cell in the corridor · 2021-01-01 to 2026-08-14")

# --- design tokens (references/palette.md) -----------------------------------
THEMES = {
    "light": dict(
        surface="#fcfcfb", plane="#f9f9f7", primary="#0b0b0b", secondary="#52514e",
        muted="#898781", grid="#e1e0d9", axis="#c3c2b7",
        ordinal=["#86b6ef", "#2a78d6", "#104281"],  # 100%, 75%, 50%
        seq=["#cde2fb", "#b7d3f6", "#9ec5f4", "#86b6ef", "#6da7ec", "#5598e7", "#3987e5",
             "#2a78d6", "#256abf", "#1c5cab", "#184f95", "#104281", "#0d366b"],
    ),
    "dark": dict(
        surface="#1a1a19", plane="#0d0d0d", primary="#ffffff", secondary="#c3c2b7",
        muted="#898781", grid="#2c2c2a", axis="#383835",
        ordinal=["#9ec5f4", "#3987e5", "#184f95"],
        # dark surface: low values recede into the surface, high values brighten
        seq=["#0d366b", "#104281", "#184f95", "#1c5cab", "#256abf", "#2a78d6", "#3987e5",
             "#5598e7", "#6da7ec", "#86b6ef", "#9ec5f4", "#b7d3f6", "#cde2fb"],
    ),
}


def style(t):
    plt.rcParams.update({
        "font.family": "sans-serif",
        "font.sans-serif": ["Segoe UI", "DejaVu Sans", "Arial"],
        "figure.facecolor": t["surface"],
        "axes.facecolor": t["surface"],
        "savefig.facecolor": t["surface"],
        "text.color": t["primary"],
        "axes.labelcolor": t["secondary"],
        "xtick.color": t["muted"],
        "ytick.color": t["muted"],
        "axes.edgecolor": t["axis"],
        "axes.linewidth": 1.0 * SCALE,
        "xtick.major.size": 0,
        "ytick.major.size": 0,
    })


def relative_luminance(hex_color):
    r, g, b = (int(hex_color[i:i + 2], 16) / 255 for i in (1, 3, 5))
    f = lambda c: c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)


def px_per_data(ax):
    """Device px per data unit on each axis (call after a canvas draw)."""
    bb = ax.get_window_extent()
    (x0, x1), (y0, y1) = ax.get_xlim(), ax.get_ylim()
    return bb.width / (x1 - x0), bb.height / (y1 - y0)


def rounded_column(ax, x, w, h, rx, ry, color, zorder=3):
    """Column with a 4px rounded cap, square where it meets the baseline."""
    if h <= 0:
        return
    rx, ry = min(rx, w / 2), min(ry, h)
    verts = [(x, 0), (x, h - ry), (x, h), (x + rx, h), (x + w - rx, h),
             (x + w, h), (x + w, h - ry), (x + w, 0), (x, 0)]
    codes = [Path.MOVETO, Path.LINETO, Path.CURVE3, Path.CURVE3, Path.LINETO,
             Path.CURVE3, Path.CURVE3, Path.LINETO, Path.CLOSEPOLY]
    ax.add_patch(PathPatch(Path(verts, codes), facecolor=color, edgecolor="none", zorder=zorder))


def from_top(fig, inches):
    """Figure-fraction y for a distance measured in inches from the top edge.

    Header spacing is kept in absolute units so the title/subtitle/legend rhythm
    is identical across figures of different heights.
    """
    return 1.0 - inches / fig.get_figheight()


def titles(fig, t, title, subtitle):
    fig.text(0.012, from_top(fig, 0.30), title, ha="left", va="center",
             fontsize=15, fontweight="600", color=t["primary"])
    fig.text(0.012, from_top(fig, 0.62), subtitle, ha="left", va="center",
             fontsize=9.5, color=t["secondary"])


def footer(fig, t, extra=""):
    fig.text(0.012, 0.14 / fig.get_figheight(), (SOURCE + extra), ha="left", va="center",
             fontsize=7.5, color=t["muted"])


def legend_row(fig, t):
    """Ordinal key: swatch + label, text in ink tokens (never the series colour)."""
    y = from_top(fig, 1.06)
    h = 0.018 * 5.6 / fig.get_figheight()  # keep the swatch square-ish at any height
    x = 0.012
    fig.text(x, y, "Corridor width", fontsize=8.5, color=t["muted"], va="center")
    x += 0.088
    for label, color in zip(REGIONS, t["ordinal"]):
        fig.patches.append(plt.Rectangle((x, y - h / 2), 0.016, h, transform=fig.transFigure,
                                         facecolor=color, edgecolor="none", zorder=5))
        fig.text(x + 0.021, y, label, fontsize=8.5, color=t["secondary"], va="center")
        x += 0.075


def grouped_geometry(ax, span, n):
    """Bar width, gap and group offset for `n` bars centred on each tick.

    Caps the bar at 24px, then packs the group with a 2px surface gap and centres
    it — so capping never opens a hole inside the group.
    """
    ppx, ppy = px_per_data(ax)
    gap = 2 * SCALE / ppx
    w = min((span - (n - 1) * gap) / n, 24 * SCALE / ppx)
    total = n * w + (n - 1) * gap
    return w, gap, total, (4 * SCALE / ppx, 4 * SCALE / ppy)


# --- figure 1: heatmap -------------------------------------------------------
def fig_heatmap(df, mode):
    t = THEMES[mode]
    style(t)
    cmap = LinearSegmentedColormap.from_list("blue_seq", t["seq"])
    cmap.set_bad(t["surface"])

    years = sorted(df.year.unique())
    vmax = df[PRIMARY].max()

    # square cells + 6 rows x 12 cols fixes the axes height, so size the figure to
    # it rather than leaving a band of dead space above and below the panels
    fig_w, left, right, wspace = 15.5, 0.045, 0.925, 0.13
    panel_w = (right - left) * fig_w / (3 + 2 * wspace)
    axes_h = panel_w * len(years) / 12
    fig_h = 1.02 + 0.28 + axes_h + 0.30 + 0.30  # header, panel title, plot, ticks, footer

    fig, axes = plt.subplots(1, 3, figsize=(fig_w, fig_h), dpi=DPI)
    fig.subplots_adjust(left=left, right=right, wspace=wspace,
                        top=1 - (1.02 + 0.28) / fig_h, bottom=0.60 / fig_h)

    for ax, region in zip(axes, REGIONS):
        sub = df[df.region == region]
        grid = np.full((len(years), 12), np.nan)
        for _, r in sub.iterrows():
            grid[years.index(r.year), r.month - 1] = r[PRIMARY]
        masked = np.ma.masked_invalid(grid)

        mesh = ax.pcolormesh(np.arange(13), np.arange(len(years) + 1), masked,
                             cmap=cmap, vmin=0, vmax=vmax,
                             edgecolors=t["surface"], linewidth=2 * SCALE)
        ax.invert_yaxis()
        ax.set_aspect("equal")
        ax.set_xticks(np.arange(12) + 0.5, MONTHS, fontsize=8)
        ax.set_yticks(np.arange(len(years)) + 0.5, years, fontsize=8.5)
        ax.tick_params(length=0)
        for s in ax.spines.values():
            s.set_visible(False)
        ax.set_title(f"{region} corridor", fontsize=10.5, fontweight="600",
                     color=t["primary"], pad=8)

        # values in-cell: this panel doubles as the table view
        for iy in range(len(years)):
            for ix in range(12):
                v = grid[iy, ix]
                if np.isnan(v):
                    continue
                fill = cmap(v / vmax if vmax else 0)
                ink = "#ffffff" if relative_luminance(
                    "#%02x%02x%02x" % tuple(int(c * 255) for c in fill[:3])) < 0.42 else "#0b0b0b"
                ax.text(ix + 0.5, iy + 0.5, f"{int(v)}", ha="center", va="center",
                        fontsize=7.6, color=ink)

    pos = axes[-1].get_position()  # match the colourbar to the panel height
    cax = fig.add_axes([0.938, pos.y0, 0.008, pos.height])
    cb = fig.colorbar(mesh, cax=cax)
    cb.outline.set_visible(False)
    cb.ax.tick_params(length=0, labelsize=8, colors=t["muted"])
    cb.set_label("days per month", fontsize=8.5, color=t["secondary"])

    titles(fig, t, "Sailing wind windows by month, 2021–2026",
           f"Days with {CRITERION}. Blank cells = beyond the record.")
    footer(fig, t)
    fig.savefig(f"{FIGDIR}/wind_window_heatmap_{mode}.png", dpi=DPI)
    plt.close(fig)


# --- figure 2: seasonality ---------------------------------------------------
def fig_seasonality(df, mode):
    t = THEMES[mode]
    style(t)
    clim = (df[df.year.isin(FULL_YEARS)]
            .groupby(["region", "month"])[PRIMARY].mean().unstack())

    fig, ax = plt.subplots(figsize=(11, 5.6), dpi=DPI)
    fig.subplots_adjust(left=0.07, right=0.985, top=0.735, bottom=0.145)

    ymax = float(clim.to_numpy().max())
    top = np.ceil(ymax) + 1.0  # headroom for the peak annotation
    ax.set_xlim(-0.5, 11.5)
    ax.set_ylim(0, top)
    ax.set_yticks(np.arange(0, top, 1.0 if top <= 6 else 2.0))
    ax.set_xticks(range(12), MONTHS, fontsize=9.5)
    ax.tick_params(length=0, labelsize=9)
    ax.set_ylabel("mean days per month", fontsize=9.5, color=t["secondary"], labelpad=8)
    ax.yaxis.grid(True, color=t["grid"], linewidth=1.0 * SCALE, zorder=0)
    ax.set_axisbelow(True)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(t["axis"])

    fig.canvas.draw()
    w, gap, total, (rx, ry) = grouped_geometry(ax, 0.74, len(REGIONS))

    for i, region in enumerate(REGIONS):
        for m in range(1, 13):
            x = (m - 1) - total / 2 + i * (w + gap)
            rounded_column(ax, x, w, clim.loc[region, m], rx, ry, t["ordinal"][i])

    peak_m, trough_m = int(clim.loc["50%"].idxmax()), int(clim.loc["50%"].idxmin())
    for m, word, ytext in ((peak_m, "peak", top - 0.35),
                           (trough_m, "trough", clim.loc["50%", trough_m] + 1.35)):
        ax.annotate(f"{word} {MONTHS[m - 1]}  ~{clim.loc['50%', m]:.1f} d",
                    xy=(m - 1, clim.loc["50%", m]), xytext=(m - 1, ytext),
                    ha="center", fontsize=8.5, color=t["secondary"],
                    arrowprops=dict(arrowstyle="-", color=t["axis"], lw=1.0 * SCALE, shrinkB=5))

    titles(fig, t, "Corridor width dominates, and windows cluster in autumn–winter",
           f"Mean days per month over the five full years, 2021–2025. {CRITERION}.")
    legend_row(fig, t)
    footer(fig, t, " · 2026 excluded (partial year)")
    fig.savefig(f"{FIGDIR}/wind_window_seasonality_{mode}.png", dpi=DPI)
    plt.close(fig)


# --- figure 3: annual totals -------------------------------------------------
def fig_annual(df, mode):
    t = THEMES[mode]
    style(t)
    ann = (df[df.year.isin(FULL_YEARS)]
           .groupby(["region", "year"])[PRIMARY].sum().unstack())

    fig, ax = plt.subplots(figsize=(9.5, 5.0), dpi=DPI)
    fig.subplots_adjust(left=0.075, right=0.985, top=1 - 1.50 / 5.0, bottom=0.145)

    ax.set_xlim(-0.5, len(FULL_YEARS) - 0.5)
    ax.set_ylim(0, ann.to_numpy().max() * 1.09)
    ax.set_xticks(range(len(FULL_YEARS)), FULL_YEARS, fontsize=10)
    ax.tick_params(length=0, labelsize=9)
    ax.set_ylabel("days per year", fontsize=9.5, color=t["secondary"], labelpad=8)
    ax.yaxis.grid(True, color=t["grid"], linewidth=1.0 * SCALE, zorder=0)
    ax.set_axisbelow(True)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(t["axis"])

    fig.canvas.draw()
    w, gap, total, (rx, ry) = grouped_geometry(ax, 0.62, len(REGIONS))

    for i, region in enumerate(REGIONS):
        for j, yr in enumerate(FULL_YEARS):
            v = ann.loc[region, yr]
            x = j - total / 2 + i * (w + gap)
            rounded_column(ax, x, w, v, rx, ry, t["ordinal"][i])
            ax.text(x + w / 2, v + ax.get_ylim()[1] * 0.022, f"{int(v)}",
                    ha="center", va="bottom", fontsize=8.2, color=t["secondary"])

    titles(fig, t, "Qualifying days per year",
           f"Full calendar years only. {CRITERION}.")
    legend_row(fig, t)
    footer(fig, t, " · 2026 excluded (partial year)")
    fig.savefig(f"{FIGDIR}/wind_window_annual_{mode}.png", dpi=DPI)
    plt.close(fig)


if __name__ == "__main__":
    df = pd.read_csv(RESULTS)
    for mode in ("light", "dark"):
        fig_heatmap(df, mode)
        fig_seasonality(df, mode)
        fig_annual(df, mode)
    print("wrote:")
    import os
    for f in sorted(os.listdir(FIGDIR)):
        print("  ", os.path.join(FIGDIR, f))
