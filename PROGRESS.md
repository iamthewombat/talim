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
| WP-47 | Portable Local Deployment & VPS Migration Layout | `[ ]` | — | Make the laptop stack portable: bind-mounted state, host-agnostic config, restore/migration runbook for later VPS move |

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
| WP-59 | FOREX.com AU Feasibility and Market Mapping | `[ ]` | — | Verify whether the canonical CFD model carries cleanly into FOREX.com AU and document any gaps |
| WP-60 | FOREX.com Exchange and Price Feed Adapters | `[ ]` | — | Implement FOREX.com on top of the broker-neutral CFD interfaces rather than as a parallel stack |
| WP-61 | Multi-Broker CFD Conformance and Demo Regression | `[ ]` | — | Prove the same Talim CFD flow works across IG and FOREX.com adapters with shared tests and demo runbooks |

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
