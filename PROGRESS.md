# Talim — Build Progress Tracker

> Tracks status of each work package across all phases. Updated after each build session.

---

## Status Legend

| Icon | Meaning |
|------|---------|
| `[ ]` | Not started |
| `[~]` | In progress |
| `[x]` | Complete |
| `[!]` | Blocked |

---

## Research / Backtesting Task Tracker

Research and backtesting TODOs that are not yet formal Talim work packages are tracked in:

- `BACKTESTING_ROADMAP.md` in the OpenClaw app checkout (not part of this repo; on the deploy host it lives at `~/openclaw-app/BACKTESTING_ROADMAP.md`)

Use that roadmap for messy/open-ended items such as finding more historical backtesting data, documenting Justin's discretionary strategy, adding/testing indicators, expanding assets, and defining comparison rules. Promote items into numbered WPs here once they become concrete implementation work.

Current active roadmap items:

- `BR-01` / `WP-74` — complete deeper AU200/US500 historical data coverage and gap audit. Dukascopy ingest/coverage/retry tooling is now in-repo (see WP-74); remaining work is running the full-depth coverage pulls and gap audit. The AU200.proxy ASK re-pull stays gated behind `RR-08`.
- `BR-02` — document Justin's discretionary trading style.
- `BR-03` — define the next indicator research batch. Promoted to `WP-88`: batch defined at `docs/indicator-research-batch-2.md` (ADX/DMI, Keltner, SuperTrend, Efficiency Ratio now; VWAP/OBV gated on a volume-quality audit); implementation is agent-pickable, evaluation gated on costed baselines + WP-87 sign-off.
- `BR-04` — establish baseline comparison rules. Promoted to `WP-87`: proposal drafted at `docs/backtest-comparison-rules.md`, awaiting Justin sign-off.
- `BR-05` — standardise realistic fees/spread/slippage assumptions. Promoted to `WP-86` and implemented: cost model + standard venue assumptions landed 2026-07-12; broker-quote verification still pending (needs demo credentials on the deploy host).

---

## Reliability / Operational Safety Tracker

Off-host backups, safe-write code patterns, HITL gates for irreplaceable data, and resumption-protocol work are tracked in:

- `RELIABILITY_ROADMAP.md` in the OpenClaw app checkout (not part of this repo; on the deploy host it lives at `~/openclaw-app/RELIABILITY_ROADMAP.md`)

Use that roadmap for anything whose value is "we don't lose work / can recover from mistakes." Originated from the 2026-05-25 AU200.proxy ASK parquet incident. Promote items into numbered WPs here once they become concrete Talim implementation work.

Current active roadmap items:

- `RR-01` — decide off-host backup destination (in progress, blocks the rest of Phase 1).
- `RR-02` — draft `RECOVERY.md` data classification.
- `RR-03` — define backup path allowlist + excludes.
- `RR-04` — install restic on host.
- `RR-05` → `RR-07` — init restic repo, wire nightly backup + notify, test-restore (blocked chain on RR-01).
- `RR-08` — re-pull AU200.proxy ASK 2014-2026 (blocked by RR-07 — no multi-day pull without a verified safety net).

---

## Phase 1: Foundation (sequential)

| WP | Name | Status | Session Date | Notes |
|----|------|--------|--------------|-------|
| WP-01 | Core Data Models & Shared Types | `[x]` | 2026-04-06 | 18/18 tests passing |
| WP-02 | Regime Detection Engine | `[x]` | 2026-04-06 | 25/25 tests passing |
| WP-03 | Strategy Framework & on_bar Interface | `[x]` | 2026-04-06 | 19/19 tests passing |

## Phase 2: Infrastructure (parallel after Phase 1)

| WP | Name | Status | Session Date | Notes |
|----|------|--------|--------------|-------|
| WP-04 | Memory Stores (SQLite) | `[x]` | 2026-04-06 | 13/13 tests passing |
| WP-05 | Redis Event Bus Wrapper | `[x]` | 2026-04-06 | 10/10 tests passing |
| WP-06 | Price Feed Connector | `[x]` | 2026-04-07 | 14/14 tests passing |
| WP-07 | Exchange Connector | `[x]` | 2026-04-07 | 17/17 tests passing |

## Phase 3: Brain (sequential, after Phase 1+2)

| WP | Name | Status | Session Date | Notes |
|----|------|--------|--------------|-------|
| WP-08 | LangGraph State & Graph Skeleton | `[x]` | 2026-04-07 | 13/13 tests passing |
| WP-09 | Signal Scanner Node | `[x]` | 2026-04-06 | 11/11 tests passing (140 total) |
| WP-10 | Router + Conditional Edges | `[x]` | 2026-04-07 | 13/13 tests passing (153 total) |
| WP-11 | HITL Interrupt Node | `[x]` | 2026-04-07 | 12/12 tests passing (165 total) |

## Phase 4: Intelligence (parallel, after WP-08)

| WP | Name | Status | Session Date | Notes |
|----|------|--------|--------------|-------|
| WP-12 | Backtest Engine (vectorbt) | `[x]` | 2026-04-07 | 14/14 tests passing (179 total) |
| WP-13 | LLM Integration Layer | `[x]` | 2026-04-07 | 15/15 tests passing (194 total) |
| WP-14 | Strategy Update & Notify Nodes | `[x]` | 2026-04-07 | 17/17 tests passing (211 total) |

## Phase 5: Interface (parallel, after WP-08)

| WP | Name | Status | Session Date | Notes |
|----|------|--------|--------------|-------|
| WP-15 | Discord Bot Connector | `[x]` | 2026-04-07 | 19/19 tests passing (230 total) |
| WP-16 | Bridge API | `[x]` | 2026-04-07 | 13/13 tests passing (243 total) |
| WP-17 | Risk Check Node | `[x]` | 2026-04-07 | 14/14 tests passing (257 total) |

## Phase 6: Deployment & Integration

| WP | Name | Status | Session Date | Notes |
|----|------|--------|--------------|-------|
| WP-18 | Docker Compose Stack | `[x]` | 2026-04-07 | 8/8 deployment file checks |
| WP-19 | End-to-End Integration Test | `[x]` | 2026-04-07 | 1 e2e scenario, 266 total tests |

---

## Integration Test Checklist

| Test Pair | Status | Date | Notes |
|-----------|--------|------|-------|
| WP-02 + WP-04: Regime -> PatternMemory | `[x]` | 2026-04-07 | `tests/test_memory.py::TestPatternMemory::test_rebuild_from_dataframe` builds fingerprints from bars and round-trips through PatternMemory |
| WP-03 + WP-06: Strategy -> PriceFeed | `[x]` | 2026-04-07 | `tests/test_signal_scanner.py::TestSignalScannerNode::test_updates_market_state` feeds MockPriceFeed bars through `BaseStrategy.on_bar` via the scanner |
| WP-08 + WP-09: Graph -> SignalScanner | `[x]` | 2026-04-07 | `tests/test_graph.py::test_cron_trigger_runs_to_end` runs the live graph through the real scanner |
| WP-08 + WP-10: Graph -> Router | `[x]` | 2026-04-07 | `tests/test_graph.py::test_signal_takes_priority_over_regime` + `test_pending_*_routes_to_*` exercise all 5 router branches inside the live graph |
| WP-11 + WP-15: HITL -> Discord | `[x]` | 2026-04-07 | `tests/e2e/test_market_day.py::test_full_market_day` formats the HITL signal as an embed, registers a Discord reaction, and resumes the graph |
| WP-11 + WP-16: HITL -> Bridge | `[x]` | 2026-04-07 | `tests/test_bridge.py` POSTs `/talim/resume` against the FastAPI app and verifies the graph resumes |
| WP-09 + WP-12: Scanner -> Backtest | `[x]` | 2026-04-07 | `tests/e2e/test_market_day.py::test_full_market_day` runs the scanner-driven graph then executes a multi-variant backtest on the same dataset |
| WP-17 + WP-07: RiskCheck -> Exchange | `[x]` | 2026-04-07 | `tests/test_execute_node.py::test_execute_places_order_and_records_decision` (post-risk-check signal flowing to MockExchange) + e2e full path |

---

## PoC Success Criteria

| # | Criterion | Verified |
|---|-----------|----------|
| 1 | Start stack with `docker compose up` | `[x]` 2026-04-07 — see `docs/poc-verification.md` |
| 2 | Replay historical bars, detect regimes, fire signals | `[x]` 2026-04-07 |
| 3 | Receive trade alert in Discord with context | `[x]` 2026-04-07 |
| 4 | React with checkmark, see MockExchange log fill | `[x]` 2026-04-07 |
| 5 | Ask "what's my P&L?" and get accurate response | `[x]` 2026-04-07 |
| 6 | Request backtest and see Sharpe/drawdown results | `[x]` 2026-04-07 |
| 7 | All decisions logged in episodic memory | `[x]` 2026-04-07 |

---

## Phase 8: Production Readiness

| WP | Name | Status | Session Date | Notes |
|----|------|--------|--------------|-------|
| WP-34 | Position Monitor & Stop/Target Enforcement | `[x]` | 2026-04-11 | 17/17 tests passing (319 total) |
| WP-35 | Order Reconciliation Loop | `[x]` | 2026-04-11 | 11/11 tests passing (330 total) |
| WP-36 | P&L Source of Truth | `[x]` | 2026-04-11 | 9/9 tests passing (339 total) |
| WP-38 | Scheduler / Cron Service | `[x]` | 2026-04-11 | 3 new tests (342 total) |
| WP-39 | Risk Rules Config & Kill Switch | `[x]` | 2026-04-11 | 18/18 tests passing (360 total) |
| WP-41 | Observability (Metrics, Logs, Alerts) | `[x]` | 2026-04-11 | 8/8 tests passing (368 total) |
| WP-43 | Backup & Disaster Recovery | `[x]` | 2026-04-11 | 4/4 tests passing (372 total) |
| WP-32 | Live Exchange Wiring & Testnet Soak | `[x]` | 2026-04-12 | 16/16 tests passing (388 total) |
| WP-46 | External Assistant Deployment | `[x]` | 2026-04-12 | Removed the bundled NanoClaw stub; compose/runtime now assume an external assistant client or direct bridge caller |

## Phase 9: Local-First Deployment

| WP | Name | Status | Session Date | Notes |
|----|------|--------|--------------|-------|
| WP-47 | Portable Local Deployment & VPS Migration Layout | `[x]` | 2026-04-22 | Replaced `talim-state` and `redis-data` named volumes with `./state` and `./redis` bind mounts; added `./backups` bind mount on `talim` and `scheduler` services; surfaced `TALIM_BACKTEST_HISTORY_DB`, `TALIM_STATE_DIR`, `TALIM_BACKUP_DIR` in `.env.example` and compose env; committed empty `state/`, `redis/`, `backups/` dirs via `.gitkeep` (gitignored contents); swept docs for hardcoded `/Users/justinluu/...` paths (now repo-relative); added `docs/vps-migration.md` runbook + cross-link from `docs/laptop-setup.md`; added `tests/test_deployment_layout.py` (16 static checks) plus updated AOF test for the new bind-mount layout |

## Phase 10: Broker-Agnostic CFD Core (IG-First)

| WP | Name | Status | Session Date | Notes |
|----|------|--------|--------------|-------|
| WP-48 | CFD Venue Contract and Instrument Registry | `[x]` | 2026-04-12 | Added canonical CFD spec/venue capability models, JSON registry, and registry loader/tests for AU200 cash/fwd instruments |
| WP-49 | IG AU Feasibility and Market Discovery | `[x]` | 2026-04-12 | Verified IG demo auth and discovered initial AU200 mappings: cash `IX.D.ASX.IFT.IP` and forward `IX.D.ASX.FWM2.IP`; some contract metadata remains to be filled during adapter work |
| WP-50 | IG Exchange Adapter | `[x]` | 2026-04-12 | Added `IgExchange`, confirm/deal-id handling, canonical-instrument mapping, factory wiring, and mocked execution tests for market + working orders |
| WP-51 | CFD Market Data Pipeline (IG-First) | `[x]` | 2026-04-13 | Added `IgPriceFeed`, snapshot-to-bar builder, scanner polling hooks, price-feed factory, and IG historical ingestion to Parquet |
| WP-52 | CFD Risk, P&L, and Session Model | `[x]` | 2026-04-13 | Added CFD-aware margin/session checks, financing-aware P&L snapshots, AU200 point-value metadata, and netted CFD reconciliation |
| WP-53 | AU200 Strategy Package and IG Demo Soak | `[x]` | 2026-04-13 | Added `momentum-AU200`, timeframe-aware backtests/datasets, IG dataset build/runbook scripts, and recorded the first AU200 baseline backtest on IG demo data |

## Phase 11: Prediction Market Venue Enablement

> Gate outcome (2026-07-12): WP-54 research recommends **NO-GO** — Polymarket is a prohibited service in Australia (ACMA formal warning July 2025; regulator-directed ISP block August 2025 under the Interactive Gambling Act 2001). WP-55–WP-58 must not start unless Justin decides otherwise. See `docs/polymarket-feasibility-gate.md`.

| WP | Name | Status | Session Date | Notes |
|----|------|--------|--------------|-------|
| WP-54 | Polymarket Feasibility, Compliance, and Product Fit Gate | `[!]` | 2026-07-12 | Research complete: Polymarket is ACMA-blocked in Australia (formal warning to Adventure One QSS Inc. July 2025; ISP-level block directed August 2025 under the IGA 2001; Polymarket's own ToS also restrict Australia). Automated access would require deliberate circumvention. Product fit is poor regardless (wallet/CLOB/binary-payout model shares little with the CFD stack). Recommendation: close Phase 11, or open a fresh WP for an Australian-licensed event-market venue instead. Blocked on Justin's close/park decision — `docs/polymarket-feasibility-gate.md` |
| WP-55 | Polymarket Wallet Auth and Exchange Connector | `[ ]` | — | Implement signed auth, order placement, balances, fills, and position retrieval for the Polymarket CLOB |
| WP-56 | Polymarket Market Data and WebSocket Feed | `[ ]` | — | Add market discovery plus live orderbook/trade snapshot ingestion for event markets |
| WP-57 | Prediction Market Position, Risk, and Settlement Model | `[ ]` | — | Model capped payout, collateral, liquidity, settlement, and event concentration risk |
| WP-58 | Event-Driven Strategy and Backtest Framework | `[ ]` | — | Add replay/backtest support and baseline strategies for probability-driven event markets |

## Phase 12: Second CFD Venue Portability

| WP | Name | Status | Session Date | Notes |
|----|------|--------|--------------|-------|
| WP-59 | FOREX.com AU Feasibility and Market Mapping | `[x]` | 2026-04-18 | Verify whether the canonical CFD model carries cleanly into FOREX.com AU and document any gaps |
| WP-60 | FOREX.com Exchange and Price Feed Adapters | `[x]` | 2026-04-18 | Implement FOREX.com on top of the broker-neutral CFD interfaces rather than as a parallel stack |
| WP-61 | Multi-Broker CFD Conformance and Demo Regression | `[x]` | 2026-04-18 | Prove the same Talim CFD flow works across IG and FOREX.com adapters with shared tests and demo runbooks |

## Phase 13: Live Runtime Execution Wiring

| WP | Name | Status | Session Date | Notes |
|----|------|--------|--------------|-------|
| WP-62 | Live Runtime Bootstrap | `[x]` | 2026-04-18 | Added runtime composition root that wires env-selected exchange/feed/strategies/instruments/risk/checkpoints/episodic memory into the FastAPI app |
| WP-63 | Live Demo Execution Harness | `[x]` | 2026-04-18 | Added deterministic mock execution harness proving scan -> HITL -> approve -> execute -> memory -> reconcile before broker demo orders |
| WP-64 | OpenClaw / Operator HITL Interface | `[x]` | 2026-04-18 | Added authenticated operator endpoints for status, pending HITL signal inspection, approve/reject, positions, and recent decisions |
| WP-65 | Runtime Reconciliation and P&L Sync | `[x]` | 2026-04-18 | Added authenticated `/talim/sync` endpoint plus offset cron schedule to refresh positions/P&L, run reconciliation, and persist safe checkpoint updates |
| WP-66 | Protective Orders and Safe Exit Execution | `[x]` | 2026-04-18 | Added broker-neutral close-position execution, fixed exit side mapping, and propagated strategy stop/target levels into supported adapter payloads |

## Phase 14: Strategy Authoring & Observability

| WP | Name | Status | Session Date | Notes |
|----|------|--------|--------------|-------|
| WP-67 | Backtest Data Strategy Decision | `[x]` | 2026-04-19 | Decided IG + FOREX.com historical REST as primary backtest data; no QuantConnect (would break single-strategy-contract invariant); rename `-ES` strategies to `-US500`; see docs/backtest-data-strategy.md |
| WP-68 | Backtest Run History & Query API | `[x]` | 2026-04-19 | Added `BacktestHistory` (SQLite `backtest_runs`) with `record_run/record_results/list_runs/get_run`; CLI + graph node persist every variant (triggered_by = cli/node); added operator endpoints `GET /talim/operator/backtests` (strategy/instrument/triggered_by/since filters + pagination) and `GET /talim/operator/backtests/{id}`; history DB path configurable via `TALIM_BACKTEST_HISTORY_DB` |
| WP-69 | Operator Monitoring Dashboard | `[x]` | 2026-04-19 | Static single-page dashboard mounted on the bridge at `/talim/dashboard/` with panels for runtime status, open positions, pending HITL signal (approve/reject), strategies (enable/disable), recent decisions (filterable), backtest history (with drill-in), daily P&L. Auth via `X-Talim-Secret` stored in `sessionStorage`; writes gated behind a separate in-memory unlock toggle. Extended `operator_status` with `open_pnl` / `daily_pnl`. Smoke tests in `tests/test_bridge.py::TestOperatorDashboard`; runbook at `docs/operator-dashboard.md` |
| WP-70 | Hot Strategy Activation Controls | `[x]` | 2026-04-19 | `Runtime.enable_strategy` / `disable_strategy` / `operator_strategies`; fail-fast module load on enable; pending HITL preserved on disable; `strategy_activations` audit table + `EpisodicMemory.record_activation` / `query_activations`; operator endpoints `GET /talim/operator/strategies`, `POST /…/{name}/enable`, `POST /…/{name}/disable`; scanner distinguishes `active_strategies=[]` from unset; `docs/strategy-activation.md` |
| WP-71 | Shared Indicator Library | `[x]` | 2026-04-19 | Added `talim/strategy/indicators/` with EMA/SMA/Wilder-ATR/Wilder-RSI/Bollinger/MACD/Stochastic/Donchian (streaming + vectorised, parity-tested); refactored momentum-ES, mean-reversion-ES, momentum-AU200 through it; `docs/strategy-authoring.md` added; AU200 baseline metrics unchanged |
| WP-72 | Strategy Parameter Schema & Validated Loading | `[x]` | 2026-04-19 | Added `ParamSpec` + `StrategyParamError`, wired through `BaseStrategy.load_params`, declared schemas on all 3 strategies, engine/CLI/LLM strategy_update/operator endpoint all validate at the boundary |
| WP-73 | US500 Rename, Ingest & Baseline Backtest | `[x]` | 2026-04-19 | Renamed `momentum-ES`/`mean-reversion-ES` → `-US500` across strategies/, tests, vectorbt translator, demo harness, README, architecture doc; added US500.cash to `config/cfd_instruments.json` with both IG (`IX.D.SPTRD.IFA.IP`) and FOREX.com (`404706660`) mappings resolved against demos; ingested 5m + 1h history from FOREX.com into `data/forexcom/US500.cash/` (IG blocked on weekly allowance); wrote `scripts/ingest_forexcom_prices.py`; hardened `data_loader.load_ohlcv` + `run_backtest.py` CLI to fail loudly on missing timeframe parquet or empty data; captured default-param baselines in `docs/backtest-baselines/us500-2026-04-19.json` and procedure in `docs/backtest-us500-runbook.md` |
| WP-74 | Pre-2020 Historical Data Source Probe | `[~]` | 2026-07-12 | Source probe resolved on Dukascopy proxy data (`USA500IDXUSD` → `US500.proxy`, `AUSIDXAUD` → `AU200.proxy`), kept separate from broker data under `data/backtest/dukascopy/` per the proxy-separation rule. Tooling landed 2026-07-10: `scripts/ingest_dukascopy_ticks.py` (BI5 tick download → OHLCV Parquet), `build_dukascopy_canonical_bars.py`, `scan_dukascopy_coverage.py`, `retry_dukascopy_fetch_errors.py`, `run_dukascopy_year_pull_and_retry.py`. Pull-reliability hardening (resume state, raw-hour cache, conservative market-closure filter, overwrite refusal, append dedupe) merged 2026-07-12 (PRs #4/#6). Remaining: run full-depth US500/AU200 coverage pulls + gap audit (`BR-01`); AU200.proxy ASK 2014–2026 re-pull blocked behind the RR-07/RR-08 backup safety net. Options note: `docs/pre-2020-historical-data-options.md` |

## Phase 15: Operator Signal Lifecycle & Approval Safety

| WP | Name | Status | Session Date | Notes |
|----|------|--------|--------------|-------|
| WP-75 | OpenClaw Discord HITL Alert Watcher | `[x]` | 2026-05-14 | Implemented OpenClaw-side watcher using `/home/wombat/.openclaw/workspace/tools/talim_pending_alert.py` plus cron job `b3345396-2253-43c6-90d2-c6a3c19af4a1` every 60s. It calls `/talim/operator/pending?thread_id=cron-main` through nginx/operator env, de-duplicates by signal fingerprint in `/home/wombat/.openclaw/talim/pending-alert-state.json`, and posts new pending-signal notifications to Discord channel <#1497790419076120576> via OpenClaw's existing Discord integration. Alerts include temp signal id/fingerprint, strategy, instrument, side, entry/stop/target, regime, age, rationale, dashboard link, and approve/reject instructions. Talim's native Discord reaction bot remains unused. |
| WP-76 | Durable Signal Records and Deep Links | `[x]` | 2026-05-14 | Added persistent `signals` table to episodic SQLite with stable `signal_id`, original signal snapshot, source bar timestamp, created_at/updated_at, regime/rationale/context JSON, thread id, dashboard URL, lifecycle status fields, latest validation placeholders, and decision timestamps/actor. `/talim/operator/pending` now records/updates pending signals and returns `signal_id` + `dashboard_url`; new `GET /talim/operator/signals/{signal_id}` returns the durable row. Dashboard shows signal id/link and warns if a deep-linked signal is not the current pending signal. OpenClaw helper supports `signal <id>` and pending alerts prefer durable signal ids/deep links. |
| WP-77 | Strategy-Specific Signal Validation | `[x]` | 2026-05-14 | Added `ValidationResult`/status model and `BaseStrategy.validate_signal(...)` with conservative default age/price-movement checks. Implemented strategy-specific validators for `momentum-US500`, `momentum-AU200`, and `mean-reversion-US500`: momentum checks EMA side (and AU200 ATR-backed separation), mean reversion checks Bollinger midline invalidation. Runtime now refreshes/uses recent bars, validates pending signals, stores latest validation status/reason on durable signal rows, and returns validation in `/operator/pending`; dashboard displays validation status/reason/current price/R-move/bars-since-signal. WP-77 is advisory only; WP-78 will enforce validation on approval. |
| WP-78 | Approval-Time Validation Enforcement | `[x]` | 2026-05-14 | Changed runtime approval so OpenClaw/dashboard approvals do not execute directly. On approve, Talim refreshes broker positions/P&L, refreshes/latest bars through strategy validation, reruns strategy-specific validation, reruns risk checks with fresh positions/P&L, and only then resumes execution. Validation/risk refusal clears the pending signal, records `expired`/`invalid` plus validation reason on the durable signal row, and returns a clear blocking reason without placing an order. Manual rejection records `rejected`; successful approved execution records `approved` then `executed` when execution clears the pending signal. |
| WP-79 | Dashboard Signal Detail Page | `[x]` | 2026-05-15 | Added standalone mobile-friendly HITL signal page via `/talim/dashboard/signal.html?signal=<signal_id>`. The signal page loads the durable `/operator/signals/{signal_id}` row, displays original signal fields, lifecycle status, timestamps, latest validation status/reason, live current-pending validation when applicable, and approve/reject controls. Approve is disabled unless the linked signal is the current pending HITL signal and live validation allows approval; non-current/stale links show a warning. The operator dashboard links out to this page for detailed review. |
| WP-80 | Paige/OpenClaw Signal Command Path | `[x]` | 2026-05-15 | Added signal-id-aware operator decision flow and OpenClaw helper commands for Paige. `/talim/operator/decision` now accepts optional `signal_id`; Talim refuses mismatched signal-id decisions without clearing the current pending signal, and still performs WP-78 validation/risk enforcement before any approval executes. OpenClaw helper supports `analyze`/`analyse <signal_id>`, `approve-signal <signal_id>`, `reject-signal <signal_id>`, plus `decision approve|reject --signal-id <signal_id>`. This enables Paige to safely analyse/approve/reject a named signal while Talim remains the final gatekeeper. |

## Phase 16: Operator Signal Visualization & Noise Diagnosis

| WP | Name | Status | Session Date | Notes |
|----|------|--------|--------------|-------|
| WP-81 | Signal Chart Data Path | `[x]` | 2026-05-17 | Confirmed durable signal rows already carry chart-anchor metadata: `signal_id`, `instrument`, `strategy`, `side`, `entry_price`, `stop`, `target`, `rationale`, `regime`, `source_bar_timestamp`, validation status/reason, and `context_json` with ATR/regime/scan context. Scanner keeps live in-memory OHLCV per instrument via `ScannerContext._bar_history`; runtime default `bar_window=50`, trim policy keeps roughly 100–200 recent bars, enough for fresh signal charts but not durable across restart. Current FOREX.com pricefeed can fetch recent bars and has `fetch_bars_before(...)`, which can reconstruct around a signal timestamp by fetching through `signal_ts + after*timeframe`; IG currently only exposes recent fetches in Talim code. No live OHLCV persistence table exists; historical Parquet is backtest-oriented and not current enough for live US500. Recommended WP-82 source order: use scanner history first for fresh/current signals, fall back to broker-specific historical fetch when available, and return clear `data_unavailable` metadata otherwise. |
| WP-82 | Signal Chart Data API | `[x]` | 2026-05-17 | Added authenticated `GET /talim/operator/signals/{signal_id}/chart?before=50&after=20`. Runtime returns candle payloads, EMA(8)/EMA(21) overlays, signal visible index, side/entry/stop/target/rationale/regime/validation context, source metadata, and warnings. Source order is scanner in-memory history first, `fetch_bars_before(...)` broker history fallback for FOREX.com-style feeds, `fetch_recent_bars(...)` fallback for recent-capable feeds, then explicit `data_unavailable`. Bounds query windows to 1–500 pre-bars and 0–500 post-bars. |
| WP-83 | Signal Detail Chart UI | `[x]` | 2026-05-17 | Added TradingView Lightweight Charts to `/talim/dashboard/signal.html?signal=<signal_id>` while keeping the static FastAPI HTML/JS dashboard architecture. The signal page now fetches `/talim/operator/signals/{signal_id}/chart`, renders candlesticks, EMA(8), EMA(21), nearest EMA-cross marker, long/short signal marker, entry/stop/target horizontal price lines, fit button, warning/status metadata, and built-in drag/wheel/pinch zoom/pan. Follow-up fix: periodic refresh now updates live status without rebuilding/resetting the chart, manual refresh preserves the visible range, chart gestures avoid mobile pull-refresh, and panning/zooming near edges expands the chart window up to the API cap. Added dashboard asset tests for the chart page/JS. |
| WP-84 | Decision-Friendly Visual Context | `[x]` | 2026-05-17 | Added a compact “Decision context” panel below the signal chart. It summarizes whether the linked signal is current/historical, fresh/stale bars-since-signal state, live price movement from entry in R/ATR/current-price terms, regime, approval allowed/blocked reason, chart data source/candle count, and a plain-English EMA(8)/EMA(21) cross interpretation that says whether the cross supports or conflicts with the signal direction. The chart fetch now degrades gracefully so detail/decision context can still render if chart data is unavailable. |
| WP-85 | EMA-Cross Alert Noise Reduction | `[x]` | 2026-05-17 | Reduced noisy momentum EMA-cross HITL alerts in the scanner. Signals generated only from old crosses inside the warm-up window are no longer emitted; duplicate same-strategy/instrument/side/timestamp emissions across repeated scans of the same latest bar are suppressed; and momentum strategies are blocked while the persisted regime is `ranging`. Added regression tests covering latest-bar signal emission, stale warm-up cross suppression, duplicate same-bar suppression, and ranging-regime momentum suppression. |

## Phase 17: Backtest Realism & Comparison Discipline

| WP | Name | Status | Session Date | Notes |
|----|------|--------|--------------|-------|
| WP-86 | Standardised Backtest Cost Model (BR-05) | `[~]` | 2026-07-12 | Added `talim/backtest/costs.py` (`BacktestCostConfig`: spread/slippage points + per-side commission, mid-based adverse fills, fail-loud `load_cost_config`), `config/backtest_costs.json` (forexcom/ig/dukascopy-proxy × US500/AU200; proxy datasets charge the live venue's costs), `Trade.fees`, engine wiring via `run_backtest(costs=...)`, CLI `--costs-venue`/`--costs-config` (frictionless runs warn), and `tests/test_costs.py`. Default stays frictionless so recorded baselines are unchanged. Remaining: verify assumption values against live demo bid/ask snapshots (needs broker creds — checklist in `docs/backtest-cost-assumptions.md`), then run `scripts/rerecord_baselines.py` on the deploy host to capture costed baselines (manifest: `config/backtest_baselines.json`). |
| WP-87 | Baseline Comparison Rules (BR-04) | `[!]` | 2026-07-12 | Proposal drafted at `docs/backtest-comparison-rules.md`: valid-comparison preconditions, one-baseline-per-strategy/instrument/timeframe, ≥30-trade admissibility floor, +10% relative Sharpe with max-DD/trade-count guardrails, holdout-segment hygiene, recording requirements. Blocked on Justin sign-off (3 open questions at the end of the doc); once approved, gates can be encoded into comparison tooling and baselines re-recorded with WP-86 costs. |
| WP-88 | Indicator Research Batch 2 (BR-03) | `[~]` | 2026-07-12 | Batch defined at `docs/indicator-research-batch-2.md`, driven by three observed problems: EMA-cross whipsaw (WP-85 guards are scanner-only, so backtests never see them — a strategy-level filter is the gap), rigid fixed stop/target exits, and Bollinger-only mean reversion. Priority order: ADX/DMI (port fingerprint maths into the shared indicator library as a momentum entry filter), Keltner Channels (+BB/KC squeeze), SuperTrend trailing exits, Kaufman Efficiency Ratio; session-anchored VWAP and OBV are gated on a broker/Dukascopy volume-quality audit. Per-indicator DoD: streaming+vectorised parity impl (WP-71 pattern) → feature builder + CLI (features pipeline pattern) → pre-registered hypothesis → costed backtest vs baseline under WP-87 gates → keep/kill verdict logged. Items 1–4 implementation is agent-pickable now; evaluation blocked on costed baselines + WP-87 sign-off. |

---

## Session Log

| Date | WP(s) | Summary | Outcome |
|------|-------|---------|---------|
| 2026-04-06 | WP-01 | Core data models, pyproject.toml, 18 unit tests | All green |
| 2026-04-06 | WP-02 | Regime fingerprint, k-means classifier, session matcher, library builder, 25 tests | All green |
| 2026-04-06 | WP-03 | BaseStrategy, loader, store, momentum-ES, mean-reversion-ES, 19 tests | All green (62 total) |
| 2026-04-06 | WP-04 | EpisodicMemory, PatternMemory, WorkingMemory (SqliteSaver), 13 tests | All green |
| 2026-04-06 | WP-05 | Event types, publisher, subscriber, connection factory, 10 tests (fakeredis) | All green |
| 2026-04-07 | WP-06 | BasePriceFeed, MockPriceFeed (DataFrame/Parquet/CSV), Binance scaffold, normaliser, 14 tests | All green |
| 2026-04-07 | WP-07 | BaseExchange, MockExchange (orders/positions/balance), ccxt impl, credential loader, 17 tests | All green (116 total) |
| 2026-04-07 | WP-08 | LangGraph StateGraph, stub nodes, checkpointer, cron/bridge entrypoints, 13 tests | All green (129 total) |
| 2026-04-06 | WP-09 | Signal scanner node: ScannerContext DI, ATR/fingerprint compute, strategy iteration, regime change detect, 11 tests | All green (140 total) |
| 2026-04-07 | WP-10 | Router node + edges module, deterministic 5-branch routing with priority, 13 tests | All green (153 total) |
| 2026-04-07 | WP-11 | HITL interrupt node, signal formatter, resume_graph w/ checkpoint persistence, interrupt_after compile, 12 tests | All green (165 total) |
| 2026-04-07 | WP-12 | Backtest engine (on_bar replay), data loader, metrics, multi-variant comparison, backtest_run node, 14 tests | All green (179 total) |
| 2026-04-07 | WP-13 | LLMClient (Claude+Ollama), prompt templates, MockLLMClient, fallback paths, 15 tests | All green (194 total) |
| 2026-04-07 | WP-14 | converse/strategy_update/notify nodes, llm_context DI, JSON proposal parsing, 17 tests | All green (211 total) |
| 2026-04-07 | WP-15 | Discord connector: embed formatter, ReactionHandler, TalimDiscordBot wrapper, 19 tests | All green (230 total) |
| 2026-04-07 | WP-16 | FastAPI bridge (/talim/converse, /talim/resume), shared-secret auth, 13 tests | All green (243 total) |
| 2026-04-07 | WP-17 | risk_check node + RiskRules (qty/exposure/dd/correlation), JSON loader, blocks routed through notify, 14 tests | All green (257 total) |
| 2026-04-07 | WP-18 | Dockerfile, docker-compose (redis/talim/scheduler/nginx), nginx.conf, healthcheck.sh, .env.example, cron.txt | 8 file-shape tests |
| 2026-04-07 | WP-19 | Full simulated market day e2e: scan→signal→risk→HITL→resume→fill→bridge Q&A→strategy update→backtest→memory | 266 total tests green |
| 2026-04-11 | WP-34 | Position monitor node: _check_exit for long/short stops+targets, wired between scanner→router in graph, 17 tests | All green (319 total) |
| 2026-04-11 | WP-35 | Reconcile node: reconcile_positions diffs exchange vs memory vs state, RepairEvent, surfaces divergences via pending_notification, 11 tests | All green (330 total) |
| 2026-04-11 | WP-36 | PnLTracker: refresh from exchange, daily_pnl accumulation, session rollover reset, custom timezone, PnLSnapshot, 9 tests | All green (339 total) |
| 2026-04-11 | WP-38 | POST /talim/trigger endpoint, supercronic scheduler container in compose, cron.txt updated to use HTTP triggers, 3 new tests | All green (342 total) |
| 2026-04-11 | WP-39 | config/risk.json template, validate_config + load_validated_config, kill switch (halted field, /halt + /resume-trading + /halt-status endpoints, risk_check blocks when halted), 18 tests | All green (360 total) |
| 2026-04-11 | WP-41 | JSONFormatter structured logging, METRICS singleton (counters+gauges), /metrics Prometheus endpoint, risk_check+execute instrumented, ops/grafana/talim.json dashboard, 8 tests | All green (368 total) |
| 2026-04-11 | WP-43 | scripts/backup.sh (sqlite3 .backup + optional S3 upload + 7-day prune), cron entries (hourly + daily), Redis AOF enabled, docs/disaster-recovery.md runbook, 4 tests | All green (372 total) |
| 2026-04-12 | WP-32 | Exchange factory (mock/testnet/live), CcxtExchange mocked integration tests (order/position/balance/cancel), docs/exchange-setup.md runbook + soak checklist, 16 tests | All green (388 total) |
| 2026-04-12 | WP-46 | Removed the bundled NanoClaw stub container/package, kept the bridge API intact, updated compose/docs/tests to treat assistant integration as external | Targeted tests green |
| 2026-04-12 | WP-48, WP-49 | Added canonical CFD spec/registry package, AU200 cash/fwd registry config, IG market discovery client + CLI, verified demo auth, and resolved initial AU200 IG epics | 25 targeted tests green plus live demo discovery; remaining contract details will land in WP-50/WP-52 |
| 2026-04-12 | WP-50 | Added the first real IG OTC exchange adapter, wired `create_exchange(..., exchange_name=\"ig\")`, and covered market/limit/cancel/balance/positions with mocked tests | 32 targeted tests green |
| 2026-04-13 | WP-51 | Added IG REST price feed, local snapshot bar builder, scanner polling/backfill hooks, price-feed factory, and Parquet ingestion CLI; verified against IG demo bars | 33 feed/scanner tests green plus live AU200 bar fetch |
| 2026-04-13 | WP-52 | Added CFD session gating, point-value exposure/margin checks, financing-aware `PnLSnapshot`, account-currency selection, and netted CFD reconciliation normalisation | 102 targeted/regression tests green |
| 2026-04-13 | WP-53 | Added `momentum-AU200`, timeframe-aware backtest inputs, AU200 dataset/backtest CLIs, demo soak docs, and ran the first AU200 baseline backtest on live IG demo historical data | 88 strategy/backtest tests green plus IG dataset build and baseline backtest run |
| 2026-04-18 | WP-59 | Verified FOREX.com AU demo auth + account entitlement, resolved AU200 MarketIds (404709651 cash, 406055157 Jun-26), wrote feasibility/mapping/gap-analysis doc at docs/forexcom-cfd-feasibility.md | Go decision; no Phase 10 contract changes required (one optional capability flag for FIFO hedging model) |
| 2026-04-18 | WP-60 | ForexcomDiscoveryClient + ForexcomExchange (BaseExchange) + ForexcomPriceFeed (BasePriceFeed with REST bar polling) + normaliser + factory wiring + AU200 cash/fwd forexcom mappings; registry gained `fifo_stack` position model and `requires_quote_prior_to_order` flag | 13 new tests green (439 total); live smoke against demo validated auth, market search, market info, registry patch, and bar fetch |
| 2026-04-18 | WP-61 | Broker-agnostic CFD conformance suite (tests/test_cfd_conformance.py, VenueFixture parametrised across IG + FOREX.com covering canonical resolution, market/limit semantics, cancel round-trip, position canonicalisation, balance shape) + shared demo soak runbook at docs/cfd-soak-runbook.md (regression checklist, per-session/daily/weekly parity checks, go/no-go, new-venue onboarding gate) | 10 new tests green (449 total across the full non-e2e suite) |
| 2026-04-18 | WP-62 | Added `talim.app.runtime.bootstrap_runtime()` to create the selected exchange/feed, subscribe instruments, load strategy packages, configure scanner/execute/risk, refresh positions/account balance into graph state, and share one persistent checkpoint DB across trigger/resume/bridge paths; Docker image now includes config/scripts and Compose forwards runtime env vars | 5 new runtime tests plus 68 targeted bridge/deployment/exchange/feed/execute tests green |
| 2026-04-18 | WP-63 | Added `talim.app.demo_harness.run_mock_demo_execution()` and `scripts/run_demo_execution.py` to run a deterministic full mock execution loop through runtime bootstrap, scanner, HITL pause, resume approval, execute, episodic memory, and reconciliation; documented IG/FOREX.com demo progression in docs/live-demo-execution.md | 32 targeted graph/runtime/checkpoint/e2e tests green; CLI smoke returns 1 order, 1 position, 1 decision, 0 reconciliation divergences |
| 2026-04-18 | WP-64 | Added `/talim/operator/status`, `/talim/operator/pending`, `/talim/operator/decision`, `/talim/operator/positions`, and `/talim/operator/decisions` for OpenClaw/operator clients; runtime now exposes checkpoint-backed pending-signal inspection plus serialised positions/decisions | 4 new operator API tests green plus bridge/runtime/demo harness regression tests |
| 2026-04-18 | WP-65 | Added runtime `sync_state()` with persistent `PnLTracker`, `/talim/sync` API, scheduler cron offset after scans, reconciliation notification persistence, paused-HITL checkpoint protection, and docs/runtime-sync.md | 3 new sync API tests plus runtime/reconcile/P&L/deployment regression tests green |
| 2026-04-18 | WP-66 | Added `BaseExchange.close_position()`, safe exit execution that closes matching positions instead of reusing entry-side order mapping, attached stop/target propagation for mock/IG/FOREX.com/ccxt orders, FOREX.com FIFO lot close handling, and soak documentation updates | Full suite green: 468 tests |
| 2026-04-19 | WP-67 | Decided backtest data strategy: IG + FOREX.com historical REST as primary sources (free via existing demo), no QuantConnect (breaks single-strategy-contract invariant), rename `-ES` strategies to `-US500`, US500 chosen as first instrument for WP-73; wrote `docs/backtest-data-strategy.md` | Documentation-only; unblocks WP-73 |
| 2026-04-19 | WP-71 | Added `talim/strategy/indicators/` with 8 indicators (EMA, SMA, Wilder ATR, Wilder RSI, Bollinger, MACD, stochastic, Donchian), each in streaming + vectorised form with parity tests; refactored momentum-ES, mean-reversion-ES, momentum-AU200 through the library; added load_params rebuild hook; wrote `docs/strategy-authoring.md` | 25 new indicator tests; 492 non-e2e tests pass; AU200 baseline backtest numerical output unchanged |
| 2026-04-19 | WP-72 | Added `talim/strategy/params.py` (`ParamSpec`, `StrategyParamError`, `validate_param_dict`); `BaseStrategy.load_params` validates against declared `PARAMS`; declared schemas on all three strategies; backtest engine pre-validates variants before loading data; `scripts/run_backtest.py` exits 2 on invalid params; `strategy_update` node rejects invalid LLM proposals and surfaces the reason in pending_notification; new `GET /talim/operator/strategies/{name}/params` endpoint returns schema + current values | 25 new tests; 517 non-e2e tests pass; AU200 baseline backtest numerical output unchanged |
| 2026-04-19 | WP-68 | Added `talim/backtest/history.py` (`BacktestHistory` + `backtest_runs` SQLite schema at `state/backtest_history.db`, env-overridable via `TALIM_BACKTEST_HISTORY_DB`); CLI `scripts/run_backtest.py` and graph node `backtest_run` record every variant (triggered_by = cli/node) and CLI returns the new row ids; Runtime exposes `operator_backtests` / `operator_backtest` and bridge adds `GET /talim/operator/backtests` (filters + pagination) and `GET /talim/operator/backtests/{id}` under shared-secret auth | 13 new tests; 519 non-e2e tests pass |
| 2026-04-19 | WP-70 | Added hot strategy activation: `Runtime._active_strategies` (init from config, mutable for toggles); `enable_strategy` validates by calling `load_strategy` before mutation and registers the instance with the scanner context; `disable_strategy` removes from the active list but leaves in-flight `pending_signal` untouched; `strategy_activations` SQLite table + `EpisodicMemory.record_activation`/`query_activations`; `_discover_strategies()` helper exposes loadable-but-inactive modules; operator endpoints `GET /talim/operator/strategies`, `POST /talim/operator/strategies/{name}/enable` (404 on unknown), `POST /talim/operator/strategies/{name}/disable`; scanner disambiguates `active_strategies=[]` (nothing active) from absent key (fall back to all loaded); `docs/strategy-activation.md` runbook | 12 new tests; 531 non-e2e tests pass |
| 2026-04-19 | WP-73 | Renamed `momentum-ES`/`mean-reversion-ES` → `-US500` across strategies/, test fixtures, vectorbt translator keys, demo harness default, README, and `talim-architecture.md` (IG-allowance blocker noted; FOREX.com used as data fallback). Added `US500.cash` to the CFD registry with IG (`IX.D.SPTRD.IFA.IP`, US 500 Cash A$1) and FOREX.com (`404706660`, US SP 500 CFD) mappings — both resolved against live demos. New `scripts/ingest_forexcom_prices.py`; ingested 4000 × 1h (~8 months) + 4000 × 5m (~2.5 weeks) of US500.cash into `data/forexcom/US500.cash/` with dataset manifest. Hardened `talim/backtest/data_loader.load_ohlcv` (explicit timeframe now required to exist — no silent fallback, empty frames raise) and `scripts/run_backtest.py` (requires `--instrument`, surfaces data errors with exit 2, warns on zero-trade results). Captured default-param baselines (momentum/mean-reversion × 5m/1h) in `docs/backtest-baselines/us500-2026-04-19.json` with runbook at `docs/backtest-us500-runbook.md` | 2 new data-loader tests; 545 tests pass |
| 2026-04-19 | WP-69 | Added static operator dashboard mounted by the bridge at `/talim/dashboard/` (`talim/api/static/{index.html,app.js,style.css}` via `StaticFiles(html=True)`). Panels: runtime status, open positions, pending HITL (approve/reject), strategies (enable/disable), decisions (filter by instrument/strategy/limit), backtest history with click-to-expand detail, daily + open P&L. Header has a two-step unlock flow: secret stored in `sessionStorage` (reads), in-memory `unlocked` flag (writes) that resets on page refresh. Extended `runtime.operator_status()` with `open_pnl`/`daily_pnl` via the existing `_safe_pnl_snapshot` path. 4 new smoke tests in `tests/test_bridge.py::TestOperatorDashboard`; `docs/operator-dashboard.md` runbook | 4 new tests; 28/28 bridge+runtime+operator tests pass |
| 2026-04-22 | WP-47 | Made the deployment migratable: `talim-state` and `redis-data` named volumes replaced with `./state` and `./redis` bind mounts; added `./backups` bind mount on `talim` and `scheduler`; surfaced `TALIM_BACKTEST_HISTORY_DB`/`TALIM_STATE_DIR`/`TALIM_BACKUP_DIR` in compose env + `.env.example`; committed `state/`, `redis/`, `backups/` via `.gitkeep` so a fresh clone has bind sources; swept docs of hardcoded `/Users/justinluu/...` paths (now repo-relative); added `docs/vps-migration.md` runbook covering provision → rsync state → start compose → verify → cutover → decommission; cross-linked from `docs/laptop-setup.md`; new `tests/test_deployment_layout.py` (16 static checks) ensures no future regressions reintroduce named volumes; updated `tests/test_backup.py::TestDockerComposeAOF` to assert the new `./redis:/data` mount | 17 new/updated tests; 558 non-e2e tests pass |
| 2026-05-14 | WP-75–WP-80 | Planned the next operator approval architecture after live US500 enablement exposed HITL alerting and stale-approval gaps: OpenClaw posts Discord alerts to <#1497790419076120576>, Talim adds durable per-signal ids/records, dashboard deep links, strategy-specific validation status, and approval-time validation enforcement. | Plan added to Phase 15; implementation order: WP-75 quick alert watcher first, then WP-76–WP-78 safety core, then WP-79 dashboard UX and WP-80 Paige command path |
| 2026-05-14 | WP-75 | Implemented the OpenClaw-side Talim pending HITL alert watcher. Added `/home/wombat/.openclaw/workspace/tools/talim_pending_alert.py`, local de-dupe state, and cron job `b3345396-2253-43c6-90d2-c6a3c19af4a1` to check every 60 seconds and post new pending-signal alerts to <#1497790419076120576> using OpenClaw's existing Discord connection. | Script smoke test passed: first run emitted alert JSON for current pending US500 signal, second run returned `already_alerted`; cron job created and manually enqueued once for no-alert path |
| 2026-05-14 | WP-76 | Implemented durable signal records and deep links. Added the `signals` table/migration, `EpisodicMemory.record_signal/get_signal/update_signal_status`, pending-signal upsert in runtime, `signal_id`/`dashboard_url` in `/operator/pending`, `GET /operator/signals/{signal_id}`, dashboard display/deep-link warning, helper CLI `signal <id>`, and pending-alert durable-id/deep-link support. | Targeted tests passed (18 bridge/strategy/dashboard tests); rebuilt/restarted `talim-app`; live pending endpoint returned `SIG-0A1C9363FAC8` and detail endpoint returned the persisted row/context |
| 2026-05-14 | WP-77 | Implemented advisory strategy-specific signal validation. Added validation model/default checks, strategy overrides for momentum and mean-reversion packages, runtime validation in `/operator/pending`, persistence of latest validation status/reason to `signals`, and dashboard validation display. | Targeted tests passed (20 bridge/strategy/dashboard tests); rebuilt/restarted `talim-app`; live pending signal `SIG-22DAA53C3A32` returned validation `stale`, approval_allowed=false, reason `signal is 7 bars old; maximum is 3` |
| 2026-05-14 | WP-78 | Implemented approval-time validation enforcement in `Runtime.resume`. Approvals now refresh broker state, run strategy validation, rerun risk checks, block invalid/stale/risk-changed approvals, update durable signal lifecycle status, and only execute when validation/risk allow it. Rejections update signal rows as `rejected`; successful executions move through `approved` to `executed`. | Targeted approval enforcement test passed; regression set now 21 passing tests plus dashboard JS syntax check |
| 2026-05-14 | WP-79 | Implemented the dashboard signal detail page behavior for `/talim/dashboard/?signal=<signal_id>`, then moved it to a standalone mobile-friendly page at `/talim/dashboard/signal.html?signal=<signal_id>`. Added durable signal-row rendering, live current-pending validation comparison, stale/non-current warning, refresh-validation action, validation-gated approve/reject controls, and responsive mobile layout/sticky action controls. | Dashboard/signal JS syntax checks passed; targeted bridge/dashboard and strategy tests passed |
| 2026-05-15 | WP-80 | Implemented Paige/OpenClaw named-signal command path. Added optional `signal_id` to operator decisions, mismatch protection that leaves the pending signal untouched, and helper commands `analyse/analyze`, `approve-signal`, `reject-signal`, and `decision --signal-id`. | Added mismatch test; targeted tests pass |
| 2026-05-17 | WP-81–WP-85 | Researched signal visualization options after noisy EMA(8) cross-below EMA(21) alerts. Recommended TradingView Lightweight Charts with Talim-owned bars/indicators rather than hosted TradingView widgets or a scratch-built renderer. Planned a signal detail chart showing at least 20 pre-signal bars, EMA(8)/EMA(21), signal marker, entry/stop/target, zoom-out support, and validation context before tuning alert noise. | Plan added as Phase 16; next step is WP-81 data-path inspection before implementation |
| 2026-05-17 | WP-81 | Completed chart data-path inspection. Signal lifecycle storage has enough anchor metadata for chart lookup; scanner history has enough recent bars for fresh signals but is volatile; FOREX.com supports timestamp-based historical reconstruction; IG support is currently recent-only in Talim; no durable live bar table exists. | WP-81 complete; WP-82 should implement a chart-data endpoint with scanner-history-first, broker-history fallback, and explicit unavailable/stale-history metadata |
| 2026-05-17 | WP-82 | Implemented the signal chart-data backend. Added runtime chart assembly around durable signals, scanner-history/broker-history/recent-history fallback order, EMA(8)/EMA(21) calculation, entry/stop/target levels, status/source/warnings metadata, and authenticated bridge endpoint `/talim/operator/signals/{signal_id}/chart`. | Targeted runtime + bridge tests pass: `tests/test_runtime.py tests/test_bridge.py` → 27 passed |
| 2026-05-17 | WP-83–WP-85 | Implemented the signal detail chart UI (Lightweight Charts on `signal.html`), the decision-context panel, and EMA-cross alert noise reduction; merged via PR #1 ("Add HITL signal lifecycle safeguards and chart UX"). Full detail in the Phase 16 table notes. | Merged to main; Phase 16 complete |
| 2026-06-21 / 2026-06-23 | — | Discord position-event push notifications: close-out cards on approved exits (instrument, side, entry/exit, P&L, hold time, reason) and 🔵 open cards on filled entries (strategy, entry, stop/target/R:R, regime, ATR, order id) via `TALIM_DISCORD_POSITION_WEBHOOK` (renamed from `TALIM_DISCORD_CLOSEOUT_WEBHOOK`; module now `position_events.py`). Exit fills also flip the matching entry decision from `pending` to `closed` so reconcile stops flagging completed round-trips. | Merged direct to main |
| 2026-07-10 | — | Operations batch: operator open-positions dashboard page; entry/exit decision pairing in the operator decisions table; protective exit signals routed straight to execution (bypassing HITL); FOREX.com fallback to opposite market order when the close route is missing; backtest loader now validates `price_type` and rejects duplicate bars. Dukascopy backfill tooling: tick ingest + canonical bar builder, coverage-scan and gap-retry helper scripts (see WP-74). Added BR/RR roadmap trackers to this file. | Merged direct to main |
| 2026-07-12 | WP-74 (partial), — | PR #2 review hardening: halted-exit warning + pending_notification, FIFO-guarded FOREX.com close fallback (refuses on hedging accounts), strategy-scoped `close_pending_entries`, positions chart instance reuse across polls, lightweight-charts 4.2.3 vendored (no unpkg), decisions `outcome` filter. PR #3: decisions gain explicit `qty` + `entry_decision_id` columns (idempotent migration + backfill), replacing client-side regex pairing heuristics. PRs #4/#6: Dukascopy pull-reliability hardening and `CENTRAL_PROGRESS.md` central index. | Merged to main |
| 2026-07-12 | Tracker refresh | Reviewed outstanding tasks against main: moved WP-74 to `[~]` (Dukascopy source chosen, tooling landed; coverage pulls + gap audit remain, ASK re-pull gated on RR-08), confirmed WP-54–WP-58 (Polymarket) remain untouched, and backfilled session-log entries for work merged 2026-05-17 → 2026-07-12. | Trackers reconciled with main |
| 2026-07-12 | — (test-suite repair) | Full-suite verification found main's HITL-path tests broken since the WP-85 merge (2026-05-17): the noise guardrails (latest-bar-only + ranging-regime suppression) silently killed the signal in the sine-wave fixtures, so the demo harness — the AGENTS.md-designated local execution proof — raised "graph did not pause for HITL approval", and e2e/operator-API tests failed. Nobody noticed because post-May sessions only ran targeted tests. Fixed `build_mock_execution_data` (uptrend + triangular pullback, truncated via new `truncate_to_last_ema_cross` so the EMA(8/21) re-cross lands on the final bar in a non-ranging window) and pointed the e2e fixture at it. Also fixed fresh-clone breakage: declared `langgraph-checkpoint-sqlite` in pyproject (was Dockerfile-only, so `pip install -e .` couldn't import the checkpointer) and committed `data/.gitkeep` (a `tests/test_deployment_layout.py` check asserts `data/` exists but git never created it). Verified no langgraph pin is needed: suite green on latest langgraph 1.2.9. | Full suite green: 681 passed, 0 failed (incl. e2e; backup tests need the `sqlite3` CLI present) |
| 2026-07-12 | WP-86, WP-87 | Promoted BR-05 → WP-86: implemented the standardised backtest cost model (spread/slippage/commission per venue+instrument, mid-based adverse fills, fail-loud config loading, CLI `--costs-venue`, frictionless-run warning, `docs/backtest-cost-assumptions.md` with broker-quote verification checklist). Promoted BR-04 → WP-87: drafted `docs/backtest-comparison-rules.md` comparison/acceptance rules proposal for Justin sign-off. Cost defaults stay frictionless so existing recorded baselines remain valid until re-baselined. | 18 new cost tests; full suite 681 passing |
| 2026-07-12 | — | PR #5 (dashboard UX improvements): operator dashboard UX/reliability improvements plus pre-sign-in halt status in the header. Logged here for tracker completeness; merged without a session entry. | Merged to main |
| 2026-07-12 | WP-86/WP-87 baseline re-record prep + doc refresh | Baselines cannot be re-recorded off-host (datasets live on the deploy host; agent environments lack broker credentials and the proxy blocks Dukascopy), so re-recording is now one command: `scripts/rerecord_baselines.py` runs every entry in new `config/backtest_baselines.json` (US500 momentum/mean-reversion × 5m/1h costed via forexcom; AU200 momentum 1h costed via ig, defaults + both documented variants), records history rows with `triggered_by="baseline"`, and writes `docs/backtest-baselines/baselines-<date>.json`; fails loudly per entry, `--allow-partial` escape hatch; 5 new tests. Declared remaining undeclared runtime deps in pyproject (`pyarrow`, `scikit-learn`, `requests` — imported by talim but previously only transitive installs). Doc refresh: README (status counts, graph diagrams gain `position_monitor` + protective-exit path, WP-78 approval revalidation, expanded operator endpoint list, dashboard section, backtest cost/history/baseline bullets, Dukascopy ingest scripts, setup now just `pip install -e ".[dev]"`), AGENTS.md (US500 live focus, `TALIM_DISCORD_POSITION_WEBHOOK`, HITL/exit semantics, costed-backtest rule), talim-architecture.md (nodes table, router protective-exit branch, current production HITL flow, WP-67/WP-74 data-source table, WP-86 cost note). | 686 tests passing; baseline re-record ready to run on the deploy host |
| 2026-07-12 | WP-54 | Completed the Polymarket feasibility/compliance gate research. Polymarket is a prohibited service in Australia: ACMA issued a formal warning to Adventure One QSS Inc. (Polymarket) in July 2025 and directed an ISP-level block in August 2025 under the Interactive Gambling Act 2001 (triggered by paid-influencer promotion of Australian election markets); Polymarket's own ToS also restrict Australia. Wrote `docs/polymarket-feasibility-gate.md` with a NO-GO recommendation and close/park/alternative-venue options; marked WP-54 `[!]` and gated WP-55–WP-58 on Justin's decision. Also fixed the stale FOREX.com pagination "known limitation" in `docs/backtest-us500-runbook.md` — `ingest_forexcom_prices.py` already supports `--start`/`--end`/`--months` paging, so deeper 5m ingest is a host command, not new code. | WP-54 research done; Phase 11 blocked on Justin decision |
| 2026-07-12 | WP-88 | Completed BR-03: defined Indicator Research Batch 2 at `docs/indicator-research-batch-2.md` after auditing the existing WP-71 indicator library, the `talim/features/` research pipeline, and the fingerprint-only ADX. Batch: ADX/DMI → Keltner → SuperTrend → Efficiency Ratio (implementable now, no data/creds needed), VWAP/OBV gated on a volume-quality audit. Each indicator carries a definition-of-done ending in a costed-backtest keep/kill verdict under WP-87 gates. Registered the doc as an agent-pickable work source in `CENTRAL_PROGRESS.md`. | Batch defined; implementation open to agents, evaluation gated on host baselines + WP-87 |
