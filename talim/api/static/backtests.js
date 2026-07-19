"use strict";

const state = {
  authenticated: false,
  outcomes: [],
  liveStrategies: [],
  filters: { instrument: "", timeframe: "", sort: "sharpe_ratio", period: "", min_trades: "20" },
  hiddenVariants: 0,
  filterOptionsLoaded: false,
  selectedStrategy: null,
  selectedVariantKey: null,
  activeView: "rankings",
};

const METRICS = {
  sharpe_ratio: { label: "Sharpe", fmt: (v) => fmtNum(v, 2) },
  net_pnl: { label: "Total P&L", fmt: fmtSigned },
  profit_factor: { label: "Profit factor", fmt: (v) => fmtNum(v, 2) },
  win_rate: { label: "Win rate", fmt: fmtPct },
  max_drawdown: { label: "Drawdown", fmt: fmtSigned },
  total_trades: { label: "Trades", fmt: (v) => String(Math.round(Number(v) || 0)) },
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
function fmtDate(v) { return v ? String(v).slice(0, 10) : "—"; }

function metricValue(outcome, name) { return Number(outcome[name] || 0); }

function sinceTimestamp(periodDays) {
  const days = Number(periodDays);
  if (!days) return "";
  return new Date(Date.now() - days * 86400_000).toISOString();
}

function buildQuery(filters) {
  const params = new URLSearchParams();
  for (const [k, v] of Object.entries(filters)) {
    if (v !== "" && v != null) params.set(k, String(v));
  }
  const qs = params.toString();
  return qs ? `?${qs}` : "";
}

// ---------- grouping: outcomes (variants) -> strategies ----------

function buildStrategies() {
  const metric = state.filters.sort;
  const minTrades = Number(state.filters.min_trades) || 0;
  const groups = new Map();
  state.hiddenVariants = 0;
  for (const outcome of state.outcomes) {
    // Scheduled validation re-runs cover ~50 bars and produce absurd
    // metrics on a handful of trades; screen by sample size, not source.
    const tradesPerRun = Number(outcome.total_trades || 0) / Math.max(1, Number(outcome.run_count || 1));
    if (tradesPerRun < minTrades) {
      state.hiddenVariants += 1;
      continue;
    }
    const name = outcome.strategy || "—";
    if (!groups.has(name)) {
      groups.set(name, { name, variants: [], instruments: new Set(), runs: 0, latest: "" });
    }
    const g = groups.get(name);
    g.variants.push(outcome);
    if (outcome.instrument) g.instruments.add(outcome.instrument);
    g.runs += Number(outcome.run_count || 0);
    const created = String(outcome.latest_created_at || "");
    if (created > g.latest) g.latest = created;
  }
  const strategies = [];
  for (const g of groups.values()) {
    g.variants.sort((a, b) => metricValue(b, metric) - metricValue(a, metric));
    g.best = g.variants[0];
    g.bestValue = metricValue(g.best, metric);
    g.live = state.liveStrategies.includes(g.name);
    strategies.push(g);
  }
  strategies.sort((a, b) => b.bestValue - a.bestValue || b.runs - a.runs);
  return strategies;
}

function selectedStrategyGroup() {
  return buildStrategies().find((g) => g.name === state.selectedStrategy) || null;
}

// ---------- data loading ----------

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
    const data = await api("/talim/operator/backtests/outcomes?limit=500&exclude_triggered_by=node");
    const outcomes = data.outcomes || [];
    const form = document.getElementById("backtests-filter");
    setSelectOptions(form.instrument, uniqueSorted(outcomes.map((o) => o.instrument)), "All instruments");
    setSelectOptions(form.timeframe, uniqueSorted(outcomes.map((o) => o.timeframe)), "All bars");
    form.instrument.value = state.filters.instrument;
    form.timeframe.value = state.filters.timeframe;
    state.filterOptionsLoaded = true;
  } catch (_) {
    // Keep static "All" dropdowns if the user is not signed in yet or the API fails.
  }
}

async function refreshLiveStrategies() {
  if (!state.authenticated) return;
  try {
    const data = await api("/talim/operator/strategies");
    state.liveStrategies = data.active || [];
  } catch (_) {
    state.liveStrategies = [];
  }
}

async function refreshAll() {
  document.getElementById("last-refresh").textContent = new Date().toISOString().replace("T", " ").replace(/\..*/, "") + " UTC";
  const body = document.getElementById("rankings-body");
  clear(body);
  body.appendChild(el("div", { class: "muted", text: "Loading strategy results…" }));
  try {
    if (!state.filterOptionsLoaded) await refreshFilterOptions();
    await refreshLiveStrategies();
    const query = buildQuery({
      instrument: state.filters.instrument,
      timeframe: state.filters.timeframe,
      since: sinceTimestamp(state.filters.period),
      // Scheduled validation re-runs are health checks on ~50-bar windows,
      // not comparable backtest results; keep them out of rankings.
      exclude_triggered_by: "node",
      limit: 500,
    });
    const data = await api("/talim/operator/backtests/outcomes" + query);
    state.outcomes = data.outcomes || [];
    if (state.selectedStrategy && !state.outcomes.some((o) => o.strategy === state.selectedStrategy)) {
      state.selectedStrategy = null;
      state.selectedVariantKey = null;
    }
    renderAll();
  } catch (err) {
    clear(body);
    const msg = err.status === 401 ? "Sign in first to view strategy results." : err.message;
    body.appendChild(el("div", { class: "error", text: msg }));
  }
}

function renderAll() {
  renderRankings();
  renderVariants();
  renderDetail();
}

// ---------- views ----------

function showView(name) {
  state.activeView = name;
  document.querySelectorAll(".bt-view").forEach((view) => view.classList.toggle("active", view.id === `view-${name}`));
  document.querySelectorAll(".mobile-tabs .tab").forEach((tab) => tab.classList.toggle("active", tab.dataset.view === name));
  window.scrollTo({ top: 0 });
}

function livePill() {
  return el("span", { class: "pill ok live-pill", text: "LIVE" });
}

function rankBadge(i) {
  return el("span", { class: `rank-badge${i === 0 ? " top" : ""}`, text: `#${i + 1}` });
}

function metricBar(value, maxAbs) {
  const scale = maxAbs > 0 ? Math.min(1, Math.abs(value) / maxAbs) : 0;
  return el("div", { class: "rank-bar" }, [
    el("div", {
      class: `rank-bar-fill ${value >= 0 ? "pos" : "neg"}`,
      style: `width: ${Math.max(2, scale * 100)}%`,
    }),
  ]);
}

function renderRankings() {
  const body = document.getElementById("rankings-body");
  clear(body);
  const strategies = buildStrategies();
  if (!strategies.length) {
    body.appendChild(el("div", { class: "panel empty-state" }, [
      el("h2", { text: "No strategy results yet" }),
      el("p", { class: "muted", text: "When Talim records or imports backtests, ranked strategies will appear here." }),
      state.hiddenVariants
        ? el("p", { class: "muted", text: `${state.hiddenVariants} low-sample variations hidden — set sample filter to All to show them.` })
        : null,
    ]));
    return;
  }
  const metric = state.filters.sort;
  const maxAbs = Math.max(...strategies.map((g) => Math.abs(g.bestValue)));
  strategies.forEach((g, i) => {
    const selected = g.name === state.selectedStrategy;
    body.appendChild(el("article", { class: `run-card rank-card${selected ? " selected" : ""}`, onClick: () => selectStrategy(g.name) }, [
      el("div", { class: "run-card-head" }, [
        el("div", { class: "rank-title" }, [
          rankBadge(i),
          el("strong", { text: g.name }),
          g.live ? livePill() : null,
        ]),
        el("span", { class: `pill ${pnlClass(g.bestValue)}`, text: METRICS[metric].fmt(g.bestValue) }),
      ]),
      metricBar(g.bestValue, maxAbs),
      el("div", { class: "metric-grid rank-metrics" }, [
        metric4("Best Sharpe", fmtNum(bestOf(g, "sharpe_ratio"), 2)),
        metric4("Best P&L", fmtSigned(bestOf(g, "net_pnl")), pnlClass(bestOf(g, "net_pnl"))),
        metric4("Win rate", fmtPct(bestOf(g, "win_rate"))),
        metric4("Worst DD", fmtSigned(worstOf(g, "max_drawdown")), "pnl-neg"),
      ]),
      el("div", { class: "muted rank-meta", text:
        `${g.variants.length} variation${g.variants.length === 1 ? "" : "s"} · ` +
        `${Array.from(g.instruments).join(", ") || "—"} · ${g.runs} runs · latest ${fmtDate(g.latest)}` }),
    ]));
  });
  if (state.hiddenVariants) {
    body.appendChild(el("div", { class: "muted hidden-note", text:
      `${state.hiddenVariants} low-sample variation${state.hiddenVariants === 1 ? "" : "s"} hidden (e.g. scheduled validation re-runs). Set sample filter to All to show them.` }));
  }
}

function bestOf(group, key) {
  return Math.max(...group.variants.map((v) => metricValue(v, key)));
}

function worstOf(group, key) {
  return Math.min(...group.variants.map((v) => metricValue(v, key)));
}

function metric4(label, value, cls) {
  return el("div", { class: "metric" }, [
    el("span", { class: "muted", text: label }),
    el("strong", { class: cls || "", text: value }),
  ]);
}

function selectStrategy(name) {
  state.selectedStrategy = name;
  state.selectedVariantKey = null;
  renderAll();
  showView("variants");
}

function backButton(label, view) {
  return el("button", { type: "button", class: "compact back-btn", text: label, onClick: (ev) => { ev.stopPropagation(); showView(view); } });
}

function paramChips(params) {
  const entries = Object.entries(params || {});
  if (!entries.length) return el("div", { class: "param-chips muted", text: "default params" });
  return el("div", { class: "param-chips" }, entries.slice(0, 8).map(([k, v]) => el("span", { class: "chip", text: `${k}: ${v}` })));
}

function renderVariants() {
  const body = document.getElementById("variants-body");
  clear(body);
  const group = selectedStrategyGroup();
  if (!group) {
    body.appendChild(el("div", { class: "panel" }, [el("p", { class: "muted", text: "Pick a strategy in Rankings first." })]));
    return;
  }
  const metric = state.filters.sort;
  body.appendChild(el("div", { class: "panel variants-head" }, [
    el("div", { class: "panel-title-row" }, [
      el("div", { class: "rank-title" }, [
        el("h2", { text: group.name }),
        group.live ? livePill() : null,
      ]),
      backButton("← Rankings", "rankings"),
    ]),
    el("div", { class: "muted", text:
      `${group.variants.length} variation${group.variants.length === 1 ? "" : "s"} ranked by ${METRICS[metric].label.toLowerCase()}` }),
  ]));
  group.variants.forEach((outcome, i) => {
    const selected = outcome.key === state.selectedVariantKey;
    body.appendChild(el("article", { class: `run-card${selected ? " selected" : ""}`, onClick: () => selectVariant(outcome.key) }, [
      el("div", { class: "run-card-head" }, [
        el("div", { class: "rank-title" }, [
          rankBadge(i),
          el("strong", { text: `${outcome.instrument || "—"} · ${outcome.timeframe || "—"}` }),
        ]),
        el("span", { class: `pill ${pnlClass(metricValue(outcome, metric))}`, text: METRICS[metric].fmt(metricValue(outcome, metric)) }),
      ]),
      paramChips(outcome.params),
      el("div", { class: "metric-grid rank-metrics" }, [
        metric4("Sharpe", fmtNum(outcome.sharpe_ratio, 2)),
        metric4("P&L", fmtSigned(outcome.net_pnl), pnlClass(outcome.net_pnl)),
        metric4("Win rate", fmtPct(outcome.win_rate)),
        metric4("Max DD", fmtSigned(outcome.max_drawdown), pnlClass(outcome.max_drawdown)),
      ]),
      el("div", { class: "muted rank-meta", text:
        `${outcome.total_trades ?? "—"} trades · ${outcome.run_count} run${outcome.run_count === 1 ? "" : "s"} · latest ${fmtDate(outcome.latest_created_at)}` }),
    ]));
  });
}

function selectVariant(key) {
  state.selectedVariantKey = key;
  renderVariants();
  renderDetail();
  showView("detail");
}

function renderDetail() {
  const body = document.getElementById("detail-body");
  clear(body);
  const outcome = state.outcomes.find((o) => o.key === state.selectedVariantKey);
  body.appendChild(el("div", { class: "panel-title-row" }, [
    el("h2", { text: "Variation detail" }),
    outcome ? backButton("← Variations", "variants") : null,
  ]));
  if (!outcome) {
    body.appendChild(el("p", { class: "muted", text: "Pick a variation first." }));
    return;
  }
  const isLive = state.liveStrategies.includes(outcome.strategy);
  body.appendChild(el("div", { class: "rank-title" }, [
    el("h3", { text: `${outcome.strategy} · ${outcome.instrument} · ${outcome.timeframe || "—"}` }),
    isLive ? livePill() : el("span", { class: "pill", text: "not deployed" }),
  ]));
  body.appendChild(paramChips(outcome.params));
  body.appendChild(el("div", { class: "metric-grid detail-metrics" }, [
    metric4("Total P&L (pts)", fmtSigned(outcome.net_pnl), pnlClass(outcome.net_pnl)),
    metric4("Avg P&L (pts)", fmtSigned(outcome.avg_net_pnl), pnlClass(outcome.avg_net_pnl)),
    metric4("Sharpe (per-trade)", fmtNum(outcome.sharpe_ratio, 3)),
    metric4("Best Sharpe (per-trade)", fmtNum(outcome.best_sharpe, 3)),
    metric4("Sortino (per-trade)", fmtNum(outcome.sortino_ratio, 3)),
    metric4("Profit factor", fmtNum(outcome.profit_factor, 3)),
    metric4("Max DD (pts)", fmtSigned(outcome.max_drawdown), pnlClass(outcome.max_drawdown)),
    metric4("Win rate", fmtPct(outcome.win_rate)),
    metric4("Trades", outcome.total_trades == null ? "—" : String(outcome.total_trades)),
    metric4("Runs", String(outcome.run_count)),
  ]));
  body.appendChild(sizingContextPanel(outcome));
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

function sizingContextPanel(outcome) {
  const panel = el("div", { class: "sizing-context" }, [
    el("h4", { text: "Sizing context" }),
    el("p", { class: "muted", text:
      "Metrics above are per-trade / points at the sizing used when the run was recorded " +
      "(default: fixed qty 1 on $100k). Annualised return depends on how the strategy is sized " +
      "in production — Sharpe stays roughly constant across sizings; expected return ≈ Sharpe × " +
      "chosen annualised volatility." }),
  ]);
  const scenarios = sizingScenariosFor(outcome);
  if (scenarios) {
    const grid = el("div", { class: "metric-grid sizing-scenarios" });
    for (const row of scenarios.rows) {
      grid.appendChild(el("div", { class: "metric" }, [
        el("span", { class: "muted", text: row.label }),
        el("strong", { class: row.cls || "", text: row.value }),
      ]));
    }
    panel.appendChild(el("h5", { text: scenarios.title }));
    panel.appendChild(grid);
    if (scenarios.note) {
      panel.appendChild(el("p", { class: "muted small-note", text: scenarios.note }));
    }
  } else {
    panel.appendChild(el("p", { class: "muted small-note", text:
      "Sizing sweep not on file for this variation yet. Combined-book sizing figures are in " +
      "STRATEGY_SEARCH_PROGRESS.md." }));
  }
  return panel;
}

// Measured sizing sweeps from tonight's run_portfolio_backtest.py sweep
// (US500.proxy 1d, per-bar costs, in-sample 2015-2024). Keyed by strategy so
// per-leg detail views can show the risk-per-trade table without re-running.
// Extend as more sweeps are recorded.
const SIZING_SWEEP_LIBRARY = {
  "US500.proxy|1d|momentum-US500": {
    title: "Sized in-sample scenarios (2015–2024, atr-high gate)",
    rows: [
      { label: "1% risk/trade — Net P&L", value: "+$20,347" },
      { label: "1% — Ann Sharpe", value: "0.53" },
      { label: "1% — Max DD", value: "−6.1%", cls: "pnl-neg" },
      { label: "2% — Net P&L", value: "≈ +$41k" },
      { label: "2% — Max DD (approx)", value: "≈ −12%", cls: "pnl-neg" },
    ],
    note: "Approx linear scaling in risk-per-trade. Live regime: atr-high.",
  },
  "US500.proxy|1d|rsi2-reversion": {
    title: "Sized in-sample scenarios (2015–2024, atr-low gate)",
    rows: [
      { label: "1% risk/trade — Net P&L", value: "+$13,035" },
      { label: "1% — Ann Sharpe", value: "0.67" },
      { label: "1% — Max DD", value: "−2.6%", cls: "pnl-neg" },
      { label: "2% — Net P&L", value: "≈ +$26k" },
      { label: "2% — Max DD (approx)", value: "≈ −5%", cls: "pnl-neg" },
    ],
    note: "Approx linear scaling in risk-per-trade. Live regime: atr-low.",
  },
  "US500.proxy|1d|ibs-reversion": {
    title: "Sized in-sample scenarios (2015–2024, ungated)",
    rows: [
      { label: "1% risk/trade — Net P&L", value: "+$13,673" },
      { label: "1% — Ann Sharpe", value: "0.74" },
      { label: "1% — Max DD", value: "−2.9%", cls: "pnl-neg" },
      { label: "2% — Net P&L", value: "≈ +$27k" },
      { label: "2% — Max DD (approx)", value: "≈ −6%", cls: "pnl-neg" },
    ],
    note: "Validated survivor; not yet in live config.",
  },
};

function sizingScenariosFor(outcome) {
  const key = `${outcome.instrument || ""}|${outcome.timeframe || ""}|${outcome.strategy || ""}`;
  return SIZING_SWEEP_LIBRARY[key] || null;
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

// ---------- auth + events ----------

function syncAuthUi() {
  const auth = document.getElementById("auth-state");
  const btn = document.getElementById("signin-btn");
  auth.textContent = state.authenticated ? "Signed in" : "Locked";
  auth.className = state.authenticated ? "auth-unlocked" : "auth-locked";
  btn.hidden = state.authenticated;
}

function bindEvents() {
  document.getElementById("signin-btn").addEventListener("click", async () => {
    const secret = await TalimUI.promptSecret();
    if (!secret) return;
    try {
      await loginWithSecret(secret);
      syncAuthUi();
      await refreshFilterOptions();
      refreshAll();
    } catch (err) {
      TalimUI.toast(err.message || "Sign in failed", "error");
    }
  });
  document.getElementById("refresh-btn").addEventListener("click", refreshAll);
  document.getElementById("backtests-filter").addEventListener("submit", (ev) => {
    ev.preventDefault();
    const f = ev.target;
    state.filters = {
      instrument: f.instrument.value,
      timeframe: f.timeframe.value,
      sort: f.sort.value,
      period: f.period.value,
      min_trades: f.min_trades.value,
    };
    refreshAll();
  });
  document.getElementById("toggle-filters").addEventListener("click", () => {
    document.getElementById("backtests-filter").classList.toggle("open");
  });
  document.querySelectorAll(".mobile-tabs .tab").forEach((tab) => tab.addEventListener("click", () => showView(tab.dataset.view)));
}

document.addEventListener("DOMContentLoaded", async () => {
  bindEvents();
  await refreshSession();
  syncAuthUi();
  await refreshFilterOptions();
  refreshAll();
});
