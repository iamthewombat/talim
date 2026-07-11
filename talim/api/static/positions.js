"use strict";

const state = {
  authenticated: false,
  selectedId: null,
  dashboard: null,
  chartData: null,
  chartError: null,
  chart: null,
  candleSeries: null,
  emaFastSeries: null,
  emaSlowSeries: null,
  priceLines: [],
  refreshing: false,
};

function clear(node) { while (node.firstChild) node.removeChild(node.firstChild); }
function asNumber(v) { const n = Number(v); return Number.isFinite(n) ? n : null; }
function fmtNum(v, digits = 2) { const n = asNumber(v); return n == null ? "—" : n.toFixed(digits); }
function fmtSigned(v, digits = 2) { const n = asNumber(v); return n == null ? "—" : `${n >= 0 ? "+" : ""}${n.toFixed(digits)}`; }
function pnlClass(v) { const n = asNumber(v); return n == null ? "" : (n >= 0 ? "pnl-pos" : "pnl-neg"); }
function fmtTs(value) { return value ? String(value).slice(0, 19).replace("T", " ") : "—"; }
function chartTime(value) { const ms = Date.parse(value); return Number.isFinite(ms) ? Math.floor(ms / 1000) : null; }

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

async function api(path, options = {}) {
  const headers = Object.assign({}, options.headers || {});
  if (options.body && !headers["Content-Type"]) headers["Content-Type"] = "application/json";
  const resp = await fetch(path, Object.assign({}, options, { headers, credentials: "same-origin" }));
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

async function refreshSession() {
  try {
    const body = await api("/talim/auth/session");
    state.authenticated = !!body.authenticated;
  } catch (_) { state.authenticated = false; }
}

async function loginWithSecret(secret) {
  await api("/talim/auth/login", { method: "POST", body: JSON.stringify({ secret }) });
  state.authenticated = true;
}

function syncAuthUi() {
  const auth = document.getElementById("auth-state");
  const signin = document.getElementById("signin-btn");
  if (!state.authenticated) {
    auth.textContent = "Locked"; auth.className = "auth-locked"; signin.hidden = false;
  } else {
    auth.textContent = "Signed in"; auth.className = "auth-unlocked"; signin.hidden = true;
  }
}

function kv(rows) {
  const dl = el("dl", { class: "kv signal-kv" });
  for (const [k, v, cls] of rows) {
    dl.appendChild(el("dt", { text: k }));
    dl.appendChild(el("dd", { text: v == null ? "—" : String(v), class: cls || "" }));
  }
  return dl;
}

function renderSummary() {
  const body = document.getElementById("summary-body");
  const pill = document.getElementById("source-pill");
  clear(body);
  const s = (state.dashboard && state.dashboard.summary) || {};
  pill.textContent = s.pricefeed_connected ? "pricefeed live" : "pricefeed offline";
  pill.className = `pill ${s.pricefeed_connected ? "ok" : "bad"}`;
  body.appendChild(kv([
    ["positions", s.position_count],
    ["live mark P&L", fmtSigned(s.mark_open_pnl), pnlClass(s.mark_open_pnl)],
    ["broker P&L", fmtSigned(s.broker_open_pnl), pnlClass(s.broker_open_pnl)],
    ["exchange", `${s.exchange_name || "—"} / ${s.exchange_mode || "—"}`],
    ["timeframe", s.timeframe],
    ["updated", fmtTs(s.updated_at)],
  ]));
}

function renderPositions() {
  const body = document.getElementById("positions-body");
  clear(body);
  const positions = (state.dashboard && state.dashboard.positions) || [];
  if (!positions.length) {
    body.appendChild(el("div", { class: "muted", text: "No open positions." }));
    return;
  }
  const table = el("table");
  table.appendChild(el("thead", null, el("tr", null, ["instrument", "side", "qty", "entry", "mark", "P&L", "source"].map((h) => el("th", { text: h })))));
  const tbody = el("tbody");
  for (const p of positions) {
    const id = String(p.position_id || "");
    const row = el("tr", { class: `clickable ${id === state.selectedId ? "selected" : ""}`, onclick: () => selectPosition(id) });
    row.appendChild(el("td", { text: p.instrument || "—" }));
    row.appendChild(el("td", { text: p.side || "—" }));
    row.appendChild(el("td", { text: fmtNum(p.qty, 2) }));
    row.appendChild(el("td", { text: fmtNum(p.entry_price, 2) }));
    row.appendChild(el("td", { text: fmtNum(p.mark_price, 2) }));
    row.appendChild(el("td", { text: fmtSigned(p.mark_open_pnl), class: pnlClass(p.mark_open_pnl) }));
    row.appendChild(el("td", { text: p.pnl_source || "—" }));
    tbody.appendChild(row);
  }
  table.appendChild(tbody);
  body.appendChild(table);
}

function renderDetail() {
  const body = document.getElementById("position-detail");
  clear(body);
  const p = selectedPosition();
  if (!p) { body.textContent = "Select a position…"; return; }
  body.appendChild(kv([
    ["position id", p.position_id],
    ["instrument", p.instrument],
    ["side", p.side],
    ["quantity", fmtNum(p.qty, 2)],
    ["entry", fmtNum(p.entry_price, 2)],
    ["bid / offer", `${fmtNum(p.bid, 2)} / ${fmtNum(p.offer, 2)}`],
    ["mark", fmtNum(p.mark_price, 2)],
    ["live mark P&L", fmtSigned(p.mark_open_pnl), pnlClass(p.mark_open_pnl)],
    ["broker P&L", fmtSigned(p.broker_open_pnl), pnlClass(p.broker_open_pnl)],
    ["P&L source", p.pnl_source],
    ["entry time", fmtTs(p.entry_time)],
    ["strategy", p.strategy || "—"],
  ]));
}

function selectedPosition() {
  return ((state.dashboard && state.dashboard.positions) || []).find((p) => String(p.position_id || "") === state.selectedId) || null;
}

function aggregateCandles(rawCandles) {
  const byTime = new Map();
  for (const bar of rawCandles || []) {
    const time = chartTime(bar.time);
    const open = asNumber(bar.open);
    const high = asNumber(bar.high);
    const low = asNumber(bar.low);
    const close = asNumber(bar.close);
    if (time == null || [open, high, low, close].some((v) => v == null)) continue;
    const existing = byTime.get(time);
    if (!existing) {
      byTime.set(time, { time, open, high, low, close });
    } else {
      existing.high = Math.max(existing.high, high);
      existing.low = Math.min(existing.low, low);
      existing.close = close;
    }
  }
  return Array.from(byTime.values()).sort((a, b) => a.time - b.time);
}

function aggregateLineValues(rawValues) {
  const byTime = new Map();
  for (const point of rawValues || []) {
    const time = chartTime(point.time);
    const value = asNumber(point.value);
    if (time == null || value == null) continue;
    byTime.set(time, { time, value });
  }
  return Array.from(byTime.values()).sort((a, b) => a.time - b.time);
}

function seriesData(chartData) {
  const candles = aggregateCandles(chartData.candles);
  const lineValues = (name) => aggregateLineValues((((chartData.indicators || {})[name] || {}).values || []));
  return { candles, emaFast: lineValues("ema_fast"), emaSlow: lineValues("ema_slow") };
}

function addPriceLine(series, price, title, color) {
  const value = asNumber(price);
  if (value == null) return;
  state.priceLines.push(series.createPriceLine({ price: value, color, lineWidth: 1, lineStyle: LightweightCharts.LineStyle.Dashed, axisLabelVisible: true, title }));
}

function chartHeight() {
  return Math.max(360, Math.min(560, Math.floor(window.innerHeight * 0.58)));
}

function destroyChart() {
  if (state.chart) { try { state.chart.remove(); } catch (_) { /* already gone */ } }
  state.chart = null;
  state.candleSeries = null;
  state.emaFastSeries = null;
  state.emaSlowSeries = null;
  state.priceLines = [];
}

function renderChartMessage(container, cls, text) {
  destroyChart();
  clear(container);
  container.appendChild(el("div", { class: cls, text }));
}

function renderChart(fit = true) {
  const container = document.getElementById("position-chart");
  const meta = document.getElementById("chart-meta");
  const warnings = document.getElementById("chart-warnings");
  clear(meta); clear(warnings);
  if (state.chartError) { renderChartMessage(container, "chart-empty error", state.chartError); return; }
  const data = state.chartData;
  if (!data) { renderChartMessage(container, "chart-empty", "Select a position…"); return; }
  meta.appendChild(el("span", { text: `${data.status} · ${data.source}` }));
  meta.appendChild(el("span", { text: `${data.timeframe} · ${(data.candles || []).length} candles` }));
  for (const warning of data.warnings || []) warnings.appendChild(el("div", { class: "warn", text: warning }));
  const { candles, emaFast, emaSlow } = seriesData(data);
  if (!candles.length) { renderChartMessage(container, "chart-empty", "No recent candles available."); return; }
  if (typeof LightweightCharts === "undefined") { renderChartMessage(container, "chart-empty error", "Chart library failed to load."); return; }
  try {
    // Reuse the chart instance across refreshes so the operator's zoom/pan
    // survives the 15s polling loop; only the series data is replaced.
    if (!state.chart) {
      clear(container);
      state.chart = LightweightCharts.createChart(container, {
        width: container.clientWidth || 800,
        height: chartHeight(),
        layout: { background: { color: "#171a21" }, textColor: "#d7dbe0" },
        grid: { vertLines: { color: "#242a35" }, horzLines: { color: "#242a35" } },
        rightPriceScale: { borderColor: "#2a2f3a" },
        timeScale: { borderColor: "#2a2f3a", timeVisible: true },
      });
      state.candleSeries = state.chart.addCandlestickSeries({ upColor: "#3fb950", downColor: "#f85149", borderVisible: false, wickUpColor: "#3fb950", wickDownColor: "#f85149" });
      state.emaFastSeries = state.chart.addLineSeries({ color: "#4fa3ff", lineWidth: 1 });
      state.emaSlowSeries = state.chart.addLineSeries({ color: "#d29922", lineWidth: 1 });
      fit = true;
    }
    state.candleSeries.setData(candles);
    state.emaFastSeries.setData(emaFast);
    state.emaSlowSeries.setData(emaSlow);
    for (const line of state.priceLines) { try { state.candleSeries.removePriceLine(line); } catch (_) { /* stale */ } }
    state.priceLines = [];
    addPriceLine(state.candleSeries, data.levels && data.levels.entry, "entry", "#4fa3ff");
    addPriceLine(state.candleSeries, data.levels && data.levels.mark, "mark", "#d29922");
    addPriceLine(state.candleSeries, data.levels && data.levels.stop, "stop", "#f85149");
    addPriceLine(state.candleSeries, data.levels && data.levels.target, "target", "#3fb950");
    if (fit) state.chart.timeScale().fitContent();
  } catch (err) {
    console.error("position chart render failed", err);
    renderChartMessage(container, "chart-empty error", `Chart render failed: ${err.message || err}`);
  }
}

async function selectPosition(id) {
  const changed = id !== state.selectedId;
  state.selectedId = id;
  if (changed) {
    state.chartData = null;
    state.chartError = null;
    destroyChart();
    renderPositions(); renderDetail(); renderChart();
  }
  try {
    state.chartData = await api(`/talim/operator/positions/${encodeURIComponent(id)}/chart?bars=240`);
    state.chartError = null;
  } catch (err) { state.chartError = err.message; }
  renderDetail();
  renderChart(changed);
}

async function refreshAll() {
  if (state.refreshing) return;
  state.refreshing = true;
  try {
    await refreshSession(); syncAuthUi();
    if (!state.authenticated) { renderLocked(); return; }
    state.dashboard = await api("/talim/operator/positions/dashboard");
    const positions = state.dashboard.positions || [];
    if (!state.selectedId && positions.length) state.selectedId = String(positions[0].position_id || "");
    renderSummary(); renderPositions(); renderDetail();
    if (state.selectedId) await selectPosition(state.selectedId); else renderChart();
    document.getElementById("last-refresh").textContent = new Date().toLocaleTimeString();
  } catch (err) {
    renderFatal(err.message);
  } finally {
    state.refreshing = false;
  }
}

function renderLocked() {
  for (const id of ["summary-body", "positions-body", "position-detail"]) {
    const node = document.getElementById(id); clear(node); node.appendChild(el("div", { class: "warn", text: "Sign in with the Talim bridge secret to load positions." }));
  }
  renderChart();
}

function renderFatal(msg) {
  for (const id of ["summary-body", "positions-body", "position-detail"]) {
    const node = document.getElementById(id); clear(node); node.appendChild(el("div", { class: "error", text: msg }));
  }
}

document.getElementById("signin-btn").addEventListener("click", async () => {
  const secret = await TalimUI.promptSecret();
  if (!secret) return;
  try { await loginWithSecret(secret); syncAuthUi(); await refreshAll(); }
  catch (err) { TalimUI.toast(err.message || "Sign in failed", "error"); }
});
document.getElementById("refresh-btn").addEventListener("click", refreshAll);
document.getElementById("fit-chart-btn").addEventListener("click", () => {
  if (state.chart) state.chart.timeScale().fitContent(); else renderChart(true);
});
window.addEventListener("resize", () => {
  if (!state.chart) return;
  const container = document.getElementById("position-chart");
  state.chart.applyOptions({ width: container.clientWidth || 800, height: chartHeight() });
});
refreshAll();
setInterval(refreshAll, 15000);
