"use strict";

const THREAD_ID = "cron-main";
const REFRESH_INTERVAL_MS = 15000;

const state = {
  authenticated: false,
  unlocked: false, // writes require an explicit per-tab unlock (task #17)
  timer: null,
  refreshPromise: null,
  halted: null,
  pendingSignalId: null,
  notifyEnabled: false,
  openBacktestRunId: null,
  strategyParams: { name: null, data: null, error: null },
  decisionsFilters: { instrument: "", strategy: "", limit: 20 },
  backtestsFilters: { strategy: "", instrument: "", limit: 25 },
};

async function refreshSession() {
  try {
    const resp = await fetch("/talim/auth/session", { credentials: "same-origin" });
    const body = await resp.json();
    state.authenticated = !!body.authenticated;
    if (!state.authenticated) state.unlocked = false;
  } catch (_) {
    state.authenticated = false;
    state.unlocked = false;
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
  if (!resp.ok) {
    const err = new Error((body && body.detail) || `HTTP ${resp.status}`);
    err.status = resp.status;
    err.body = body;
    throw err;
  }
  state.authenticated = true;
  state.unlocked = false;
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
    err.body = body;
    if (resp.status === 401 && state.authenticated) {
      // The session cookie expired mid-session: drop back to the locked
      // header state instead of showing "Unlocked" next to 401 panels.
      state.authenticated = false;
      state.unlocked = false;
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
      else if (k.startsWith("on") && typeof v === "function") {
        node.addEventListener(k.slice(2).toLowerCase(), v);
      } else if (v === true) {
        node.setAttribute(k, "");
      } else if (v != null && v !== false) {
        node.setAttribute(k, String(v));
      }
    }
  }
  if (children) {
    for (const c of [].concat(children)) {
      if (c == null) continue;
      node.appendChild(typeof c === "string" ? document.createTextNode(c) : c);
    }
  }
  return node;
}

function clear(node) { while (node.firstChild) node.removeChild(node.firstChild); }

function fmtNum(v, digits) {
  if (v == null || Number.isNaN(v)) return "—";
  const d = digits == null ? 2 : digits;
  return Number(v).toFixed(d);
}

function fmtSigned(v) {
  if (v == null || Number.isNaN(v)) return "—";
  const n = Number(v);
  const s = (n >= 0 ? "+" : "") + n.toFixed(2);
  return s;
}

function pnlClass(v) {
  if (v == null || Number.isNaN(v)) return "";
  return Number(v) >= 0 ? "pnl-pos" : "pnl-neg";
}

function buildTradeRows(decisions) {
  const entriesById = new Map();
  for (const r of decisions) {
    if (r.signal_type === "enter") entriesById.set(r.id, r);
  }
  const pairedEntryIds = new Set();
  const trades = [];

  for (const r of decisions) {
    if (r.signal_type === "enter") continue;
    if (r.signal_type !== "exit") {
      trades.push({ kind: "decision", row: r, timestamp: r.timestamp || r.created_at });
      continue;
    }

    const entry = (r.entry_decision_id != null && entriesById.get(r.entry_decision_id)) || null;
    if (entry) pairedEntryIds.add(entry.id);
    const qty = Number(r.qty) || (entry && Number(entry.qty)) || 1;
    const direction = r.side === "short" ? -1 : 1;
    const entryPrice = entry ? Number(entry.entry_price) : null;
    const exitPrice = Number(r.entry_price);
    const points = Number.isFinite(entryPrice) && Number.isFinite(exitPrice)
      ? (exitPrice - entryPrice) * direction
      : (Number.isFinite(Number(r.pnl)) && qty ? Number(r.pnl) / qty : null);
    trades.push({ kind: "trade", entry, exit: r, qty, points, timestamp: r.timestamp || r.created_at });
  }

  for (const e of entriesById.values()) {
    if (!pairedEntryIds.has(e.id)) trades.push({ kind: "open", entry: e, timestamp: e.timestamp || e.created_at });
  }

  return trades.sort((a, b) => String(b.timestamp || "").localeCompare(String(a.timestamp || "")));
}

function fmtTs(value) {
  if (!value) return "—";
  try { return new Date(value).toISOString().replace("T", " ").replace("Z", " UTC"); }
  catch (_) { return String(value); }
}

function fmtTsShort(value) {
  if (!value) return "—";
  try { return new Date(value).toISOString().slice(0, 19).replace("T", " "); }
  catch (_) { return String(value); }
}

function fmtAgo(value) {
  if (!value) return "";
  const ms = Date.parse(value);
  if (!Number.isFinite(ms)) return "";
  const s = Math.round((Date.now() - ms) / 1000);
  if (s < 0) return "";
  if (s < 60) return `${s}s ago`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 48) return `${h}h ago`;
  return `${Math.floor(h / 24)}d ago`;
}

function updateTitle() {
  let prefix = "";
  if (state.halted) prefix += "⏸ HALTED · ";
  if (state.pendingSignalId) prefix += "⏳ pending · ";
  document.title = prefix + "Talim Operator";
}

function maybeNotifyPending(signalId, signal) {
  if (!state.notifyEnabled || typeof Notification === "undefined" || Notification.permission !== "granted") return;
  const s = signal || {};
  const text = `${String(s.side || "?").toUpperCase()} ${s.instrument || "?"} @ ${fmtNum(s.entry_price, 4)} · ${s.strategy || "—"}`;
  try {
    const n = new Notification("Talim: pending HITL signal", { body: text, tag: "talim-pending-signal" });
    n.onclick = () => { window.focus(); n.close(); };
  } catch (_) { /* Notification constructor can throw on some platforms */ }
}

function renderError(node, err) {
  clear(node);
  const msg = err && err.status === 401
    ? "unauthorized — click Sign in and paste TALIM_BRIDGE_SECRET once"
    : (err && err.message) || "error";
  node.appendChild(el("div", { class: "error", text: msg }));
}

function writesAllowed() { return state.authenticated && state.unlocked; }

function requestedSignalId() {
  return new URLSearchParams(window.location.search).get("signal");
}

function validationText(v) {
  if (!v) return "—";
  return `${v.status || "unknown"} · approval ${v.approval_allowed ? "allowed" : "blocked"}`;
}

// ---------------------------------------------------------------------------
// Runtime status
// ---------------------------------------------------------------------------

async function refreshStatus() {
  const body = document.getElementById("status-body");
  const dot = document.getElementById("status-dot");
  const label = document.getElementById("status-label");
  try {
    const data = await api("/talim/operator/status");
    const rt = data.runtime || {};
    clear(body);

    const dl = el("dl", { class: "kv" });
    const pushRow = (k, v, cls) => {
      dl.appendChild(el("dt", { text: k }));
      dl.appendChild(el("dd", { text: v == null ? "—" : String(v), class: cls || "" }));
    };
    pushRow("exchange", `${rt.exchange_name || "?"} (${rt.exchange_mode || "?"})`);
    pushRow("pricefeed", `${rt.pricefeed_name || "?"} @ ${rt.pricefeed_timeframe || "?"}`);
    pushRow("pricefeed connected", rt.pricefeed_connected);
    pushRow("instruments", (rt.instruments || []).join(", ") || "—");
    pushRow("strategies", (rt.strategies || []).join(", ") || "—");
    pushRow("subscriptions", (rt.subscriptions || []).join(", ") || "—");
    pushRow("default qty", rt.default_qty);
    pushRow("open positions", rt.position_count);
    pushRow("account balance", rt.account_balance == null ? "—" : fmtNum(rt.account_balance));
    pushRow("open P&L", fmtSigned(rt.open_pnl), pnlClass(rt.open_pnl));
    pushRow("daily P&L", fmtSigned(rt.daily_pnl), pnlClass(rt.daily_pnl));
    body.appendChild(dl);

    const controls = el("div", { class: "inline-controls" });
    const haltBtn = el("button", {
      type: "button",
      class: data.halted ? "ok" : "danger",
      text: data.halted ? "Resume trading" : "HALT",
      disabled: !writesAllowed(),
      onClick: async () => {
        const ok = await TalimUI.confirm(
          data.halted ? "Resume trading?" : "HALT all trading?",
          { confirmLabel: data.halted ? "Resume trading" : "HALT", danger: !data.halted },
        );
        if (!ok) return;
        try {
          await api(data.halted ? "/talim/resume-trading" : "/talim/halt", { method: "POST", body: "{}" });
          TalimUI.toast(data.halted ? "Trading resumed" : "Trading HALTED", "ok");
          await refreshAll();
        } catch (err) { TalimUI.toast("Action failed: " + err.message, "error"); }
      },
    });
    controls.appendChild(haltBtn);
    body.appendChild(controls);

    state.halted = !!data.halted;
    updateTitle();
    if (data.halted) {
      dot.className = "dot bad";
      label.textContent = "HALTED";
    } else {
      dot.className = "dot ok";
      label.textContent = "running";
    }
  } catch (err) {
    dot.className = "dot unknown";
    label.textContent = "—";
    state.halted = null;
    updateTitle();
    renderError(body, err);
  }
}

// ---------------------------------------------------------------------------
// Pending HITL
// ---------------------------------------------------------------------------

function fetchPending() {
  return api("/talim/operator/pending?thread_id=" + encodeURIComponent(THREAD_ID));
}

async function refreshPending(pendingPromise) {
  const body = document.getElementById("pending-body");
  try {
    const data = await (pendingPromise || fetchPending());
    clear(body);

    const currentSignalId = data.pending_signal
      ? (data.signal_id || data.pending_signal.signal_id || "pending")
      : null;
    if (currentSignalId && currentSignalId !== state.pendingSignalId) {
      maybeNotifyPending(currentSignalId, data.pending_signal);
    }
    state.pendingSignalId = currentSignalId;
    updateTitle();

    if (!data.pending_signal) {
      body.appendChild(el("div", { class: "muted", text: data.last_action ? `no pending signal · last: ${data.last_action}` : "no pending signal" }));
      return;
    }
    const s = data.pending_signal;
    const dl = el("dl", { class: "kv" });
    const pushRow = (k, v) => {
      dl.appendChild(el("dt", { text: k }));
      dl.appendChild(el("dd", { text: v == null ? "—" : String(v) }));
    };
    if (data.signal_id || s.signal_id) pushRow("signal id", data.signal_id || s.signal_id);
    pushRow("instrument", s.instrument);
    pushRow("strategy", s.strategy);
    pushRow("side", s.side);
    pushRow("entry", fmtNum(s.entry_price, 4));
    pushRow("stop", fmtNum(s.stop, 4));
    pushRow("target", fmtNum(s.target, 4));
    if (s.rationale) pushRow("rationale", s.rationale);
    pushRow("paused", data.paused);
    if (data.validation || s.validation) {
      const v = data.validation || s.validation;
      pushRow("validation", `${v.status || "unknown"} · approval ${v.approval_allowed ? "allowed" : "blocked"}`);
      if (v.reason) pushRow("validation reason", v.reason);
      if (v.current_price != null) pushRow("current price", fmtNum(v.current_price, 4));
      if (v.movement_r != null) pushRow("move from entry", `${fmtNum(v.movement_r, 2)}R`);
      if (v.bars_since_signal != null) pushRow("bars since signal", v.bars_since_signal);
    }
    if (data.pending_notification) pushRow("notification", data.pending_notification);
    if (data.dashboard_url) pushRow("dashboard link", data.dashboard_url);
    body.appendChild(dl);

    const requestedSignal = requestedSignalId();
    if (requestedSignal && requestedSignal !== (data.signal_id || s.signal_id)) {
      body.appendChild(el("div", { class: "warn", text: `linked signal ${requestedSignal} is not the current pending signal` }));
    }

    const approvalAllowed = !(data.validation || s.validation) || (data.validation || s.validation).approval_allowed;
    if (!writesAllowed()) {
      body.appendChild(el("div", { class: "warn", text: "Writes are locked — click Unlock writes before approving or rejecting." }));
    } else if (!approvalAllowed) {
      body.appendChild(el("div", { class: "warn", text: "Approval is blocked by validation; reject remains available to clear the stale/invalid signal." }));
    }

    const controls = el("div", { class: "inline-controls" });
    const approve = el("button", {
      type: "button",
      class: "ok",
      text: "Approve",
      disabled: !writesAllowed() || !approvalAllowed,
      onClick: () => sendDecision(true, data.signal_id || s.signal_id),
    });
    const reject = el("button", {
      type: "button",
      class: "danger",
      text: "Reject",
      disabled: !writesAllowed(),
      onClick: () => sendDecision(false, data.signal_id || s.signal_id),
    });
    controls.appendChild(approve);
    controls.appendChild(reject);
    body.appendChild(controls);
  } catch (err) {
    renderError(body, err);
  }
}

async function sendDecision(approved, signalId) {
  const verb = approved ? "Approve" : "Reject";
  const suffix = signalId ? ` signal ${signalId}` : ` the pending signal on thread ${THREAD_ID}`;
  const ok = await TalimUI.confirm(`${verb}${suffix}?`, { confirmLabel: verb, danger: !approved });
  if (!ok) return;
  try {
    const result = await api("/talim/operator/decision", {
      method: "POST",
      body: JSON.stringify({ thread_id: THREAD_ID, approved, signal_id: signalId || null }),
    });
    TalimUI.toast(result.last_action || (approved ? "Signal approved" : "Signal rejected"), "ok");
    await refreshAll();
  } catch (err) { TalimUI.toast("Decision failed: " + err.message, "error"); }
}

// ---------------------------------------------------------------------------
// Signal detail
// ---------------------------------------------------------------------------

async function refreshSignalDetail(pendingPromise) {
  const panel = document.getElementById("panel-signal-detail");
  const body = document.getElementById("signal-detail-body");
  const signalId = requestedSignalId();
  if (!signalId) {
    panel.hidden = true;
    clear(body);
    return;
  }
  panel.hidden = false;
  try {
    const data = await api("/talim/operator/signals/" + encodeURIComponent(signalId));
    const s = data.signal || {};
    clear(body);

    const dl = el("dl", { class: "kv" });
    const pushRow = (k, v, cls) => {
      dl.appendChild(el("dt", { text: k }));
      dl.appendChild(el("dd", { text: v == null ? "—" : String(v), class: cls || "" }));
    };
    pushRow("signal id", s.signal_id);
    pushRow("status", s.status);
    pushRow("instrument", s.instrument);
    pushRow("strategy", s.strategy);
    pushRow("side", s.side);
    pushRow("entry", fmtNum(s.entry_price, 4));
    pushRow("stop", fmtNum(s.stop, 4));
    pushRow("target", fmtNum(s.target, 4));
    pushRow("source bar", fmtTs(s.source_bar_timestamp));
    pushRow("created", fmtTs(s.created_at));
    pushRow("updated", fmtTs(s.updated_at));
    pushRow("latest validation", validationText({
      status: s.latest_validation_status,
      approval_allowed: s.latest_validation_status === "valid",
    }));
    if (s.latest_validation_reason) pushRow("validation reason", s.latest_validation_reason);
    if (s.rationale) pushRow("rationale", s.rationale);
    const detailUrl = `/talim/dashboard/signal.html?signal=${encodeURIComponent(s.signal_id)}`;
    pushRow("signal page", detailUrl);
    if (s.dashboard_url) pushRow("dashboard link", s.dashboard_url);
    body.appendChild(dl);
    body.appendChild(el("div", { class: "inline-controls" }, [
      el("a", { class: "nav-link", href: detailUrl, text: "Open signal page" }),
    ]));

    const currentPending = await (pendingPromise || fetchPending());
    const isCurrent = currentPending.signal_id === signalId;
    if (!isCurrent) {
      body.appendChild(el("div", { class: "warn", text: "This signal is not the current pending HITL signal. Approval is unavailable from this detail view." }));
    } else if (currentPending.validation) {
      const v = currentPending.validation;
      const vdl = el("dl", { class: "kv detail" });
      const pushV = (k, val) => {
        vdl.appendChild(el("dt", { text: k }));
        vdl.appendChild(el("dd", { text: val == null ? "—" : String(val) }));
      };
      pushV("live validation", validationText(v));
      pushV("live reason", v.reason);
      pushV("current price", fmtNum(v.current_price, 4));
      pushV("move from entry", v.movement_r == null ? "—" : `${fmtNum(v.movement_r, 2)}R`);
      pushV("bars since signal", v.bars_since_signal);
      body.appendChild(vdl);
    }

    const controls = el("div", { class: "inline-controls" });
    controls.appendChild(el("button", { type: "button", text: "Refresh validation", onClick: refreshAll }));
    controls.appendChild(el("button", {
      type: "button", class: "ok", text: "Approve current signal",
      disabled: !writesAllowed() || !isCurrent || !(currentPending.validation && currentPending.validation.approval_allowed),
      onClick: () => sendDecision(true, signalId),
    }));
    controls.appendChild(el("button", {
      type: "button", class: "danger", text: "Reject current signal",
      disabled: !writesAllowed() || !isCurrent,
      onClick: () => sendDecision(false, signalId),
    }));
    body.appendChild(controls);
  } catch (err) {
    renderError(body, err);
  }
}

// ---------------------------------------------------------------------------
// Open positions
// ---------------------------------------------------------------------------

async function refreshPositions() {
  const body = document.getElementById("positions-body");
  try {
    const data = await api("/talim/operator/positions/dashboard");
    clear(body);
    const summary = data.summary || {};
    const positions = data.positions || [];
    body.appendChild(el("div", {
      class: "muted",
      text: `${summary.pricefeed_connected ? "pricefeed live" : "pricefeed offline"}`
        + ` · live mark P&L ${fmtSigned(summary.mark_open_pnl)}`
        + ` · broker P&L ${fmtSigned(summary.broker_open_pnl)}`,
    }));
    if (!positions.length) {
      body.appendChild(el("div", { class: "muted", text: "no open positions" }));
      return;
    }
    const table = el("table");
    const thead = el("thead");
    const headRow = el("tr");
    for (const h of ["instrument", "side", "qty", "entry", "mark", "stop", "target", "strategy", "P&L", "source"]) {
      headRow.appendChild(el("th", { text: h }));
    }
    thead.appendChild(headRow);
    table.appendChild(thead);
    const tbody = el("tbody");
    for (const p of positions) {
      const row = el("tr");
      row.appendChild(el("td", { text: p.instrument || "—" }));
      row.appendChild(el("td", { text: p.side || "—" }));
      row.appendChild(el("td", { text: fmtNum(p.qty, 4) }));
      row.appendChild(el("td", { text: fmtNum(p.entry_price, 4) }));
      row.appendChild(el("td", { text: fmtNum(p.mark_price, 4) }));
      row.appendChild(el("td", { text: fmtNum(p.stop, 4) }));
      row.appendChild(el("td", { text: fmtNum(p.target, 4) }));
      row.appendChild(el("td", { text: p.strategy || "—" }));
      row.appendChild(el("td", { text: fmtSigned(p.mark_open_pnl), class: pnlClass(p.mark_open_pnl) }));
      row.appendChild(el("td", { text: p.pnl_source || "—" }));
      tbody.appendChild(row);
    }
    table.appendChild(tbody);
    body.appendChild(table);
  } catch (err) { renderError(body, err); }
}

// ---------------------------------------------------------------------------
// Strategies
// ---------------------------------------------------------------------------

async function refreshStrategies() {
  const body = document.getElementById("strategies-body");
  try {
    const data = await api("/talim/operator/strategies");
    clear(body);
    const active = new Set(data.active || []);
    const available = data.available || [];
    if (!available.length) {
      body.appendChild(el("div", { class: "muted", text: "no strategies discovered" }));
      return;
    }
    const table = el("table");
    const thead = el("thead");
    const head = el("tr");
    for (const h of ["strategy", "state", "actions"]) head.appendChild(el("th", { text: h }));
    thead.appendChild(head);
    table.appendChild(thead);
    const tbody = el("tbody");
    for (const name of available) {
      const row = el("tr");
      const isActive = active.has(name);
      row.appendChild(el("td", { text: name }));
      row.appendChild(el("td", { text: isActive ? "active" : "inactive", class: isActive ? "pnl-pos" : "muted" }));
      const actionCell = el("td");
      actionCell.appendChild(el("button", {
        type: "button",
        class: "compact",
        text: state.strategyParams.name === name ? "Hide params" : "Params",
        onClick: () => toggleStrategyParams(name),
      }));
      actionCell.appendChild(document.createTextNode(" "));
      actionCell.appendChild(el("button", {
        type: "button",
        text: isActive ? "Disable" : "Enable",
        class: isActive ? "danger" : "ok",
        disabled: !writesAllowed(),
        onClick: () => toggleStrategy(name, !isActive),
      }));
      row.appendChild(actionCell);
      tbody.appendChild(row);
      if (state.strategyParams.name === name) {
        const cell = el("td", { colspan: 3 });
        cell.appendChild(renderStrategyParams());
        tbody.appendChild(el("tr", { class: "params-row" }, cell));
      }
    }
    table.appendChild(tbody);
    body.appendChild(table);
  } catch (err) { renderError(body, err); }
}

async function toggleStrategyParams(name) {
  if (state.strategyParams.name === name) {
    state.strategyParams = { name: null, data: null, error: null };
    await refreshStrategies();
    return;
  }
  state.strategyParams = { name, data: null, error: null };
  await refreshStrategies();
  try {
    const data = await api(`/talim/operator/strategies/${encodeURIComponent(name)}/params`);
    if (state.strategyParams.name === name) state.strategyParams = { name, data, error: null };
  } catch (err) {
    if (state.strategyParams.name === name) state.strategyParams = { name, data: null, error: err.message };
  }
  if (state.strategyParams.name === name) await refreshStrategies();
}

function renderStrategyParams() {
  const sp = state.strategyParams;
  if (sp.error) return el("div", { class: "error", text: sp.error });
  if (!sp.data) return el("div", { class: "muted", text: "loading params…" });
  const schema = sp.data.schema || [];
  const current = sp.data.current || {};
  if (!schema.length) return el("div", { class: "muted", text: "no declared params" });
  const table = el("table");
  const head = el("tr");
  for (const h of ["param", "current", "default", "constraints", "description"]) head.appendChild(el("th", { text: h }));
  table.appendChild(el("thead", null, head));
  const tbody = el("tbody");
  for (const spec of schema) {
    const constraints = spec.choices && spec.choices.length
      ? `one of ${spec.choices.join(", ")}`
      : [spec.min != null ? `min ${spec.min}` : null, spec.max != null ? `max ${spec.max}` : null]
          .filter(Boolean).join(" · ");
    const row = el("tr");
    row.appendChild(el("td", { text: spec.name }));
    row.appendChild(el("td", { text: current[spec.name] == null ? "—" : String(current[spec.name]) }));
    row.appendChild(el("td", { text: spec.default == null ? "—" : String(spec.default), class: "muted" }));
    row.appendChild(el("td", { text: constraints || "—", class: "muted" }));
    row.appendChild(el("td", { text: spec.description || "—", class: "muted" }));
    tbody.appendChild(row);
  }
  table.appendChild(tbody);
  return table;
}

async function toggleStrategy(name, enable) {
  const verb = enable ? "enable" : "disable";
  const ok = await TalimUI.confirm(
    `${enable ? "Enable" : "Disable"} strategy "${name}"?`,
    { confirmLabel: enable ? "Enable" : "Disable", danger: !enable },
  );
  if (!ok) return;
  try {
    await api(`/talim/operator/strategies/${encodeURIComponent(name)}/${verb}`, { method: "POST", body: "{}" });
    TalimUI.toast(`Strategy ${name} ${verb}d`, "ok");
    await refreshStrategies();
  } catch (err) { TalimUI.toast(`Could not ${verb} ${name}: ${err.message}`, "error"); }
}

// ---------------------------------------------------------------------------
// Decisions
// ---------------------------------------------------------------------------

function buildQuery(params) {
  const out = [];
  for (const [k, v] of Object.entries(params)) {
    if (v === "" || v == null) continue;
    out.push(`${encodeURIComponent(k)}=${encodeURIComponent(v)}`);
  }
  return out.length ? "?" + out.join("&") : "";
}

async function refreshDecisions() {
  const body = document.getElementById("decisions-body");
  try {
    const qs = buildQuery(state.decisionsFilters);
    const data = await api("/talim/operator/decisions" + qs);
    clear(body);
    const rows = data.decisions || [];
    if (!rows.length) {
      body.appendChild(el("div", { class: "muted", text: "no decisions match filters" }));
      return;
    }
    const trades = buildTradeRows(rows);
    const table = el("table");
    const thead = el("thead");
    const head = el("tr");
    for (const h of ["timestamp", "instrument", "strategy", "side", "status", "entry → exit", "points", "PnL", "notes"]) {
      head.appendChild(el("th", { text: h }));
    }
    thead.appendChild(head);
    table.appendChild(thead);
    const tbody = el("tbody");
    for (const t of trades) {
      const r = t.exit || t.entry || t.row;
      const row = el("tr");
      const entryPrice = t.entry ? t.entry.entry_price : (t.kind === "open" ? r.entry_price : null);
      const exitPrice = t.exit ? t.exit.entry_price : null;
      const priceText = t.kind === "trade"
        ? `${fmtNum(entryPrice, 2)} → ${fmtNum(exitPrice, 2)}`
        : (t.kind === "open" ? `${fmtNum(entryPrice, 2)} → open` : fmtNum(r.entry_price, 2));
      const status = t.kind === "trade" ? "closed" : (r.outcome || r.signal_type || "—");
      const points = t.kind === "trade" ? t.points : null;
      const ts = r.timestamp || r.created_at;
      const tsCell = el("td", { text: fmtTsShort(ts) });
      const ago = fmtAgo(ts);
      if (ago) tsCell.appendChild(el("span", { class: "muted ts-ago", text: ` · ${ago}` }));
      row.appendChild(tsCell);
      row.appendChild(el("td", { text: r.instrument || "—" }));
      row.appendChild(el("td", { text: r.strategy || "—" }));
      row.appendChild(el("td", { text: r.side || "—" }));
      row.appendChild(el("td", { text: status }));
      row.appendChild(el("td", { text: priceText }));
      row.appendChild(el("td", { text: points == null ? "—" : fmtSigned(points), class: pnlClass(points) }));
      row.appendChild(el("td", { text: fmtSigned(r.pnl), class: pnlClass(r.pnl) }));
      row.appendChild(el("td", { text: (r.notes || r.rationale || "").slice(0, 80) }));
      tbody.appendChild(row);
    }
    table.appendChild(tbody);
    body.appendChild(table);
  } catch (err) { renderError(body, err); }
}

// ---------------------------------------------------------------------------
// Backtests
// ---------------------------------------------------------------------------

async function refreshBacktests() {
  const body = document.getElementById("backtests-body");
  try {
    const qs = buildQuery(state.backtestsFilters);
    const data = await api("/talim/operator/backtests" + qs);
    clear(body);
    const rows = data.runs || [];
    if (!rows.length) {
      body.appendChild(el("div", { class: "muted", text: "no backtest runs match filters" }));
      return;
    }
    const table = el("table");
    const thead = el("thead");
    const head = el("tr");
    for (const h of ["id", "created", "strategy", "instrument", "tf", "trades", "net P&L", "return %", "Sharpe", "max DD", "win %", "trigger", "status"]) {
      head.appendChild(el("th", { text: h }));
    }
    thead.appendChild(head);
    table.appendChild(thead);
    const tbody = el("tbody");
    for (const r of rows) {
      const row = el("tr", {
        class: "clickable" + (state.openBacktestRunId === r.id ? " selected" : ""),
        "data-run-id": r.id,
        onClick: () => showBacktestDetail(r.id),
      });
      row.appendChild(el("td", { text: String(r.id) }));
      row.appendChild(el("td", { text: fmtTsShort(r.created_at) }));
      row.appendChild(el("td", { text: r.strategy || "—" }));
      row.appendChild(el("td", { text: r.instrument || "—" }));
      row.appendChild(el("td", { text: r.timeframe || "—" }));
      row.appendChild(el("td", { text: String(r.total_trades == null ? "—" : r.total_trades) }));
      row.appendChild(el("td", { text: fmtSigned(r.net_pnl), class: pnlClass(r.net_pnl) }));
      row.appendChild(el("td", { text: r.return_pct == null ? "—" : (Number(r.return_pct) * 100).toFixed(2) + "%", class: pnlClass(r.return_pct) }));
      row.appendChild(el("td", { text: fmtNum(r.sharpe_ratio, 4) }));
      row.appendChild(el("td", { text: fmtSigned(r.max_drawdown), class: pnlClass(r.max_drawdown) }));
      row.appendChild(el("td", { text: r.win_rate == null ? "—" : (Number(r.win_rate) * 100).toFixed(1) + "%" }));
      row.appendChild(el("td", { text: r.triggered_by || "—" }));
      row.appendChild(el("td", { text: r.status || "—" }));
      tbody.appendChild(row);
    }
    table.appendChild(tbody);
    body.appendChild(table);
  } catch (err) { renderError(body, err); }
}

function markSelectedBacktestRow() {
  document.querySelectorAll("#backtests-body tr[data-run-id]").forEach((tr) => {
    tr.classList.toggle(
      "selected",
      state.openBacktestRunId != null && String(state.openBacktestRunId) === tr.getAttribute("data-run-id"),
    );
  });
}

function closeBacktestDetail() {
  const detail = document.getElementById("backtest-detail");
  state.openBacktestRunId = null;
  detail.hidden = true;
  clear(detail);
  markSelectedBacktestRow();
}

async function showBacktestDetail(runId) {
  const detail = document.getElementById("backtest-detail");
  state.openBacktestRunId = runId;
  markSelectedBacktestRow();
  clear(detail);
  detail.hidden = false;
  detail.appendChild(el("div", { class: "muted", text: `Loading run ${runId}…` }));
  try {
    const data = await api(`/talim/operator/backtests/${runId}`);
    const run = data.run || {};
    clear(detail);
    detail.appendChild(el("h3", { text: `Backtest run #${run.id}` }));
    const dl = el("dl", { class: "kv" });
    const push = (k, v) => {
      dl.appendChild(el("dt", { text: k }));
      dl.appendChild(el("dd", { text: v == null ? "—" : String(v) }));
    };
    push("created_at", fmtTs(run.created_at));
    push("strategy", run.strategy);
    push("instrument", run.instrument);
    push("timeframe", run.timeframe);
    push("engine", run.engine);
    push("period_start", run.period_start);
    push("period_end", run.period_end);
    push("triggered_by", run.triggered_by);
    push("status", run.status);
    push("artifact_path", run.artifact_path);
    push("trades", run.total_trades);
    push("net P&L", fmtSigned(run.net_pnl));
    push("return", run.return_pct == null ? "—" : (Number(run.return_pct) * 100).toFixed(2) + "%");
    push("Sharpe", fmtNum(run.sharpe_ratio, 4));
    push("Sortino", fmtNum(run.sortino_ratio, 4));
    push("profit factor", fmtNum(run.profit_factor, 4));
    push("max drawdown", fmtSigned(run.max_drawdown));
    push("win rate", run.win_rate == null ? "—" : (Number(run.win_rate) * 100).toFixed(2) + "%");
    if (run.notes) push("notes", run.notes);
    detail.appendChild(dl);
    if (run.param_variant) {
      detail.appendChild(el("h4", { text: "params" }));
      detail.appendChild(el("pre", { text: typeof run.param_variant === "string" ? run.param_variant : JSON.stringify(run.param_variant, null, 2) }));
    }
    const md = run.matched_dates;
    if (md && md.length) {
      detail.appendChild(el("h4", { text: "matched dates" }));
      detail.appendChild(el("pre", { text: Array.isArray(md) ? md.join(", ") : String(md) }));
    }
    const close = el("button", { type: "button", text: "Close", onClick: closeBacktestDetail });
    detail.appendChild(close);
  } catch (err) { renderError(detail, err); }
}

// ---------------------------------------------------------------------------
// Header / filter bindings
// ---------------------------------------------------------------------------

function syncAuthUi() {
  const authState = document.getElementById("auth-state");
  const unlockBtn = document.getElementById("unlock-btn");
  const lockBtn = document.getElementById("lock-btn");
  if (!state.authenticated) {
    authState.textContent = "Locked — sign in to read";
    authState.className = "auth-locked";
    unlockBtn.hidden = false;
    lockBtn.hidden = true;
    unlockBtn.textContent = "Sign in";
  } else if (!state.unlocked) {
    authState.textContent = "Read-only (writes locked)";
    authState.className = "auth-locked";
    unlockBtn.hidden = false;
    lockBtn.hidden = true;
    unlockBtn.textContent = "Unlock writes";
  } else {
    authState.textContent = "Unlocked (writes enabled)";
    authState.className = "auth-unlocked";
    unlockBtn.hidden = true;
    lockBtn.hidden = false;
    lockBtn.textContent = "Lock writes";
  }
}

function syncNotifyUi() {
  const btn = document.getElementById("notify-btn");
  if (!btn) return;
  if (typeof Notification === "undefined") {
    btn.hidden = true;
    return;
  }
  btn.hidden = false;
  if (Notification.permission === "denied") {
    btn.textContent = "Notify: blocked";
    btn.disabled = true;
    return;
  }
  btn.disabled = false;
  btn.textContent = state.notifyEnabled ? "Notify: on" : "Notify: off";
}

function bindHeader() {
  document.getElementById("refresh-btn").addEventListener("click", refreshAll);
  const notifyBtn = document.getElementById("notify-btn");
  if (notifyBtn) {
    notifyBtn.addEventListener("click", async () => {
      if (typeof Notification === "undefined") return;
      if (state.notifyEnabled) {
        state.notifyEnabled = false;
      } else {
        const permission = Notification.permission === "granted"
          ? "granted"
          : await Notification.requestPermission();
        state.notifyEnabled = permission === "granted";
        if (permission === "denied") TalimUI.toast("Browser notifications are blocked for this site.", "error");
      }
      syncNotifyUi();
    });
  }
  document.getElementById("unlock-btn").addEventListener("click", async () => {
    if (!state.authenticated) {
      const secret = await TalimUI.promptSecret("Paste the TALIM_BRIDGE_SECRET value once for this browser session.");
      if (!secret) return;
      try {
        await loginWithSecret(secret);
        syncAuthUi();
        TalimUI.toast("Signed in", "ok");
        refreshAll();
      } catch (err) {
        TalimUI.toast((err && err.message) || "Sign in failed", "error");
      }
      return;
    }
    const ok = await TalimUI.confirm(
      "Unlock write actions (approve/reject, halt, strategy toggles) for this tab?",
      { confirmLabel: "Unlock writes" },
    );
    if (ok) {
      state.unlocked = true;
      syncAuthUi();
      refreshAll();
    }
  });
  document.getElementById("lock-btn").addEventListener("click", () => {
    if (state.unlocked) {
      state.unlocked = false;
      syncAuthUi();
      refreshAll();
      return;
    }
    syncAuthUi();
    refreshAll();
  });
  const clearSignal = document.getElementById("clear-signal-link");
  if (clearSignal) {
    clearSignal.addEventListener("click", () => {
      history.replaceState(null, "", window.location.pathname);
      refreshAll();
    });
  }
}

function bindFilters() {
  document.getElementById("decisions-filter").addEventListener("submit", (ev) => {
    ev.preventDefault();
    const f = ev.target;
    state.decisionsFilters = {
      instrument: f.instrument.value.trim(),
      strategy: f.strategy.value.trim(),
      limit: Number(f.limit.value) || 20,
    };
    refreshDecisions();
  });
  document.getElementById("backtests-filter").addEventListener("submit", (ev) => {
    ev.preventDefault();
    const f = ev.target;
    state.backtestsFilters = {
      strategy: f.strategy.value.trim(),
      instrument: f.instrument.value.trim(),
      limit: Number(f.limit.value) || 25,
    };
    refreshBacktests();
  });
}

// ---------------------------------------------------------------------------
// Top-level refresh
// ---------------------------------------------------------------------------

function refreshAll() {
  // Coalesce concurrent callers (15s timer, manual refresh, post-action
  // refreshes) onto one in-flight pass so slow bridge responses don't stack.
  if (state.refreshPromise) return state.refreshPromise;
  state.refreshPromise = (async () => {
    document.getElementById("last-refresh").textContent =
      new Date().toISOString().replace("T", " ").replace(/\..*/, "") + " UTC";
    const pendingPromise = fetchPending();
    pendingPromise.catch(() => {}); // consumers below handle their own errors
    await Promise.all([
      refreshStatus(),
      refreshPending(pendingPromise),
      refreshSignalDetail(pendingPromise),
      refreshPositions(),
      refreshStrategies(),
      refreshDecisions(),
      refreshBacktests(),
    ]);
  })().finally(() => { state.refreshPromise = null; });
  return state.refreshPromise;
}

function startAutoRefresh() {
  if (state.timer) clearInterval(state.timer);
  state.timer = setInterval(() => {
    if (!document.hidden) refreshAll();
  }, REFRESH_INTERVAL_MS);
}

document.addEventListener("DOMContentLoaded", async () => {
  bindHeader();
  bindFilters();
  syncNotifyUi();
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) refreshAll();
  });
  await refreshSession();
  syncAuthUi();
  refreshAll();
  startAutoRefresh();
});
