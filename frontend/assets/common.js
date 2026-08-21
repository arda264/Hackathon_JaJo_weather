/* DutchSail weather frontend — shared UI helpers.
 * All data access lives in output/scripts/api.js — include that first; nothing
 * in this file calls fetch(). Graphs are no longer drawn in the browser: the
 * Claude agent (agent/run_agent.py) renders them as light/dark PNGs, and this
 * file's theme code swaps the right variant in. */
"use strict";

/* ---------------- theme ---------------- */

function effectiveTheme() {
  const t = document.documentElement.dataset.theme;
  if (t === "light" || t === "dark") return t;
  return matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

const themeListeners = [];
function onThemeChange(fn) { themeListeners.push(fn); }
function notifyTheme() { const t = effectiveTheme(); themeListeners.forEach(fn => fn(t)); }

function initChrome() {
  const btn = document.querySelector(".theme-toggle");
  if (btn) {
    const labels = { auto: "Theme: auto", light: "Theme: light", dark: "Theme: dark" };
    const urlTheme = new URLSearchParams(location.search).get("theme");
    let mode = (urlTheme === "light" || urlTheme === "dark") ? urlTheme
      : localStorage.getItem("ds-theme") || "auto";
    const apply = () => {
      if (mode === "auto") delete document.documentElement.dataset.theme;
      else document.documentElement.dataset.theme = mode;
      btn.textContent = labels[mode];
      notifyTheme();
    };
    btn.addEventListener("click", () => {
      mode = mode === "auto" ? "light" : mode === "light" ? "dark" : "auto";
      if (mode === "auto") localStorage.removeItem("ds-theme");
      else localStorage.setItem("ds-theme", mode);
      apply();
    });
    apply();
  }
  matchMedia("(prefers-color-scheme: dark)").addEventListener("change", notifyTheme);

  // generated PNGs exist in light and dark renders — swap src with the theme
  const swap = () => {
    const t = effectiveTheme();
    document.querySelectorAll("img[data-light]").forEach(img => {
      img.src = t === "dark" ? img.dataset.dark : img.dataset.light;
    });
  };
  onThemeChange(swap);
  swap();
}

/* ---------------- units & formatting ---------------- */

const msToKt = v => v * 1.9438445;

function beaufort(ms) {
  const t = [0.5, 1.5, 3.3, 5.5, 8.0, 10.8, 13.9, 17.2, 20.8, 24.5, 28.5, 32.7];
  let b = 0;
  while (b < t.length && ms >= t[b]) b++;
  return b;
}

function compass16(deg) {
  const names = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE", "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"];
  return names[Math.round(((deg % 360) + 360) % 360 / 22.5) % 16];
}

const DAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const pad2 = n => String(n).padStart(2, "0");
const fmtDay = d => `${DAYS[d.getDay()]} ${d.getDate()}`;
const fmtHour = d => `${pad2(d.getHours())}:${pad2(d.getMinutes())}`;
const fmtFull = d => `${fmtDay(d)} · ${fmtHour(d)}`;

/* ---------------- shared page bits ---------------- */

// stat tile used by the current and tide pages
function statTile(label, valueHtml, deltaText) {
  const div = document.createElement("div");
  div.className = "tile";
  const l = document.createElement("div");
  l.className = "label";
  l.textContent = label;
  const v = document.createElement("div");
  v.className = "value";
  v.innerHTML = valueHtml;
  const dl = document.createElement("div");
  dl.className = "delta";
  dl.textContent = deltaText;
  div.append(l, v, dl);
  return div;
}

function statusMsg(mount, text, retry) {
  mount.innerHTML = "";
  const div = document.createElement("div");
  div.className = "status-msg error";
  div.textContent = text;
  if (retry) {
    const b = document.createElement("button");
    b.textContent = "Retry";
    b.addEventListener("click", retry);
    div.append(b);
  }
  mount.append(div);
}

document.addEventListener("DOMContentLoaded", initChrome);
