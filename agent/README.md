# DutchSail agent

The site's data pipeline is now **one API call to Claude**. `run_agent.py` starts a
single agentic run (`client.beta.messages.tool_runner`, model `claude-opus-5`) and
hands the agent four tools — shell, read, write, list — plus an output contract.
The agent does everything else itself:

1. Reads the skills in [`.agents/skills/`](../.agents/skills) (`get-forecast`,
   `weather-statistics`) and follows them.
2. Fetches the forecast data — Open-Meteo wind (six models) and marine, and the
   Copernicus Marine wave/current forecasts when credentials are present.
3. Computes the learned blend (`forecast_blend/results/weights.json`) and the
   sailing-window verdict.
4. Renders every graph the frontend shows, in light **and** dark variants, to
   `output/figures/agent/`, and writes `output/results/agent/summary.json`.

The frontend makes **no external API calls** anymore — the pages just display the
figures and the summary the agent produced (see `frontend/README.md`).

## Run

```
pip install anthropic
set ANTHROPIC_API_KEY=sk-ant-...        # or run `ant auth login` once
python agent/run_agent.py
```

Optionally pass a custom instruction:

```
python agent/run_agent.py "Only regenerate the tide figure"
```

A full refresh takes a few minutes (the agent downloads data, writes scripts, runs
them, and verifies its own output). Commit the refreshed `output/figures/agent/` and
`output/results/agent/summary.json` to publish them — the site is served statically.

## What the agent produces

| File | Shown on |
| --- | --- |
| `output/figures/agent/wind_forecast_{light,dark}.png` | index, wind |
| `output/figures/agent/wind_next24_{light,dark}.png` | current |
| `output/figures/agent/tide_{light,dark}.png` | tide |
| `output/figures/agent/currents_map_{light,dark}.png` | tide (skipped without Copernicus credentials) |
| `output/figures/agent/waves_map_{light,dark}.png` | tide (skipped without Copernicus credentials) |
| `output/results/agent/summary.json` | all pages (tiles, verdicts, model table) |

Copernicus credentials live at `credentials/.copernicusmarine-credentials`
(gitignored); without them the agent skips the two map figures and says so in
`summary.json` → `notes`.
