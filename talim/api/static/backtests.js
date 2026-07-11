"use strict";

const state = {
  authenticated: false,
  outcomes: [],
  selectedOutcomeKey: null,
  filters: { strategy: "", instrument: "", timeframe: "", sort: "sharpe_desc", limit: 100 },
  filterOptionsLoaded: false,
  activeView: "runs",
};

async function refreshSession() {
  try {
    const resp = await fetch("/talim/auth/session", { credentials: "same-origin" });
    const body = await resp.json();
    state.authenticated = !!body.authenticated;
  } catch (_) {
    state.authenticated = false;
  }
}

async function loginWithSecret(secret) {
  const resp = await fetch("/talim/auth/login", {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ secret }),
  });
  let body = null;
  try { body = await resp.json(); } catch (_) { body = null; }
  if (!resp.ok) throw new Error((body && body.detail) || `HTTP ${resp.status}`);
  state.authenticated = true;
}

async function api(path) {
  const resp = await fetch(path, { credentials: "same-origin" });
  let body = null;
  try { body = await resp.json(); } catch (_) { body = null; }
  if (!resp.ok) {
    const err = new Error((body && body.detail) || `HTTP ${resp.status}`);
    err.status = resp.status;
    if (resp.status === 401 && state.authenticated) {
      state.authenticated = false;
      syncAuthUi();
    }
    throw err;
  }
  return body;
}

function el(tag, attrs, children) {
  const node = document.createElement(tag);
  if (attrs) {
    for (const [k, v] of Object.entries(attrs)) {
      if (k === "class") node.className = v;
      else if (k === "text") node.textContent = v;
      else if (k.startsWith("on") && typeof v === "function") node.addEventListener(k.slice(2).toLowerCase(), v);
      else if (v === true) node.setAttribute(k, "");
      else if (v != null && v !== false) node.setAttribute(k, String(v));
    }
  }
  for (const c of [].concat(children || [])) {
    if (c == null) continue;
    node.appendChild(typeof c === "string" ? document.createTextNode(c) : c);
  }
  return node;
}

function clear(node) { while (node.firstChild) node.removeChild(node.firstChild); }
function fmtNum(v, digits = 2) { return v == null || Number.isNaN(Number(v)) ? "—" : Number(v).toFixed(digits); }
function fmtSigned(v) { return v == null || Number.isNaN(Number(v)) ? "—" : `${Number(v) >= 0 ? "+" : ""}${Number(v).toFixed(2)}`; }
function pnlClass(v) { return v == null || Number.isNaN(Number(v)) ? "" : (Number(v) >= 0 ? "pnl-pos" : "pnl-neg"); }
function fmtPct(v) { return v == null || Number.isNaN(Number(v)) ? "—" : `${(Number(v) * 100).toFixed(1)}%`; }
function fmtDate(v) { return v ? String(v).slice(0, 19).replace("T", " ") : "—"; }

function buildQuery(filters) {
  const params = new URLSearchParams();
  for (const [k, v] of Object.entries(filters)) {
    if (v !== "" && v != null) params.set(k, String(v));
  }
  const qs = params.toString();
  return qs ? `?${qs}` : "";
}

function apiFilters() {
  return {
    strategy: state.filters.strategy,
    instrument: state.filters.instrument,
    timeframe: state.filters.timeframe,
    limit: 500,
  };
}

function sortOutcomes(outcomes) {
  const sort = state.filters.sort || "sharpe_desc";
  const value = (o, key) => Number(o[key] || 0);
  const comparators = {
    sharpe_desc: (a, b) => value(b, "sharpe_ratio") - value(a, "sharpe_ratio") || value(b, "net_pnl") - value(a, "net_pnl"),
    win_rate_desc: (a, b) => value(b, "win_rate") - value(a, "win_rate") || value(b, "sharpe_ratio") - value(a, "sharpe_ratio"),
    net_pnl_desc: (a, b) => value(b, "net_pnl") - value(a, "net_pnl"),
    avg_net_pnl_desc: (a, b) => value(b, "avg_net_pnl") - value(a, "avg_net_pnl"),
    max_drawdown_desc: (a, b) => value(b, "max_drawdown") - value(a, "max_drawdown"),
    total_trades_desc: (a, b) => value(b, "total_trades") - value(a, "total_trades"),
    run_count_desc: (a, b) => value(b, "run_count") - value(a, "run_count"),
  };
  return outcomes.slice().sort(comparators[sort] || comparators.sharpe_desc);
}

function uniqueSorted(values) {
  return Array.from(new Set(values.filter(Boolean))).sort((a, b) => String(a).localeCompare(String(b), undefined, { numeric: true }));
}

function setSelectOptions(select, values, allLabel) {
  const current = select.value;
  clear(select);
  select.appendChild(el("option", { value: "", text: allLabel }));
  for (const value of values) select.appendChild(el("option", { value, text: value }));
  select.value = values.includes(current) ? current : "";
}

async function refreshFilterOptions() {
  if (!state.authenticated) return;
  try {
    const data = await api("/talim/operator/backtests/outcomes?limit=500");
    const outcomes = data.outcomes || [];
    const form = document.getElementById("backtests-filter");
    setSelectOptions(form.strategy, uniqueSorted(outcomes.map((o) => o.strategy)), "All strategies");
    setSelectOptions(form.instrument, uniqueSorted(outcomes.map((o) => o.instrument)), "All instruments");
    setSelectOptions(form.timeframe, uniqueSorted(outcomes.map((o) => o.timeframe)), "All bars");
    form.strategy.value = state.filters.strategy;
    form.instrument.value = state.filters.instrument;
    form.timeframe.value = state.filters.timeframe;
    state.filterOptionsLoaded = true;
  } catch (_) {
    // Keep static "All" dropdowns if the user is not signed in yet or the API fails.
  }
}

function syncAuthUi() {
  const auth = document.getElementById("auth-state");
  const btn = document.getElementById("signin-btn");
  auth.textContent = state.authenticated ? "Signed in" : "Locked";
  auth.className = state.authenticated ? "auth-unlocked" : "auth-locked";
  btn.hidden = state.authenticated;
}

function showView(name) {
  state.activeView = name;
  document.querySelectorAll(".bt-view").forEach((view) => view.classList.toggle("active", view.id === `view-${name}`));
  document.querySelectorAll(".mobile-tabs .tab").forEach((tab) => tab.classList.toggle("active", tab.dataset.view === name));
  if (name === "graph") drawGraph();
}

async function refreshRuns() {
  document.getElementById("last-refresh").textContent = new Date().toISOString().replace("T", " ").replace(/\..*/, "") + " UTC";
  const body = document.getElementById("runs-body");
  clear(body);
  body.appendChild(el("div", { class: "muted", text: "Loading strategy outcomes…" }));
  try {
    if (!state.filterOptionsLoaded) await refreshFilterOptions();
    const data = await api("/talim/operator/backtests/outcomes" + buildQuery(apiFilters()));
    const limit = Math.min(Math.max(Number(state.filters.limit) || 100, 1), 500);
    state.outcomes = sortOutcomes(data.outcomes || []).slice(0, limit);
    if (state.selectedOutcomeKey && !state.outcomes.some((o) => o.key === state.selectedOutcomeKey)) state.selectedOutcomeKey = null;
    if (!state.selectedOutcomeKey && state.outcomes.length) state.selectedOutcomeKey = state.outcomes[0].key;
    renderRuns();
    renderDetail();
    drawGraph();
  } catch (err) {
    clear(body);
    const msg = err.status === 401 ? "Sign in first to view backtests." : err.message;
    body.appendChild(el("div", { class: "error", text: msg }));
  }
}

function renderRuns() {
  const body = document.getElementById("runs-body");
  clear(body);
  if (!state.outcomes.length) {
    body.appendChild(el("div", { class: "panel empty-state" }, [
      el("h2", { text: "No strategy outcomes yet" }),
      el("p", { class: "muted", text: "When Talim records or imports backtests, grouped strategy outcomes will appear here." }),
      el("p", { class: "muted", text: "Try a strategy/instrument/bars dropdown or change the sort option." }),
    ]));
    return;
  }
  for (const outcome of state.outcomes) body.appendChild(runCard(outcome));
}

function runCard(outcome) {
  const selected = outcome.key === state.selectedOutcomeKey;
  return el("article", { class: `run-card${selected ? " selected" : ""}`, onClick: () => selectRun(outcome.key) }, [
    el("div", { class: "run-card-head" }, [
      el("div", null, [
        el("strong", { text: `${outcome.strategy || "—"} · ${outcome.instrument || "—"}` }),
        el("div", { class: "muted", text: `${outcome.timeframe || "—"} · ${outcome.run_count} run${outcome.run_count === 1 ? "" : "s"} · latest ${fmtDate(outcome.latest_created_at)}` }),
      ]),
      el("span", { class: `pill ${pnlClass(outcome.net_pnl)}`, text: fmtSigned(outcome.net_pnl) }),
    ]),
    paramChips(outcome.params),
    el("div", { class: "metric-grid" }, [
      metric("Avg Sharpe", fmtNum(outcome.sharpe_ratio, 3)),
      metric("Best Sharpe", fmtNum(outcome.best_sharpe, 3)),
      metric("Worst DD", fmtSigned(outcome.max_drawdown), pnlClass(outcome.max_drawdown)),
      metric("Win rate", fmtPct(outcome.win_rate)),
      metric("Trades", outcome.total_trades == null ? "—" : String(outcome.total_trades)),
    ]),
    el("div", { class: "muted", text: `best run #${outcome.best_run_id || "—"} · avg P&L ${fmtSigned(outcome.avg_net_pnl)}` }),
  ]);
}

function paramChips(params) {
  const entries = Object.entries(params || {});
  if (!entries.length) return el("div", { class: "param-chips muted", text: "baseline/default params" });
  return el("div", { class: "param-chips" }, entries.slice(0, 8).map(([k, v]) => el("span", { class: "chip", text: `${k}: ${v}` })));
}

function metric(label, value, cls) {
  return el("div", { class: "metric" }, [
    el("span", { class: "muted", text: label }),
    el("strong", { class: cls || "", text: value }),
  ]);
}

function selectRun(key) {
  state.selectedOutcomeKey = key;
  renderRuns();
  renderDetail();
  showView("detail");
}

async function renderDetail() {
  const body = document.getElementById("detail-body");
  const key = state.selectedOutcomeKey;
  clear(body);
  body.appendChild(el("h2", { text: "Strategy outcome" }));
  if (!key) {
    body.appendChild(el("p", { class: "muted", text: "Select a strategy outcome or tap a bar in Graph." }));
    return;
  }
  const outcome = state.outcomes.find((o) => o.key === key);
  if (!outcome) return;
  body.appendChild(el("h3", { text: `${outcome.strategy} · ${outcome.instrument} · ${outcome.timeframe || "—"}` }));
  body.appendChild(paramChips(outcome.params));
  body.appendChild(el("div", { class: "metric-grid detail-metrics" }, [
    metric("Total P&L", fmtSigned(outcome.net_pnl), pnlClass(outcome.net_pnl)),
    metric("Avg P&L", fmtSigned(outcome.avg_net_pnl), pnlClass(outcome.avg_net_pnl)),
    metric("Avg Sharpe", fmtNum(outcome.sharpe_ratio, 4)),
    metric("Best Sharpe", fmtNum(outcome.best_sharpe, 4)),
    metric("Sortino", fmtNum(outcome.sortino_ratio, 4)),
    metric("Profit factor", fmtNum(outcome.profit_factor, 3)),
    metric("Worst DD", fmtSigned(outcome.max_drawdown), pnlClass(outcome.max_drawdown)),
    metric("Win rate", fmtPct(outcome.win_rate)),
    metric("Total trades", outcome.total_trades == null ? "—" : String(outcome.total_trades)),
    metric("Runs", String(outcome.run_count)),
  ]));
  body.appendChild(kv({
    period_start: outcome.period_start,
    period_end: outcome.period_end,
    latest_created_at: outcome.latest_created_at,
    status: outcome.status,
    best_run_id: outcome.best_run_id,
    artifact_paths: (outcome.artifact_paths || []).join(", "),
    sample_run_ids: (outcome.run_ids || []).join(", "),
  }));
}

function kv(rows) {
  const dl = el("dl", { class: "kv" });
  for (const [k, v] of Object.entries(rows)) {
    if (v == null || v === "") continue;
    dl.appendChild(el("dt", { text: k }));
    dl.appendChild(el("dd", { text: String(v) }));
  }
  return dl;
}

function drawGraph() {
  const canvas = document.getElementById("runs-chart");
  const empty = document.getElementById("graph-empty");
  const summary = document.getElementById("graph-summary");
  const ctx = canvas.getContext("2d");
  const metricName = document.getElementById("graph-metric").value;
  const rows = state.outcomes.slice().reverse();
  clear(summary);
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  empty.hidden = rows.length > 0;
  if (!rows.length) return;

  const values = rows.map((r) => Number(r[metricName] || 0));
  const min = Math.min(0, ...values);
  const max = Math.max(0, ...values);
  const span = max - min || 1;
  const pad = 44;
  const w = canvas.width - pad * 2;
  const h = canvas.height - pad * 2;
  const zeroY = pad + h - ((0 - min) / span) * h;
  const barW = Math.max(12, Math.min(48, w / rows.length - 8));

  summary.appendChild(metric("Best", formatMetric(Math.max(...values), metricName)));
  summary.appendChild(metric("Worst", formatMetric(Math.min(...values), metricName)));
  summary.appendChild(metric("Outcomes", String(rows.length)));

  ctx.strokeStyle = "#2a2f3a";
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.moveTo(pad, zeroY);
  ctx.lineTo(canvas.width - pad, zeroY);
  ctx.stroke();

  ctx.fillStyle = "#8b93a1";
  ctx.font = "22px -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif";
  ctx.fillText(metricLabel(metricName), pad, 28);
  ctx.font = "12px -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif";
  ctx.fillText(formatMetric(max, metricName), 8, pad + 4);
  ctx.fillText(formatMetric(min, metricName), 8, pad + h);

  rows.forEach((run, i) => {
    const x = pad + i * (w / rows.length) + (w / rows.length - barW) / 2;
    const y = pad + h - ((values[i] - min) / span) * h;
    const top = Math.min(y, zeroY);
    const height = Math.max(2, Math.abs(zeroY - y));
    ctx.fillStyle = values[i] >= 0 ? "#3fb950" : "#f85149";
    ctx.fillRect(x, top, barW, height);
    if (run.key === state.selectedOutcomeKey) {
      ctx.strokeStyle = "#4fa3ff";
      ctx.lineWidth = 3;
      ctx.strokeRect(x - 2, top - 2, barW + 4, height + 4);
    }
    ctx.fillStyle = "#8b93a1";
    ctx.fillText(`${run.strategy?.replace(/^(momentum|mean-reversion)-/, "") || ""} ${run.timeframe || ""}`.slice(0, 14), x, canvas.height - 14);
  });
}

function formatMetric(value, name) {
  if (name === "win_rate" || name === "return_pct") return `${(Number(value) * 100).toFixed(1)}%`;
  if (name === "total_trades") return String(Math.round(Number(value)));
  if (name === "sharpe_ratio" || name === "sortino_ratio" || name === "profit_factor") return fmtNum(value, 3);
  return fmtSigned(value);
}

function metricLabel(name) {
  return {
    net_pnl: "Total P&L by strategy outcome",
    return_pct: "Return % by strategy outcome",
    sharpe_ratio: "Average Sharpe by strategy outcome",
    sortino_ratio: "Average Sortino by strategy outcome",
    max_drawdown: "Worst drawdown by strategy outcome",
    win_rate: "Weighted win rate by strategy outcome",
    profit_factor: "Average profit factor by strategy outcome",
    total_trades: "Total trades by strategy outcome",
  }[name] || name;
}

function bindEvents() {
  document.getElementById("signin-btn").addEventListener("click", async () => {
    const secret = await TalimUI.promptSecret();
    if (!secret) return;
    try {
      await loginWithSecret(secret);
      syncAuthUi();
      await refreshFilterOptions();
      refreshRuns();
    } catch (err) {
      TalimUI.toast(err.message || "Sign in failed", "error");
    }
  });
  document.getElementById("refresh-btn").addEventListener("click", refreshRuns);
  document.getElementById("backtests-filter").addEventListener("submit", (ev) => {
    ev.preventDefault();
    const f = ev.target;
    state.filters = {
      strategy: f.strategy.value,
      instrument: f.instrument.value,
      timeframe: f.timeframe.value,
      sort: f.sort.value,
      limit: Number(f.limit.value) || 100,
    };
    refreshRuns();
  });
  document.getElementById("toggle-filters").addEventListener("click", () => {
    document.getElementById("backtests-filter").classList.toggle("open");
  });
  document.querySelectorAll(".mobile-tabs .tab").forEach((tab) => tab.addEventListener("click", () => showView(tab.dataset.view)));
  document.getElementById("graph-metric").addEventListener("change", drawGraph);
  document.getElementById("runs-chart").addEventListener("click", (ev) => {
    const rows = state.outcomes.slice().reverse();
    if (!rows.length) return;
    const rect = ev.target.getBoundingClientRect();
    const x = (ev.clientX - rect.left) * (ev.target.width / rect.width);
    const pad = 44;
    const w = ev.target.width - pad * 2;
    const idx = Math.floor((x - pad) / (w / rows.length));
    if (rows[idx]) selectRun(rows[idx].key);
  });
}

document.addEventListener("DOMContentLoaded", async () => {
  bindEvents();
  await refreshSession();
  syncAuthUi();
  await refreshFilterOptions();
  refreshRuns();
});
