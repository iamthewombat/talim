"use strict";

const THREAD_ID = "cron-main";
const CHART_INITIAL_BEFORE = 160;
const CHART_INITIAL_AFTER = 60;
const CHART_MAX_BEFORE = 500;
const CHART_MAX_AFTER = 500;
const state = {
  authenticated: false,
  unlocked: false,
  signal: null,
  pending: null,
  chartData: null,
  chartError: null,
  chart: null,
  chartBefore: CHART_INITIAL_BEFORE,
  chartAfter: CHART_INITIAL_AFTER,
  chartFetchInFlight: false,
  resizeObserver: null,
};

function signalId() { return new URLSearchParams(window.location.search).get("signal"); }
function clear(node) { while (node.firstChild) node.removeChild(node.firstChild); }
function fmtNum(v, digits = 2) { return v == null || Number.isNaN(Number(v)) ? "—" : Number(v).toFixed(digits); }
function fmtTs(value) { return value ? String(value).slice(0, 19).replace("T", " ") : "—"; }
function asNumber(v) { const n = Number(v); return Number.isFinite(n) ? n : null; }
function chartTime(value) {
  if (typeof value === "number") return value;
  const ms = Date.parse(value);
  return Number.isFinite(ms) ? Math.floor(ms / 1000) : null;
}
function writesAllowed() { return state.authenticated && state.unlocked; }
function validationAllowed() { return !!(state.pending && state.pending.validation && state.pending.validation.approval_allowed); }
function isCurrent() { return !!(state.pending && state.signal && state.pending.signal_id === state.signal.signal_id); }

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
  if (!resp.ok) throw new Error((body && body.detail) || `HTTP ${resp.status}`);
  return body;
}

async function refreshSession() {
  try {
    const body = await api("/talim/auth/session");
    state.authenticated = !!body.authenticated;
    if (!state.authenticated) state.unlocked = false;
  } catch (_) { state.authenticated = false; state.unlocked = false; }
}

async function loginWithSecret(secret) {
  await api("/talim/auth/login", { method: "POST", body: JSON.stringify({ secret }) });
  state.authenticated = true;
  state.unlocked = false;
}

function syncAuthUi() {
  const auth = document.getElementById("auth-state");
  const signin = document.getElementById("signin-btn");
  const unlock = document.getElementById("unlock-btn");
  const lock = document.getElementById("lock-btn");
  if (!state.authenticated) {
    auth.textContent = "Locked"; auth.className = "auth-locked";
    signin.hidden = false; unlock.hidden = true; lock.hidden = true;
  } else if (!state.unlocked) {
    auth.textContent = "Read-only"; auth.className = "auth-locked";
    signin.hidden = true; unlock.hidden = false; lock.hidden = true;
  } else {
    auth.textContent = "Writes enabled"; auth.className = "auth-unlocked";
    signin.hidden = true; unlock.hidden = true; lock.hidden = false;
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

function renderError(id, msg) {
  const node = document.getElementById(id);
  clear(node);
  node.appendChild(el("div", { class: "error", text: msg }));
}

function renderChartWarnings(warnings) {
  const node = document.getElementById("chart-warnings");
  clear(node);
  for (const warning of warnings || []) {
    node.appendChild(el("div", { class: "warn", text: warning }));
  }
}

function markerTimeForSignal(chartData) {
  const candles = chartData && chartData.candles || [];
  const visibleIndex = chartData && chartData.signal && chartData.signal.visible_index;
  if (Number.isInteger(visibleIndex) && candles[visibleIndex]) return chartTime(candles[visibleIndex].time);
  return chartTime(chartData && chartData.signal && chartData.signal.timestamp);
}

function nearestEmaCross(chartData) {
  const indicators = chartData.indicators || {};
  const fast = (indicators.ema_fast && indicators.ema_fast.values) || [];
  const slow = (indicators.ema_slow && indicators.ema_slow.values) || [];
  const slowByTime = new Map(slow.map((point) => [chartTime(point.time), asNumber(point.value)]));
  const points = fast
    .map((point) => ({ time: chartTime(point.time), fast: asNumber(point.value), slow: slowByTime.get(chartTime(point.time)) }))
    .filter((point) => point.time != null && point.fast != null && point.slow != null);
  const crosses = [];
  for (let i = 1; i < points.length; i += 1) {
    const prev = points[i - 1].fast - points[i - 1].slow;
    const curr = points[i].fast - points[i].slow;
    if ((prev <= 0 && curr > 0) || (prev >= 0 && curr < 0)) crosses.push({ time: points[i].time, bullish: curr > 0 });
  }
  if (!crosses.length) return null;
  const signalTime = markerTimeForSignal(chartData);
  if (signalTime == null) return crosses[crosses.length - 1];
  return crosses.reduce((best, cross) => (
    Math.abs(cross.time - signalTime) < Math.abs(best.time - signalTime) ? cross : best
  ), crosses[0]);
}

function chartSeriesData(chartData) {
  const candles = (chartData.candles || []).map((bar) => ({
    time: chartTime(bar.time),
    open: asNumber(bar.open),
    high: asNumber(bar.high),
    low: asNumber(bar.low),
    close: asNumber(bar.close),
  })).filter((bar) => bar.time != null && [bar.open, bar.high, bar.low, bar.close].every((v) => v != null));
  const lineValues = (name) => (((chartData.indicators || {})[name] || {}).values || [])
    .map((point) => ({ time: chartTime(point.time), value: asNumber(point.value) }))
    .filter((point) => point.time != null && point.value != null);
  return { candles, emaFast: lineValues("ema_fast"), emaSlow: lineValues("ema_slow") };
}

function chartPath(id, before = state.chartBefore, after = state.chartAfter) {
  return "/talim/operator/signals/" + encodeURIComponent(id)
    + "/chart?before=" + encodeURIComponent(before)
    + "&after=" + encodeURIComponent(after);
}

async function fetchChartWindow(before = state.chartBefore, after = state.chartAfter) {
  const id = signalId();
  if (!id) return null;
  const chart = await api(chartPath(id, before, after));
  state.chartBefore = before;
  state.chartAfter = after;
  state.chartData = chart;
  state.chartError = null;
  return chart;
}

function growWindow(value, max) {
  return Math.min(max, Math.max(value + 100, value * 2));
}

async function maybeLoadMoreChartData(logicalRange) {
  if (!logicalRange || state.chartFetchInFlight || !state.chartData) return;
  const candleCount = (state.chartData.candles || []).length;
  if (!candleCount) return;

  let nextBefore = state.chartBefore;
  let nextAfter = state.chartAfter;
  if (logicalRange.from < 12 && state.chartBefore < CHART_MAX_BEFORE) {
    nextBefore = growWindow(state.chartBefore, CHART_MAX_BEFORE);
  }
  if (logicalRange.to > candleCount - 12 && state.chartAfter < CHART_MAX_AFTER) {
    nextAfter = growWindow(state.chartAfter, CHART_MAX_AFTER);
  }
  if (nextBefore === state.chartBefore && nextAfter === state.chartAfter) return;

  const visibleTimeRange = state.chart && state.chart.timeScale().getVisibleRange();
  state.chartFetchInFlight = true;
  try {
    await fetchChartWindow(nextBefore, nextAfter);
    state.chartFetchInFlight = false;
    render({ chart: true, fitChart: false, visibleTimeRange });
  } catch (err) {
    state.chartError = err.message;
    renderDecisionContext();
  } finally {
    state.chartFetchInFlight = false;
  }
}

function addPriceLine(series, price, title, color) {
  const value = asNumber(price);
  if (value == null) return;
  series.createPriceLine({
    price: value,
    color,
    lineWidth: 1,
    lineStyle: LightweightCharts.LineStyle.Dashed,
    axisLabelVisible: true,
    title,
  });
}

function renderChart(options = {}) {
  const container = document.getElementById("signal-chart");
  const meta = document.getElementById("chart-meta");
  const fitChart = options.fit !== false;
  const visibleTimeRange = options.visibleTimeRange || null;
  clear(container);
  clear(meta);
  state.chart = null;

  if (state.chartError) {
    meta.textContent = "Chart unavailable";
    container.appendChild(el("div", { class: "chart-empty error", text: state.chartError }));
    renderChartWarnings([]);
    return;
  }
  const chartData = state.chartData;
  if (!chartData) {
    meta.textContent = "Loading chart…";
    container.appendChild(el("div", { class: "chart-empty", text: "Loading chart…" }));
    renderChartWarnings([]);
    return;
  }
  meta.appendChild(el("span", { text: `${chartData.status || "unknown"} · ${chartData.source || "no source"}` }));
  meta.appendChild(el("span", { text: `${chartData.timeframe || "?"} · ${(chartData.candles || []).length} candles` }));
  meta.appendChild(el("span", { text: `window ${state.chartBefore}/${state.chartAfter} bars` }));
  meta.appendChild(el("span", { text: state.chartFetchInFlight ? "Loading more…" : "Drag/pinch to pan + zoom" }));
  renderChartWarnings(chartData.warnings || []);

  const { candles, emaFast, emaSlow } = chartSeriesData(chartData);
  if (!candles.length) {
    container.appendChild(el("div", { class: "chart-empty", text: "No candles available around this signal yet." }));
    return;
  }
  if (typeof LightweightCharts === "undefined") {
    container.appendChild(el("div", { class: "chart-empty error", text: "TradingView Lightweight Charts failed to load." }));
    return;
  }

  const chart = LightweightCharts.createChart(container, {
    width: container.clientWidth || 720,
    height: window.matchMedia("(max-width: 640px)").matches ? 320 : 420,
    layout: {
      background: { type: LightweightCharts.ColorType.Solid, color: "#10131a" },
      textColor: "#d6dae5",
    },
    grid: {
      vertLines: { color: "rgba(255,255,255,0.06)" },
      horzLines: { color: "rgba(255,255,255,0.06)" },
    },
    rightPriceScale: { borderColor: "rgba(255,255,255,0.16)" },
    timeScale: { borderColor: "rgba(255,255,255,0.16)", timeVisible: true, secondsVisible: false },
    handleScroll: true,
    handleScale: true,
  });
  state.chart = chart;

  const candleSeries = chart.addCandlestickSeries({
    upColor: "#22c55e",
    downColor: "#ef4444",
    borderVisible: false,
    wickUpColor: "#22c55e",
    wickDownColor: "#ef4444",
  });
  candleSeries.setData(candles);
  chart.addLineSeries({ color: "#4fa3ff", lineWidth: 2, title: "EMA 8" }).setData(emaFast);
  chart.addLineSeries({ color: "#f5c542", lineWidth: 2, title: "EMA 21" }).setData(emaSlow);

  addPriceLine(candleSeries, chartData.levels && chartData.levels.entry, "Entry", "#4fa3ff");
  addPriceLine(candleSeries, chartData.levels && chartData.levels.stop, "Stop", "#ef4444");
  addPriceLine(candleSeries, chartData.levels && chartData.levels.target, "Target", "#22c55e");

  const markers = [];
  const side = String(chartData.signal && chartData.signal.side || "").toLowerCase();
  const signalTime = markerTimeForSignal(chartData);
  if (signalTime != null) {
    markers.push({
      time: signalTime,
      position: side === "short" ? "aboveBar" : "belowBar",
      color: side === "short" ? "#ef4444" : "#22c55e",
      shape: side === "short" ? "arrowDown" : "arrowUp",
      text: side === "short" ? "SHORT signal" : "LONG signal",
    });
  }
  const cross = nearestEmaCross(chartData);
  if (cross) {
    markers.push({
      time: cross.time,
      position: cross.bullish ? "belowBar" : "aboveBar",
      color: "#f5c542",
      shape: "circle",
      text: cross.bullish ? "EMA cross ↑" : "EMA cross ↓",
    });
  }
  candleSeries.setMarkers(markers.sort((a, b) => a.time - b.time));

  chart.timeScale().subscribeVisibleLogicalRangeChange((range) => {
    window.requestAnimationFrame(() => { maybeLoadMoreChartData(range); });
  });

  if (visibleTimeRange && visibleTimeRange.from != null && visibleTimeRange.to != null) {
    chart.timeScale().setVisibleRange(visibleTimeRange);
  } else if (fitChart) {
    chart.timeScale().fitContent();
  }
}

function formatSigned(value, suffix = "") {
  const n = asNumber(value);
  if (n == null) return "—";
  return `${n > 0 ? "+" : ""}${n.toFixed(2)}${suffix}`;
}

function approvalContext(validation, current) {
  if (!current) return { cls: "warn", title: "Historical signal", text: "This is not the current pending HITL signal. Use it for review only; approval/rejection is disabled." };
  if (!validation) return { cls: "warn", title: "Validation unavailable", text: "Talim has not returned a live validation result yet. Approval remains conservative." };
  if (validation.approval_allowed) return { cls: "ok", title: "Approval currently allowed", text: validation.reason || "Latest validation says this setup is still valid." };
  return { cls: "error", title: "Approval blocked", text: validation.reason || "Latest validation blocks approval. Rejection remains available for a current signal." };
}

function freshnessText(validation, current) {
  if (!current) return "Historical/not current";
  if (!validation) return "Unknown";
  const bars = validation.bars_since_signal == null ? "unknown bars" : `${validation.bars_since_signal} bars`;
  if (validation.status === "valid") return `Fresh enough: ${bars} since the source bar.`;
  if (validation.status === "stale") return `Stale: ${bars} since the source bar.`;
  return `${validation.status || "unknown"}: ${bars} since the source bar.`;
}

function movementText(validation) {
  if (!validation) return "No live movement check available.";
  const parts = [];
  if (validation.current_price != null) parts.push(`current ${fmtNum(validation.current_price, 4)}`);
  if (validation.movement_r != null) parts.push(`${formatSigned(validation.movement_r, "R")} from entry`);
  if (validation.movement_atr != null) parts.push(`${formatSigned(validation.movement_atr, " ATR")} from entry`);
  return parts.length ? parts.join(" · ") : "No price movement data available.";
}

function emaInterpretation(chartData, signal) {
  if (!chartData) return "Chart data is unavailable, so the EMA cross cannot be interpreted here.";
  const cross = nearestEmaCross(chartData);
  if (!cross) return "No EMA(8)/EMA(21) cross is visible in the returned chart window.";
  const direction = cross.bullish ? "bullish" : "bearish";
  const side = String((signal && signal.side) || (chartData.signal && chartData.signal.side) || "").toLowerCase();
  const supports = (side === "long" && cross.bullish) || (side === "short" && !cross.bullish);
  const timestamp = new Date(cross.time * 1000).toISOString();
  const plain = `EMA(8) crossed ${cross.bullish ? "above" : "below"} EMA(21) near ${fmtTs(timestamp)}.`;
  if (!side) return `${plain} That is a ${direction} momentum cue.`;
  return `${plain} That ${supports ? "supports" : "conflicts with"} the ${side.toUpperCase()} signal direction.`;
}

function renderDecisionContext() {
  const body = document.getElementById("decision-context-body");
  if (!body) return;
  clear(body);
  const s = state.signal;
  const current = isCurrent();
  const validation = current ? state.pending && state.pending.validation : null;
  const ctx = s && s.context || {};
  const chartSignal = state.chartData && state.chartData.signal || {};
  const verdict = approvalContext(validation, current);

  body.appendChild(el("div", { class: `decision-verdict ${verdict.cls}` }, [
    el("div", { class: "decision-verdict-title", text: verdict.title }),
    el("div", { class: "decision-verdict-text", text: verdict.text }),
  ]));

  const grid = el("div", { class: "decision-grid" });
  const addCard = (label, value) => grid.appendChild(el("div", { class: "decision-card" }, [
    el("div", { class: "decision-label", text: label }),
    el("div", { class: "decision-value", text: value == null ? "—" : String(value) }),
  ]));

  addCard("Freshness", freshnessText(validation, current));
  addCard("Price movement", movementText(validation));
  addCard("Regime", s && (s.regime || ctx.regime) || chartSignal.regime || "—");
  addCard("Approval gate", current && validation ? `${validation.approval_allowed ? "Allowed" : "Blocked"}: ${validation.reason || validation.status || "no reason returned"}` : verdict.text);
  addCard("EMA cross", emaInterpretation(state.chartData, s));
  addCard("Chart data", state.chartData ? `${state.chartData.source || "unknown source"} · ${(state.chartData.candles || []).length} candles · ${state.chartData.status || "unknown"}` : (state.chartError || "Loading…"));
  body.appendChild(grid);
}

function render(options = {}) {
  const drawChart = options.chart !== false;
  const s = state.signal;
  const p = state.pending;
  if (!s) return;
  document.getElementById("signal-pill").textContent = s.status || "—";
  document.getElementById("signal-pill").className = `pill ${s.status === "pending" ? "" : "muted"}`;

  const summary = document.getElementById("signal-summary");
  clear(summary);
  summary.appendChild(el("div", { class: "signal-side", text: `${String(s.side || "?").toUpperCase()} ${s.instrument || "?"}` }));
  summary.appendChild(el("div", { class: "signal-strategy", text: s.strategy || "—" }));
  summary.appendChild(el("div", { class: "signal-price", text: `@ ${fmtNum(s.entry_price, 4)}` }));
  summary.appendChild(el("div", { class: "muted", text: `stop ${fmtNum(s.stop, 4)} · target ${fmtNum(s.target, 4)}` }));

  const validation = p && p.validation;
  const validationBody = document.getElementById("validation-body");
  clear(validationBody);
  if (!isCurrent()) {
    validationBody.appendChild(el("div", { class: "warn", text: "This is not the current pending signal. Approval/rejection is disabled here." }));
  } else if (validation) {
    validationBody.appendChild(kv([
      ["status", validation.status],
      ["approval", validation.approval_allowed ? "allowed" : "blocked", validation.approval_allowed ? "pnl-pos" : "error"],
      ["reason", validation.reason],
      ["current price", fmtNum(validation.current_price, 4)],
      ["move from entry", validation.movement_r == null ? "—" : `${fmtNum(validation.movement_r, 2)}R`],
      ["move in ATR", validation.movement_atr == null ? "—" : `${fmtNum(validation.movement_atr, 2)} ATR`],
      ["bars since signal", validation.bars_since_signal],
      ["evaluated", fmtTs(validation.evaluated_at)],
    ]));
  } else {
    validationBody.appendChild(el("div", { class: "muted", text: "No live validation available." }));
  }

  const original = document.getElementById("original-body");
  clear(original);
  original.appendChild(kv([
    ["signal id", s.signal_id],
    ["strategy", s.strategy],
    ["instrument", s.instrument],
    ["side", s.side],
    ["entry", fmtNum(s.entry_price, 4)],
    ["stop", fmtNum(s.stop, 4)],
    ["target", fmtNum(s.target, 4)],
    ["source bar", fmtTs(s.source_bar_timestamp)],
    ["created", fmtTs(s.created_at)],
    ["updated", fmtTs(s.updated_at)],
    ["rationale", s.rationale],
  ]));

  const context = document.getElementById("context-body");
  clear(context);
  const ctx = s.context || {};
  context.appendChild(kv([
    ["regime", s.regime || ctx.regime],
    ["ATR", fmtNum(ctx.atr_current, 4)],
    ["ATR ratio", fmtNum(ctx.atr_ratio, 4)],
    ["last scan", fmtTs(ctx.last_scan_time)],
    ["latest validation", s.latest_validation_status],
    ["validation reason", s.latest_validation_reason],
  ]));

  const actions = document.getElementById("signal-actions");
  clear(actions);
  if (!writesAllowed()) actions.appendChild(el("div", { class: "warn", text: state.authenticated ? "Unlock writes to reject/approve." : "Sign in to reject/approve." }));
  if (isCurrent() && validation && !validation.approval_allowed) actions.appendChild(el("div", { class: "warn", text: "Approval is blocked by validation. Reject is still available to clear it." }));
  actions.appendChild(el("button", { type: "button", class: "ok big-action", text: "Approve", disabled: !writesAllowed() || !isCurrent() || !validationAllowed(), onClick: () => decide(true) }));
  actions.appendChild(el("button", { type: "button", class: "danger big-action", text: "Reject", disabled: !writesAllowed() || !isCurrent(), onClick: () => decide(false) }));

  if (drawChart) renderChart({ fit: options.fitChart !== false, visibleTimeRange: options.visibleTimeRange });
  renderDecisionContext();
}

async function refreshAll(options = {}) {
  const resetChartWindow = options.resetChartWindow !== false;
  if (resetChartWindow) {
    state.chartBefore = CHART_INITIAL_BEFORE;
    state.chartAfter = CHART_INITIAL_AFTER;
  }
  document.getElementById("last-refresh").textContent = new Date().toISOString().replace("T", " ").replace(/\..*/, "") + " UTC";
  const id = signalId();
  if (!id) {
    renderError("signal-summary", "No signal id in URL. Open /talim/dashboard/signal.html?signal=SIG-...");
    return;
  }
  try {
    const [detail, pending, chartResult] = await Promise.all([
      api("/talim/operator/signals/" + encodeURIComponent(id)),
      api("/talim/operator/pending?thread_id=" + encodeURIComponent(THREAD_ID)),
      fetchChartWindow(state.chartBefore, state.chartAfter)
        .then((chart) => ({ chart }))
        .catch((err) => ({ chartError: err.message })),
    ]);
    state.signal = detail.signal;
    state.pending = pending;
    state.chartData = chartResult.chart || null;
    state.chartError = chartResult.chartError || null;
    render({ chart: true, fitChart: options.fitChart !== false, visibleTimeRange: options.visibleTimeRange });
  } catch (err) {
    state.chartError = err.message;
    renderError("signal-summary", err.message);
    renderChart();
    renderDecisionContext();
  }
}

async function refreshLiveOnly() {
  document.getElementById("last-refresh").textContent = new Date().toISOString().replace("T", " ").replace(/\..*/, "") + " UTC";
  const id = signalId();
  if (!id) return;
  try {
    const [detail, pending] = await Promise.all([
      api("/talim/operator/signals/" + encodeURIComponent(id)),
      api("/talim/operator/pending?thread_id=" + encodeURIComponent(THREAD_ID)),
    ]);
    state.signal = detail.signal;
    state.pending = pending;
    render({ chart: false });
  } catch (_) {
    // Keep the operator's current chart interaction intact on transient refresh failures.
  }
}

async function decide(approved) {
  const id = signalId();
  const verb = approved ? "Approve" : "Reject";
  if (!confirm(`${verb} signal ${id}?`)) return;
  try {
    const result = await api("/talim/operator/decision", { method: "POST", body: JSON.stringify({ thread_id: THREAD_ID, approved, signal_id: id }) });
    if (result.last_action) alert(result.last_action);
    await refreshAll();
  } catch (err) { alert("Decision failed: " + err.message); }
}

function bind() {
  document.getElementById("refresh-btn").addEventListener("click", () => {
    const visibleTimeRange = state.chart && state.chart.timeScale().getVisibleRange();
    refreshAll({ resetChartWindow: false, fitChart: false, visibleTimeRange });
  });
  document.getElementById("fit-chart-btn").addEventListener("click", () => { if (state.chart) state.chart.timeScale().fitContent(); });
  document.getElementById("signin-btn").addEventListener("click", async () => {
    const secret = prompt("Paste TALIM_BRIDGE_SECRET once for this browser session:");
    if (!secret) return;
    try { await loginWithSecret(secret.trim()); syncAuthUi(); await refreshAll(); }
    catch (err) { alert(err.message); }
  });
  document.getElementById("unlock-btn").addEventListener("click", () => { if (confirm("Unlock write actions for this tab?")) { state.unlocked = true; syncAuthUi(); render({ chart: false }); } });
  document.getElementById("lock-btn").addEventListener("click", () => { state.unlocked = false; syncAuthUi(); render({ chart: false }); });
  if (window.ResizeObserver) {
    state.resizeObserver = new ResizeObserver(() => {
      const container = document.getElementById("signal-chart");
      if (state.chart && container) state.chart.applyOptions({ width: container.clientWidth });
    });
    state.resizeObserver.observe(document.getElementById("signal-chart"));
  }
}

document.addEventListener("DOMContentLoaded", async () => {
  bind();
  await refreshSession();
  syncAuthUi();
  await refreshAll();
  setInterval(refreshLiveOnly, 15000);
});
