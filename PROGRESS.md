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

| WP | Name | Status | Session Date | Notes |
|----|------|--------|--------------|-------|
| WP-54 | Polymarket Feasibility, Compliance, and Product Fit Gate | `[ ]` | — | Confirm whether Polymarket is usable for the intended jurisdiction/use case before building a connector |
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
| WP-74 | Pre-2020 Historical Data Source Probe | `[ ]` | — | Find historical data deeper than current FOREX.com coverage for US500/AU200 backtests. Prefer IG/FOREX.com/Dukascopy broker-style data if available; otherwise keep free/paid proxy data separate with source-specific manifests. Initial options note: `docs/pre-2020-historical-data-options.md` |

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
