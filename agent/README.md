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

## Automatic refresh (GitHub Actions)

`.github/workflows/agent-refresh.yml` runs the agent daily at 05:30 UTC, commits
whatever changed under `output/figures/agent/` + `output/results/agent/summary.json`,
and pushes — which triggers the Vercel redeploy, exactly like the existing daily
route job. Setup:

1. **Add the Claude key** — GitHub repo → **Settings → Secrets and variables →
   Actions → New repository secret**:
   - Name: `ANTHROPIC_API_KEY`
   - Value: an API key from <https://platform.claude.com> (Console → API keys).
   This is the only required secret. **Do not put this key in Vercel** — the deploy
   is static and never runs the agent; the key lives only in Actions.

2. **(Optional) add the Copernicus credentials** so the agent can also draw the two
   corridor map figures:
   1. Locally, run `python scripts/get_sample_wave_forecast.py` once — it prompts
      for your Copernicus Marine username/password and writes
      `credentials/.copernicusmarine-credentials`.
   2. Copy that file's *contents* into a second repository secret named
      `COPERNICUSMARINE_CREDENTIALS`.
   The workflow recreates the file from the secret before the run. Without it, the
   run still succeeds — the agent skips `currents_map`/`waves_map` and notes why in
   `summary.json`.

3. **Test it** — Actions → **Agent forecast refresh** → **Run workflow**. Watch the
   log: the runner prints every command the agent executes. On success the job
   pushes a commit like `Agent forecast refresh: 2026-08-21 05:30Z`, and Vercel
   redeploys from it.

4. **Vercel side** — nothing agent-related to configure. The only environment
   variable Vercel needs is `MAPBOX_TOKEN` (a public `pk.` token for the route map);
   the site itself is served statically from what the workflow commits.

Notes:

- **Cost**: every run is one full agentic run on `claude-opus-5` (typically a few
  minutes of tool use). Tune the `cron` line in the workflow to your budget, or
  remove the `schedule` block and trigger it manually only.
- The schedule is offset from the 11:30 UTC route job so the two never push at the
  same time.
- `.gitignore` ignores `output/figures/*` **except** `output/figures/agent/` — keep
  that exception, or the workflow's commit step will silently miss the new PNGs.
