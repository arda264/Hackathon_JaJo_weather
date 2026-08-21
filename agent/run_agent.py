#!/usr/bin/env python3
"""DutchSail agent runner — the project's single Claude API call.

The browser no longer fetches forecasts. Instead this script hands the whole
job to a Claude agent: it reads the skills in .agents/skills, downloads the
forecast data itself (Open-Meteo, Copernicus Marine), computes the blend and
the sailing-window verdict, and renders every graph the frontend displays as
light/dark PNGs plus a machine-readable summary.json.

Usage:
    pip install anthropic
    set ANTHROPIC_API_KEY (or run `ant auth login` once)
    python agent/run_agent.py            # full refresh
    python agent/run_agent.py "task..."  # custom instruction

Everything below the tool_runner() call is plumbing: the four tools the agent
drives (shell, read, write, list) and the contract it must fulfil.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import anthropic
from anthropic import beta_tool

REPO_ROOT = Path(__file__).resolve().parents[1]
SKILLS_DIR = REPO_ROOT / ".agents" / "skills"

MODEL = "claude-opus-5"
MAX_TOKENS = 16000
COMMAND_TIMEOUT_S = 1800  # forecast downloads (Copernicus) can be slow
MAX_TOOL_OUTPUT = 20000   # chars returned to the model per tool call

# ---------------------------------------------------------------- tools

def _safe_path(path: str) -> Path:
    """Resolve a path against the repo root and refuse to escape it."""
    p = (REPO_ROOT / path).resolve()
    if not p.is_relative_to(REPO_ROOT):
        raise ValueError(f"path escapes the repository: {path}")
    return p


def _clip(text: str) -> str:
    if len(text) <= MAX_TOOL_OUTPUT:
        return text
    half = MAX_TOOL_OUTPUT // 2
    return (
        text[:half]
        + f"\n... [{len(text) - MAX_TOOL_OUTPUT} chars omitted] ...\n"
        + text[-half:]
    )


@beta_tool
def run_command(command: str) -> str:
    """Run a shell command from the repository root and return its combined output.

    Args:
        command: The command line to execute (runs via the system shell, with the
            repository root as working directory). Prefer writing longer scripts to
            a file with write_file and running them, over complex one-liners.
    """
    print(f"  $ {command}", flush=True)
    try:
        r = subprocess.run(
            command, shell=True, cwd=REPO_ROOT, capture_output=True,
            text=True, encoding="utf-8", errors="replace",
            timeout=COMMAND_TIMEOUT_S,
        )
    except subprocess.TimeoutExpired:
        return f"ERROR: command timed out after {COMMAND_TIMEOUT_S}s"
    out = (r.stdout or "") + (("\n[stderr]\n" + r.stderr) if r.stderr else "")
    return _clip(f"exit code {r.returncode}\n{out.strip()}")


@beta_tool
def read_file(path: str) -> str:
    """Read a text file inside the repository.

    Args:
        path: File path relative to the repository root.
    """
    print(f"  read  {path}", flush=True)
    return _clip(_safe_path(path).read_text(encoding="utf-8", errors="replace"))


@beta_tool
def write_file(path: str, content: str) -> str:
    """Create or overwrite a text file inside the repository.

    Args:
        path: File path relative to the repository root; parent directories are created.
        content: Full text content to write (UTF-8).
    """
    print(f"  write {path} ({len(content)} chars)", flush=True)
    p = _safe_path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8", newline="\n")
    return f"wrote {path}"


@beta_tool
def list_dir(path: str = ".") -> str:
    """List a directory inside the repository (names only; directories get a trailing /).

    Args:
        path: Directory path relative to the repository root.
    """
    print(f"  ls    {path}", flush=True)
    p = _safe_path(path)
    entries = sorted(
        (e.name + "/" if e.is_dir() else e.name) for e in p.iterdir()
    )
    return _clip("\n".join(entries) or "(empty)")


# ---------------------------------------------------------------- prompt

def skill_index() -> str:
    """One line per available skill, from each SKILL.md's frontmatter."""
    lines = []
    for md in sorted(SKILLS_DIR.glob("*/SKILL.md")):
        text = md.read_text(encoding="utf-8", errors="replace")
        name = md.parent.name
        m = re.search(r"^description:\s*(.+)$", text, re.MULTILINE)
        desc = m.group(1).strip() if m else ""
        rel = md.relative_to(REPO_ROOT).as_posix()
        lines.append(f"- {name} ({rel}): {desc}")
    return "\n".join(lines) or "(no skills found)"


SYSTEM = f"""You are the data-and-graphs agent for the DutchSail weather site — a static
site about sailing the southern North Sea (the Lowestoft → IJmuiden record corridor).
The site makes NO external API calls from the browser anymore: you fetch all forecast
data and render every graph. The pages only display what you produce.

Repository root: {REPO_ROOT}
Platform: {sys.platform} (run_command uses the system shell). The pixi environments in
pyproject.toml (metocean, copernicus) are declared for linux-64; if `pixi run` does not
work on this machine, fall back to any available Python (create a venv and pip install
what you need: requests, numpy, pandas, xarray, netcdf4, matplotlib, copernicusmarine).

# Skills
Before doing work a skill covers, read its SKILL.md (and the example scripts it points
to) and follow it:
{skill_index()}

# Data sources
- Wind (six models, hourly, 7 days): GET https://api.open-meteo.com/v1/forecast
  ?latitude={{lat}}&longitude={{lon}}
  &hourly=wind_speed_10m,wind_direction_10m,wind_gusts_10m
  &models=ecmwf_ifs025,gfs_global,icon_eu,meteofrance_arpege_europe,knmi_harmonie_arome_netherlands,ukmo_global_deterministic_10km
  &wind_speed_unit=ms&timeformat=unixtime&forecast_days=7
  Response hourly keys come back suffixed per model id. No API key.
- Marine (hourly, 5 days): GET https://marine-api.open-meteo.com/v1/marine
  ?latitude={{lat}}&longitude={{lon}}
  &hourly=sea_level_height_msl,wave_height,ocean_current_velocity,ocean_current_direction
  &timeformat=unixtime&forecast_days=5
  Current velocity is in km/h — convert to knots (kt = kmh / 1.852). No key.
- Copernicus Marine wave + current forecasts: use the get-forecast skill. Credentials
  live at credentials/.copernicusmarine-credentials; if that file does not exist, SKIP
  the Copernicus map figures, and record why in summary.json "notes".
- Blend weights: read forecast_blend/results/weights.json ("speed" and "direction"
  maps keyed ecmwf/gfs/icon/arpege/harmonie/ukmo). Blend speed and gusts with the
  speed weights (weighted mean over models that report a value, weights renormalized);
  blend direction with the direction weights on unit vectors (atan2 of the weighted
  vector sum). Model spread = max - min speed across models per hour.
- Location: lat 52.5, lon 3.0 — "Mid-corridor (52.5°N 3.0°E)".
- Sailing-window criterion: blend wind 18–30 kt (1 kt = 0.514444 m/s) from 205–235°
  or 305–335°, sustained ≥ 6 consecutive hours within a local day.

# Output contract — produce ALL of this every run
Figures go in output/figures/agent/, each in a light and a dark variant named
<name>_light.png and <name>_dark.png (~1400px wide, dpi ≥ 120). Read
frontend/assets/style.css first and match its palette: figure/axes backgrounds should
match the site's surface colors for each theme, text its ink colors, and series its
--s1..--s7 accent colors. Timestamps in figures: label as UTC.

1. wind_forecast     — 7-day hourly wind, 2 stacked panels: (a) blend speed (bold)
                       over all six models with a legend, (b) blended gusts. m/s.
                       No spread panel — "now".spread_ms still carries the number.
2. wind_next24       — next 24 h blended wind speed with direction arrows along the
                       time axis (arrows point where the wind blows TOWARD).
3. tide              — 5-day marine outlook, 3 stacked panels: (a) sea level (m MSL)
                       with the next high/low water labeled, (b) tidal stream (kt)
                       with direction arrows (TOWARD), (c) significant wave height (m).
4. currents_map      — latest Copernicus currents quick-look map (speed colormap +
                       arrows), per the get-forecast skill. Skip without credentials.
5. waves_map         — Copernicus wave multipanel quick-look, per the get-forecast
                       skill. Skip without credentials.

Write output/results/agent/summary.json exactly in this shape (ISO-8601 UTC times):
{{
  "generated_at": "...",
  "point": {{"lat": 52.5, "lon": 3.0, "name": "Mid-corridor (52.5°N 3.0°E)"}},
  "now": {{"speed_ms": .., "dir_deg": .., "gust_ms": .., "spread_ms": .., "met": bool}},
  "days": [ {{"date": "YYYY-MM-DD", "label": "Thu 21", "met": bool, "best_run_h": int}} x7 ],
  "models": [ {{"name": "ECMWF IFS 0.25°", "speed_ms": .., "dir_deg": .., "gust_ms": ..,
               "weight_speed": .., "weight_direction": ..}} x6 ],
  "tide": {{"level_m": .., "rising": bool,
           "next_high": {{"time": "...", "level_m": ..}},
           "next_low":  {{"time": "...", "level_m": ..}},
           "stream_kt": .., "stream_dir_deg": .., "wave_height_m": ..}},
  "notes": ["..."]
}}
"now"/"tide" values are at the current UTC hour; "days" covers today + 6 days with the
longest consecutive qualifying run per local day. Model display names:
ECMWF IFS 0.25°, NOAA GFS, DWD ICON-EU, ARPEGE Europe, KNMI HARMONIE, UKMO Global 10 km.
Save any intermediate data under output/results/agent/.

# Working style
- Write real script files (write_file) under output/results/agent/scripts/ and run
  them; don't fight shell quoting with one-liners.
- Verify before finishing: list output/figures/agent/ and read back summary.json;
  every contracted file must exist (minus documented skips). If a figure failed,
  fix it and rerun — do not declare success with missing files.
- Finish with a short plain-text report of what was produced and any skips.
"""

DEFAULT_TASK = (
    "Refresh everything: fetch the latest forecast data and regenerate every "
    "figure and the summary.json per your output contract."
)

# ---------------------------------------------------------------- main

def main() -> int:
    task = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_TASK
    client = anthropic.Anthropic()
    tools = [run_command, read_file, write_file, list_dir]

    params = dict(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        output_config={"effort": "high"},
        system=SYSTEM,
        tools=tools,
        messages=[{"role": "user", "content": task}],
        max_iterations=100,
        # Opus 5 safety classifiers can decline a request; the server-side
        # fallback re-runs it on the recommended fallback model instead.
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
    )

    print(f"DutchSail agent — one Claude API call ({MODEL})")
    print(f"task: {task}\n")
    started = datetime.now(timezone.utc)

    try:
        runner = client.beta.messages.tool_runner(**params)
    except TypeError:
        # older SDK without the fallbacks parameter — run without it
        params.pop("fallbacks", None)
        params.pop("betas", None)
        runner = client.beta.messages.tool_runner(**params)

    final = None
    for message in runner:
        final = message
        for block in message.content:
            if block.type == "text" and block.text.strip():
                print(f"\n{block.text.strip()}\n", flush=True)

    print(f"\nelapsed: {datetime.now(timezone.utc) - started}")
    if final is None:
        print("no response from the model")
        return 1
    if final.stop_reason == "refusal":
        print("the request was declined by safety classifiers (stop_reason=refusal)")
        return 1

    summary = REPO_ROOT / "output" / "results" / "agent" / "summary.json"
    if summary.exists():
        data = json.loads(summary.read_text(encoding="utf-8"))
        print(f"summary.json OK — generated_at {data.get('generated_at')}")
        figs = sorted((REPO_ROOT / "output" / "figures" / "agent").glob("*.png"))
        print(f"figures: {', '.join(f.name for f in figs) or '(none)'}")
        return 0
    print("WARNING: agent finished but output/results/agent/summary.json is missing")
    return 1


if __name__ == "__main__":
    sys.exit(main())
