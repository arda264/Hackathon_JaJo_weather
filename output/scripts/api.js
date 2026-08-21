/* DutchSail weather — the data-access layer, in output/scripts with the rest
 * of the project's scripts.
 *
 * The browser no longer calls any external forecast API. All forecast data is
 * fetched — and every graph rendered — by the Claude agent (agent/run_agent.py):
 * one API call to Claude, and the agent handles the rest, writing
 * output/figures/agent/*.png and output/results/agent/summary.json.
 *
 * What remains here are same-origin reads of those agent outputs and of the
 * route pipeline's files, plus the optional live route optimiser. Pages and
 * frontend/assets/common.js never call fetch() themselves.
 */
"use strict";

/* ---------------- endpoints (all same-origin) ---------------- */

const AGENT_SUMMARY_URL = "../output/results/agent/summary.json";

const ROUTE_TODAY_URL = "./data/route-today.json";     // rewritten daily by CI
const ROUTE_SAMPLE_URL = "./data/route-sample.json";   // last-resort synthetic fallback
const ROUTE_ROBUSTNESS_URL = "../route/app/gribs/robustness.json";
const ROUTE_SUMMARY_URL = "../route/app/gribs/summary.json";
const ROUTE_API_URL = "/api/route";
const ROUTE_API_TIMEOUT_MS = 45000;

async function fetchJson(url) {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`HTTP ${r.status} from ${new URL(url, location.href).host}`);
  return r.json();
}

/* ---------------- agent outputs ---------------- */

// The summary the agent writes on every run; the file is rewritten in place,
// so bust the browser cache.
async function fetchAgentSummary() {
  return fetchJson(`${AGENT_SUMMARY_URL}?t=${Date.now()}`);
}

/* ---------------- route data (route.html) ---------------- */

// POST the current vector to the live optimiser; throws on timeout or error
async function fetchLiveRoute(current) {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), ROUTE_API_TIMEOUT_MS);
  try {
    const res = await fetch(ROUTE_API_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ current }),
      signal: ctrl.signal,
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || `optimiser returned ${res.status}`);
    return data;
  } finally {
    clearTimeout(timer);
  }
}

// stored → today's CI-generated route first, synthetic sample only if that is missing
async function fetchStoredRoute() {
  for (const url of [ROUTE_TODAY_URL, ROUTE_SAMPLE_URL]) {
    try {
      const res = await fetch(url);
      if (res.ok) return await res.json();
    } catch { /* try the next one */ }
  }
  return null;
}

// LLM brief for the route page; null when unavailable
async function fetchRouteSummary() {
  try {
    const res = await fetch(ROUTE_SUMMARY_URL);
    return res.ok ? await res.json() : null;
  } catch {
    return null;
  }
}

// robustness cross-evaluation KPIs; throws so the page can show the regen hint
async function fetchRobustness() {
  return fetchJson(ROUTE_ROBUSTNESS_URL);
}
