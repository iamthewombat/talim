# Talim — Work Breakdown for Agentic Build Sessions

> Each work package is designed to be completed in a single coding agent session, is independently testable, and produces artifacts that later packages integrate against. Build order matters for the first few foundation packages; after that, most can be built in parallel.

---

## Build Order Overview

```
Phase 1: Foundation (build in order)
  WP-01  Core data models & shared types
  WP-02  Regime detection engine
  WP-03  Strategy framework & on_bar interface

Phase 2: Infrastructure (parallel)
  WP-04  Memory stores (SQLite — working, episodic, pattern)
  WP-05  Redis event bus wrapper
  WP-06  Price feed connector (WebSocket + normalisation)
  WP-07  Exchange connector (ccxt abstraction)

Phase 3: Brain (build in order, after Phase 1+2)
  WP-08  LangGraph state & graph skeleton
  WP-09  Signal scanner node (cron path)
  WP-10  Router + conditional edges
  WP-11  HITL interrupt node

Phase 4: Intelligence (parallel, after WP-08)
  WP-12  Backtest engine (vectorbt + regime matching)
  WP-13  LLM integration layer (Claude API + Ollama)
  WP-14  Strategy update & notify nodes

Phase 5: Interface (parallel, after WP-08)
  WP-15  Discord bot connector
  WP-16  Bridge API
  WP-17  Risk check node

Phase 6: Deployment & Integration
  WP-18  Docker Compose stack + deployment config
  WP-19  End-to-end integration test (simulated market day)
```

---

## Phase 1: Foundation

### WP-01 — Core Data Models & Shared Types

**Goal:** Establish every shared type so all future work packages import from one place.

**Deliverables:**
- `talim/models/bar.py` — `OHLCVBar` dataclass
- `talim/models/position.py` — `Position` dataclass (instrument, side, qty, entry_price, stop, target, open_pnl, strategy)
- `talim/models/signal.py` — `Signal` dataclass (instrument, strategy, side, entry_price, stop, target, rationale, regime_context)
- `talim/models/backtest.py` — `BacktestRequest` and `BacktestResult` dataclasses
- `talim/models/state.py` — `TalimState` TypedDict (the full LangGraph state schema)
- `talim/models/__init__.py` — re-exports everything
- `pyproject.toml` — project scaffold with dependencies (langgraph, pandas, numpy, ccxt, vectorbt, etc.)

**Tests:**
- Unit tests that instantiate every model with valid data
- Unit tests that verify `TalimState` TypedDict field completeness against the architecture doc
- Serialisation round-trip tests (model → dict → model)

**Verification:** `pytest tests/test_models.py` — all green.

**Session prompt hint:**
> "Create the Python project scaffold for Talim. Define all shared data models as dataclasses and TypedDicts based on the architecture doc. Include pyproject.toml with all dependencies. Write comprehensive unit tests."

---

### WP-02 — Regime Detection Engine

**Goal:** Pure-Python regime fingerprinting and classification — no LLM, no external dependencies beyond numpy/pandas.

**Deliverables:**
- `talim/regime/fingerprint.py` — `compute_fingerprint(bars: pd.DataFrame) -> np.ndarray` (the 6-feature vector)
- `talim/regime/classifier.py` — `classify_regime(fingerprint: np.ndarray) -> str` using k-means (k=4) against a pre-fitted cluster model
- `talim/regime/matcher.py` — `find_similar_sessions(fingerprint, library_features, library_dates, threshold) -> list[date]`
- `talim/regime/library.py` — functions to build and update the regime fingerprint library from Parquet OHLCV data
- Helper: `compute_adx(bars, period)` and `compute_atr(bars, period)`

**Tests:**
- Unit test `compute_fingerprint` against a known 50-bar synthetic DataFrame — assert output shape `(6,)` and values within expected ranges
- Unit test `classify_regime` with synthetic fingerprints at cluster centroids — assert correct labels
- Unit test `find_similar_sessions` — create a library of 100 random fingerprints, query with a known near-duplicate, assert it's returned
- Performance test: `find_similar_sessions` on 2000 rows completes in < 10ms

**Verification:** `pytest tests/test_regime.py` — all green. Also run a standalone script that generates synthetic bars, computes fingerprints, fits k-means, and prints regime labels.

**Session prompt hint:**
> "Build the regime detection engine for Talim. Implement fingerprint computation (6-feature vector), k-means regime classification, and nearest-neighbour session matching. Use only numpy and pandas. Write thorough tests with synthetic data. Import OHLCVBar from talim.models."

---

### WP-03 — Strategy Framework & on_bar Interface

**Goal:** Establish the strategy code + markdown structure so strategies are runnable in both live and backtest modes.

**Deliverables:**
- `talim/strategy/base.py` — `BaseStrategy` abstract class with `on_bar(bar: OHLCVBar) -> Signal | None`, `load_params()`, `name` property
- `talim/strategy/loader.py` — `load_strategy(name: str) -> BaseStrategy` (imports from `strategies/{name}/strategy.py`)
- `talim/strategy/store.py` — `StrategyStore` class with `read(name) -> str`, `write(name, content)`, `list_strategies() -> list[str]` for the markdown files
- `strategies/momentum-ES/strategy.py` — example strategy implementing `on_bar` with EMA crossover logic
- `strategies/momentum-ES/momentum-ES.md` — example strategy markdown following the template from the architecture doc
- `strategies/mean-reversion-ES/strategy.py` — second example (Bollinger Band mean-reversion)
- `strategies/mean-reversion-ES/mean-reversion-ES.md`

**Tests:**
- Unit test: load `momentum-ES`, feed it 100 synthetic bars, verify it returns `Signal` objects at expected crossover points
- Unit test: load `mean-reversion-ES`, same pattern
- Unit test: `StrategyStore.read` / `write` / `list_strategies`
- Integration test: verify `strategy.on_bar(bar)` signature is identical across live and backtest paths (parity rule)

**Verification:** `pytest tests/test_strategy.py` — all green.

**Session prompt hint:**
> "Build the strategy framework for Talim. Create a BaseStrategy abstract class with on_bar interface, a strategy loader, and a markdown strategy store. Implement two example strategies (momentum EMA crossover, mean-reversion Bollinger). Ensure parity — same code runs in live and backtest. Write tests."

---

## Phase 2: Infrastructure (parallel builds)

### WP-04 — Memory Stores (SQLite)

**Goal:** Set up all three SQLite-backed memory stores with clean APIs.

**Deliverables:**
- `talim/memory/episodic.py` — `EpisodicMemory` class wrapping the `decisions` table. Methods: `record_decision(...)`, `query_decisions(instrument, strategy, date_range) -> list[dict]`, `get_stats(strategy) -> dict`
- `talim/memory/pattern.py` — `PatternMemory` class wrapping the `regime_library` table. Methods: `get_library() -> tuple[np.ndarray, list[date]]`, `update_library(fingerprints, dates)`, `rebuild_from_parquet(data_dir)`
- `talim/memory/working.py` — thin wrapper confirming LangGraph's `SqliteSaver` works with `TalimState`; this is mostly a test/validation package
- Database schema migration script: `talim/memory/schema.sql`

**Tests:**
- `EpisodicMemory`: insert 50 decisions, query by instrument, query by date range, verify stats aggregation
- `PatternMemory`: rebuild from synthetic Parquet, query library, verify shapes
- `WorkingMemory`: checkpoint a `TalimState`, restore it, assert equality
- Concurrency test: two writers to episodic memory don't corrupt

**Verification:** `pytest tests/test_memory.py` — all green.

**Session prompt hint:**
> "Build the three SQLite memory stores for Talim: episodic (decisions table), pattern (regime_library table), and working (LangGraph SqliteSaver validation). Include schema creation, CRUD methods, and thorough tests. Import models from talim.models."

---

### WP-05 — Redis Event Bus Wrapper

**Goal:** Thin abstraction over Redis Streams for internal pub/sub.

**Deliverables:**
- `talim/bus/events.py` — event type definitions (`BarEvent`, `RegimeChangeEvent`, `SignalEvent`, `TradeEvent`)
- `talim/bus/publisher.py` — `EventPublisher` class: `publish(stream_name, event)`
- `talim/bus/subscriber.py` — `EventSubscriber` class: `subscribe(stream_name, handler, consumer_group)`
- `talim/bus/connection.py` — Redis connection factory with retry logic

**Tests:**
- Integration test (requires Redis): publish a `BarEvent`, subscribe and receive it, assert data integrity
- Integration test: publish 100 events rapidly, subscriber receives all 100 in order
- Unit test: event serialisation/deserialisation round-trip

**Verification:** `pytest tests/test_bus.py` — all green (needs a running Redis instance or use `fakeredis` for unit tests).

**Session prompt hint:**
> "Build a Redis Streams event bus wrapper for Talim. Define event types (bar, regime change, signal, trade), create publisher/subscriber classes with consumer groups, and write integration tests. Use fakeredis for unit tests, real Redis for integration."

---

### WP-06 — Price Feed Connector

**Goal:** WebSocket connections to exchanges, normalising all data to OHLCVBar.

**Deliverables:**
- `talim/connectors/pricefeed/base.py` — `BasePriceFeed` ABC with `connect()`, `disconnect()`, `subscribe(instrument)`, `on_bar` callback
- `talim/connectors/pricefeed/binance.py` — Binance WebSocket implementation via `ccxt.pro`
- `talim/connectors/pricefeed/mock.py` — `MockPriceFeed` that replays bars from a Parquet file (for testing and backtesting)
- `talim/connectors/pricefeed/normaliser.py` — converts exchange-specific bar formats to `OHLCVBar`

**Tests:**
- Unit test: `MockPriceFeed` replays 200 bars from a fixture Parquet file, verify each is a valid `OHLCVBar`
- Unit test: normaliser handles Binance kline format correctly
- Integration test (optional, needs API): connect to Binance testnet, receive one bar

**Verification:** `pytest tests/test_pricefeed.py` — all green.

**Session prompt hint:**
> "Build the price feed connector for Talim. Create a base ABC, a Binance WebSocket implementation using ccxt.pro, a mock feed that replays from Parquet files, and a normaliser. Focus on the mock feed being solid — it's critical for testing and backtesting."

---

### WP-07 — Exchange Connector

**Goal:** Unified order execution interface across venues.

**Deliverables:**
- `talim/connectors/exchange/base.py` — `BaseExchange` ABC: `place_order(...)`, `cancel_order(...)`, `get_positions()`, `get_account_balance()`
- `talim/connectors/exchange/ccxt_exchange.py` — implementation using `ccxt` for Binance/Bybit
- `talim/connectors/exchange/mock_exchange.py` — `MockExchange` that records orders in memory and simulates fills (for testing)
- `talim/connectors/exchange/credentials.py` — credential loading from env vars (never from disk at runtime)

**Tests:**
- Unit test: `MockExchange` — place order, verify it appears in `get_positions()`, cancel it, verify removed
- Unit test: credential loader reads from env vars, raises on missing keys
- Integration test (optional, needs testnet): place and cancel an order on Binance testnet

**Verification:** `pytest tests/test_exchange.py` — all green.

**Session prompt hint:**
> "Build the exchange connector for Talim. Create a base ABC, a ccxt implementation for Binance/Bybit, and a mock exchange for testing. The mock should simulate order placement, fills, positions, and balance. Include credential loading from env vars."

---

## Phase 3: Brain (sequential builds)

### WP-08 — LangGraph State & Graph Skeleton

**Goal:** The runnable LangGraph graph with all nodes stubbed — the central nervous system.

**Deliverables:**
- `talim/app/state.py` — `TalimState` TypedDict (imported from models, re-exported here for LangGraph)
- `talim/app/graph.py` — `StateGraph` definition with all nodes registered and all conditional edges wired
- `talim/app/nodes/__init__.py` — stub implementations for every node (each returns state unchanged with a log message)
- `talim/app/checkpointer.py` — SqliteSaver setup
- `talim/app/entrypoints.py` — two entry functions: `cron_trigger(state)` and `bridge_message(state, message)`

**Tests:**
- Integration test: invoke the graph via `cron_trigger` with a minimal state, verify it traverses `signal_scanner → router → END`
- Integration test: invoke via `bridge_message` with a user question, verify it traverses `converse → router → notify → END`
- Checkpoint test: run graph, kill process, restart, verify state is restored from SQLite

**Verification:** `pytest tests/test_graph.py` — all green. The graph runs end-to-end with stubs.

**Session prompt hint:**
> "Build the LangGraph graph skeleton for Talim. Define the StateGraph with TalimState, register all nodes as stubs (signal_scanner, converse, router, risk_check, execute, strategy_update, backtest_run, notify, hitl_interrupt). Wire all conditional edges per the architecture. Implement SqliteSaver checkpointing. Write integration tests that invoke both the cron and bridge entry points."

---

### WP-09 — Signal Scanner Node (Cron Path)

**Goal:** Replace the `signal_scanner` stub with real logic — pulls bars, computes ATR/regime, checks thresholds.

**Deliverables:**
- `talim/app/nodes/signal_scanner.py` — real implementation: reads latest bars from price feed, computes fingerprint using regime engine, updates `current_bar`, `atr_current`, `atr_ratio`, `regime`, `regime_fingerprint` on state, checks active strategies for signal thresholds
- Integrates with: `talim/regime/`, `talim/strategy/`, `talim/connectors/pricefeed/`

**Tests:**
- Unit test: feed the node a state with mock price data, assert state fields are updated correctly
- Unit test: feed data that crosses a strategy threshold, assert `pending_signal` is populated
- Unit test: feed data that doesn't cross any threshold, assert `pending_signal` is None
- Integration test: wire into the graph, run a full cron cycle with MockPriceFeed

**Verification:** `pytest tests/test_signal_scanner.py` — all green.

**Session prompt hint:**
> "Implement the signal_scanner node for Talim's LangGraph graph. It should pull the latest bars (via price feed connector), compute ATR and regime fingerprint (using the regime engine), update all market state fields, and check active strategies for signal thresholds. Use dependency injection so tests can use MockPriceFeed. Write thorough tests."

---

### WP-10 — Router + Conditional Edges

**Goal:** Replace the `router` stub with real branching logic.

**Deliverables:**
- `talim/app/nodes/router.py` — inspects state and returns one of: `"end"`, `"strategy_update"`, `"notify"`, `"backtest_run"`, `"risk_check"`
- `talim/app/edges.py` — conditional edge functions that map router output to next node

**Routing rules (deterministic, no LLM):**
```
pending_signal is not None           → "risk_check"
regime changed since last check      → "strategy_update"
pending_backtest is not None         → "backtest_run"
last_user_message is not None        → "notify"
otherwise                            → "end"
```

**Tests:**
- Unit test: one test per routing branch — craft a state that triggers each path, assert correct output
- Integration test: run full graph with states that exercise each branch

**Verification:** `pytest tests/test_router.py` — all green.

**Session prompt hint:**
> "Implement the router node and conditional edges for Talim's LangGraph graph. The router is deterministic (no LLM) — it inspects state fields and returns a branch name. Implement all 5 routing paths from the architecture. Write one test per routing branch plus integration tests through the full graph."

---

### WP-11 — HITL Interrupt Node

**Goal:** Implement the human-in-the-loop freeze/resume mechanism.

**Deliverables:**
- `talim/app/nodes/hitl_interrupt.py` — formats the pending signal into a rich message, uses LangGraph's native interrupt mechanism to freeze the graph, handles resume with approval/rejection
- `talim/app/resume.py` — `resume_graph(thread_id, approved: bool)` function that resumes a frozen graph

**Tests:**
- Integration test: trigger a signal → graph freezes at HITL → call resume with `approved=True` → verify graph continues to `execute` node
- Integration test: same but `approved=False` → verify graph goes to END, `pending_signal` is cleared
- Persistence test: freeze graph, restart process, resume — verify full context is preserved

**Verification:** `pytest tests/test_hitl.py` — all green.

**Session prompt hint:**
> "Implement the HITL (human-in-the-loop) interrupt node for Talim's LangGraph graph. Use LangGraph's native interrupt feature to freeze the graph when a trade signal needs approval. Implement resume logic for both approval and rejection. Test freeze/resume including across process restarts."

---

## Phase 4: Intelligence (parallel builds)

### WP-12 — Backtest Engine

**Goal:** Run vectorbt backtests against regime-matched historical sessions.

**Deliverables:**
- `talim/backtest/engine.py` — `run_backtest(strategy_name, param_variants: list[dict], matched_dates: list[date], data_dir) -> BacktestResult`
- `talim/backtest/data_loader.py` — loads OHLCV Parquet files, filters to matched dates
- `talim/backtest/metrics.py` — computes net_pnl, Sharpe, max_dd, win_rate from vectorbt output
- `talim/app/nodes/backtest_run.py` — LangGraph node that reads `pending_backtest` from state, runs engine, writes `backtest_result`

**Tests:**
- Unit test: run backtest on momentum-ES strategy with synthetic 1-year data, verify result schema
- Unit test: compare two param variants, verify both appear in results
- Unit test: metrics computation against known trade sequences
- Integration test: trigger backtest via graph with a `pending_backtest` in state

**Verification:** `pytest tests/test_backtest.py` — all green.

**Session prompt hint:**
> "Build the backtest engine for Talim using vectorbt. Implement backtest execution with regime-matched date filtering, multi-param-variant comparison, and metrics computation (PnL, Sharpe, max drawdown, win rate). Wire it into the LangGraph graph as the backtest_run node. Write tests with synthetic data."

---

### WP-13 — LLM Integration Layer

**Goal:** Clean abstraction for calling Claude API and Ollama, used by nodes that need LLM reasoning.

**Deliverables:**
- `talim/llm/client.py` — `LLMClient` with `reason(prompt, context) -> str` (Claude API) and `classify(prompt) -> str` (Ollama)
- `talim/llm/prompts.py` — prompt templates for: strategy reasoning, backtest interpretation, regime observation, message classification
- `talim/llm/mock.py` — `MockLLMClient` with canned responses for testing
- Configuration: model selection, API keys from env, fallback behaviour

**Tests:**
- Unit test with `MockLLMClient`: verify each prompt template produces well-formed prompts
- Unit test: verify fallback when Ollama is unavailable (falls back to Claude or returns error gracefully)
- Integration test (optional, needs API keys): call Claude API with a strategy reasoning prompt, verify response is parseable

**Verification:** `pytest tests/test_llm.py` — all green.

**Session prompt hint:**
> "Build the LLM integration layer for Talim. Create a client that wraps both Claude API (for reasoning) and Ollama (for fast classification). Include prompt templates for strategy reasoning, backtest interpretation, regime observation, and message classification. Create a mock client for testing. All API keys from env vars."

---

### WP-14 — Strategy Update & Notify Nodes

**Goal:** Replace stubs with real LLM-powered nodes.

**Deliverables:**
- `talim/app/nodes/strategy_update.py` — reads strategy markdown + regime context, calls Claude API to propose param changes, drafts alert message
- `talim/app/nodes/notify.py` — formats any pending result/observation into a Discord-ready message using Claude API
- `talim/app/nodes/converse.py` — parses incoming user message, loads relevant strategy context into state

**Tests:**
- Unit test with MockLLMClient: strategy_update produces a param change proposal given regime shift
- Unit test: notify formats a backtest result into readable text
- Unit test: converse correctly identifies strategy references in user messages
- Integration test: run graph through `converse → router → notify` path with a user question

**Verification:** `pytest tests/test_llm_nodes.py` — all green.

**Session prompt hint:**
> "Implement the strategy_update, notify, and converse nodes for Talim's LangGraph graph. strategy_update uses Claude to propose param changes based on regime context. notify formats results as Discord messages. converse parses user messages and loads strategy context. Use the LLM integration layer (with mock client for tests)."

---

## Phase 5: Interface (parallel builds)

### WP-15 — Discord Bot Connector

**Goal:** Two-way Discord integration for all three channels.

**Deliverables:**
- `talim/connectors/discord/bot.py` — Discord bot using `discord.py`: listens on `#talim-chat`, posts to `#talim-alerts` and `#talim-log`
- `talim/connectors/discord/formatter.py` — rich embed formatting for signals, backtest results, regime changes
- `talim/connectors/discord/reactions.py` — monitors ✅/❌ reactions on alert messages, translates to resume calls
- Configuration: channel IDs, bot token from env

**Tests:**
- Unit test: formatter produces valid Discord embed structures for each message type
- Unit test: reaction handler maps ✅ to `approved=True` and ❌ to `approved=False`
- Integration test (optional, needs bot token): post a test message to a dev channel, react, verify callback fires

**Verification:** `pytest tests/test_discord.py` — all green.

**Session prompt hint:**
> "Build the Discord bot connector for Talim using discord.py. Implement posting to three channels (alerts, chat, log), rich embed formatting for trade signals and backtest results, and reaction monitoring (✅/❌) that triggers HITL resume. Write unit tests for formatting and reaction handling."

---

### WP-16 — Bridge API

**Goal:** The HTTP bridge between Talim and any external assistant or client.

**Deliverables:**
- `talim/api/bridge.py` — FastAPI app with two endpoints:
  - `POST /talim/converse` — receives Discord message, invokes LangGraph bridge entry point, returns response
  - `POST /talim/resume` — receives approval/rejection, resumes frozen graph
- `talim/api/auth.py` — shared secret auth between bridge clients and Talim (from env var)

**Tests:**
- Unit test: POST to `/talim/converse` with a trading question, verify graph is invoked and response returned
- Unit test: POST to `/talim/resume` with approval, verify graph resumes
- Unit test: auth rejects requests without correct secret
- Integration test: full round-trip — message → bridge → graph → response

**Verification:** `pytest tests/test_bridge.py` — all green.

**Session prompt hint:**
> "Build the bridge API for Talim using FastAPI. Two endpoints: POST /talim/converse (forwards messages to the LangGraph graph) and POST /talim/resume (resumes HITL-frozen graphs). Include shared-secret auth and tests for both endpoints."

---

### WP-17 — Risk Check Node

**Goal:** Validate position limits and risk constraints before any trade executes.

**Deliverables:**
- `talim/app/nodes/risk_check.py` — checks: max position size per instrument, max total exposure, max daily drawdown, correlation between pending and existing positions
- `talim/risk/rules.py` — configurable risk rules loaded from a config file
- Output: either passes signal through to HITL, or blocks it and writes rejection reason to state

**Tests:**
- Unit test: signal within all limits → passes
- Unit test: signal exceeds position size limit → blocked
- Unit test: signal would breach daily drawdown limit → blocked
- Unit test: signal on correlated instrument when already exposed → blocked (or flagged)

**Verification:** `pytest tests/test_risk.py` — all green.

**Session prompt hint:**
> "Implement the risk_check node for Talim's LangGraph graph. Check position size limits, total exposure, max daily drawdown, and correlation with existing positions. Risk rules should be configurable. If any check fails, block the signal and write rejection reason to state. Write tests for each risk rule."

---

## Phase 6: Deployment & Integration

### WP-18 — Docker Compose Stack

**Goal:** The full deployment configuration — everything runs with `docker compose up`.

**Deliverables:**
- `docker-compose.yml` — services: talim, scheduler, redis, nginx
- `talim/Dockerfile` — Python app with all dependencies
- `nginx/nginx.conf` — reverse proxy for bridge API with TLS termination
- `scripts/healthcheck.sh` — verifies all services are running
- `.env.example` — template for all required env vars
- Cron job configs: 5-min heartbeat trigger, nightly data update

**Tests:**
- `docker compose up` starts all services without errors
- Health check script passes
- Bridge API is reachable through nginx
- Redis is accessible from talim container

**Verification:** `docker compose up -d && ./scripts/healthcheck.sh` — all services healthy.

**Session prompt hint:**
> "Create the Docker Compose deployment stack for Talim. Four services: talim (LangGraph app), scheduler, redis, nginx (reverse proxy). Include Dockerfiles, nginx config, healthcheck script, .env.example, and cron job configs. Verify everything starts cleanly."

---

### WP-19 — End-to-End Integration Test (Simulated Market Day)

**Goal:** A single test script that simulates a full market day and exercises every component.

**Deliverables:**
- `tests/e2e/test_market_day.py` — simulates:
  1. Startup: all services initialise, strategies loaded, regime library populated
  2. Morning scan: MockPriceFeed replays 50 bars, regime detected as "momentum"
  3. Signal fires: momentum-ES strategy triggers entry signal
  4. Risk check: passes
  5. HITL: signal posted (to mock Discord), approval received
  6. Execution: MockExchange fills order
  7. User question: "what's my P&L?" via bridge API → response returned
  8. Regime change: mid-day shift to "high_vol", strategy_update triggers
  9. Backtest request: user asks to test tighter stops → backtest runs → results returned
  10. Exit signal: strategy fires exit, HITL approved, position closed
  11. End of day: episodic memory contains all decisions, strategy markdown updated

**Tests:**
- The whole scenario runs end-to-end with mocks for external services (exchange, Discord, LLM)
- Every memory store has expected records
- Final state matches expected portfolio (flat, with realised P&L)

**Verification:** `pytest tests/e2e/test_market_day.py -v` — all green.

**Session prompt hint:**
> "Build an end-to-end integration test for Talim that simulates a full market day. Use MockPriceFeed, MockExchange, MockLLMClient, and mock Discord. Exercise every path: signal scan, regime detection, trade signal, HITL approval, execution, user conversation, regime change, backtest request, exit signal. Verify all memory stores and final state."

---

## Integration Testing Between Work Packages

After building any two connected work packages, run these integration checks:

| After completing... | Test integration with... | How |
|---|---|---|
| WP-02 + WP-04 | Regime → PatternMemory | Compute fingerprints, store in library, query back |
| WP-03 + WP-06 | Strategy → PriceFeed | Feed MockPriceFeed bars into strategy.on_bar() |
| WP-08 + WP-09 | Graph → SignalScanner | Run cron trigger through full graph with real scanner |
| WP-08 + WP-10 | Graph → Router | Verify all 5 routing branches work in the live graph |
| WP-11 + WP-15 | HITL → Discord | Signal posts to Discord, reaction resumes graph |
| WP-11 + WP-16 | HITL → Bridge | Resume via POST /talim/resume |
| WP-09 + WP-12 | Scanner → Backtest | Scanner detects regime, backtest runs on matched dates |
| WP-17 + WP-07 | RiskCheck → Exchange | Approved signal flows to MockExchange execution |

---

## PoC Success Criteria

The PoC is "working" when you can:

1. **Start the stack** with `docker compose up`
2. **Replay historical bars** through MockPriceFeed and see Talim detect regimes and fire signals
3. **Receive a trade alert** in Discord with entry/stop/target and regime context
4. **React with ✅** and see MockExchange log the fill
5. **Ask "what's my P&L?"** in Discord and get an accurate response
6. **Request a backtest** and see results with Sharpe/drawdown comparison
7. **See all decisions** logged in episodic memory

Everything uses mocks for external services (exchanges, real market data) — but the entire pipeline is exercised end-to-end.

---

## Estimated Effort

| Phase | Work packages | Est. sessions |
|-------|--------------|---------------|
| Phase 1: Foundation | WP-01, 02, 03 | 3 sessions |
| Phase 2: Infrastructure | WP-04, 05, 06, 07 | 4 sessions (parallel) |
| Phase 3: Brain | WP-08, 09, 10, 11 | 4 sessions |
| Phase 4: Intelligence | WP-12, 13, 14 | 3 sessions (parallel) |
| Phase 5: Interface | WP-15, 16, 17 | 3 sessions (parallel) |
| Phase 6: Deploy + E2E | WP-18, 19 | 2 sessions |
| **Total** | **19 packages** | **~12–19 sessions** |

With parallel execution in Phases 2, 4, and 5, the critical path is roughly 12 sessions.

---

## Phase 7: Spec Reconciliation (post-audit gaps)

These work packages close gaps found auditing the implementation against `talim-architecture.md` and the original work breakdown. They are not strictly required for the PoC to pass its test suite, but each one corresponds to a documented spec item that the WP-01–WP-19 build skipped or diverged from.

---

### WP-20 — TalimState Field Reconciliation

**Goal:** Bring `TalimState` in line with architecture §3.

**Deliverables:**
- Add missing fields to `talim/app/models/state.py` (or wherever `TalimState` lives): `last_tick`, `instrument`, `open_pnl`, `daily_pnl`, `discord_thread_id`, `messages`, `last_action`.
- Update `signal_scanner` to populate `last_tick` / `instrument` as it iterates bars.
- Update `execute` to update `open_pnl` / `last_action` after a fill, and `daily_pnl` rollups.
- Update `risk_check` to read `daily_pnl` from state (currently the drawdown rule has nothing to read).
- Update `converse` / bridge entrypoint to thread `discord_thread_id` and append to `messages`.

**Tests:**
- Unit: scanner writes `last_tick` and `instrument`.
- Unit: risk_check blocks when `state["daily_pnl"]` exceeds `max_daily_drawdown`.
- Unit: execute updates `open_pnl` / `last_action`.
- Regression: existing 266 tests still pass.

---

### WP-21 — Episodic Memory Schema Alignment

**Goal:** Match the architecture §5.1 schema so analytics queries work.

**Deliverables:**
- Add columns to `episodic.db`: `signal_type`, `atr_ratio`, `action`, `notes` (additive — keep current columns for back-compat or migrate).
- Update `EpisodicMemory.record_decision` signature + call sites (`execute`, e2e test) to populate the new columns.
- Migration helper for existing dbs.

**Tests:**
- Unit: record + query round-trips all spec columns.
- Migration test: open an old-shape db, run migration, verify new columns exist with sane defaults.

---

### WP-22 — Regime Engine Spec Alignment

**Goal:** Reconcile labels and fingerprint features with architecture §2 / §7.2.

**Deliverables:**
- Rename `low_vol` → `ranging` across classifier, library builder, tests, prompts, README.
- Add the spec's missing fingerprint features: `price_position`, `range_expansion`, `session_return`. Decide whether to replace or extend the current 6-feature vector (document the choice).
- Implement matcher domain filters (§7.2): exclude macro-event days, match by session type, require ≥30 historical matches before returning a match (otherwise return None).
- Macro event calendar stub (`talim/regime/calendar.py`) — JSON-driven, hand-curated for the PoC.

**Tests:**
- Unit: classifier emits `ranging` instead of `low_vol`.
- Unit: matcher returns None when fewer than 30 candidates remain after filtering.
- Unit: macro-event date is excluded from matcher candidates.

---

### WP-23 — Real Execute Node + Exit Signal Path

**Goal:** Replace the stub `execute` node with a real exchange call, and wire the exit-signal half of the trade lifecycle (WP-19 step 10).

**Deliverables:**
- `execute` node calls `exchange.place_order(...)` using injected exchange context (mirror the `configure_scanner` DI pattern).
- Episodic memory write moves into `execute` (so the e2e test no longer records the decision manually).
- Exit-signal handling: `signal_scanner` emits exit signals when a strategy's `on_bar` returns `Signal(action="exit")` (or equivalent); routed through risk_check (lighter rules) → HITL → execute → close position.
- Update `MockExchange.close_position` if missing.

**Tests:**
- Unit: execute calls the configured exchange exactly once and writes an episodic record.
- Unit: exit-signal flow closes an open position end-to-end.
- Update e2e test to remove the manual `place_order` and assert the execute node did it.

---

### WP-24 — HITL P&L Projection in Alerts

**Goal:** Architecture §4.4 — Discord alerts should show projected $ risk/reward against account size.

**Deliverables:**
- Pass account balance into `format_signal_embed` (or fetch from exchange context).
- Compute `risk_$ = qty * (entry - stop)` and `reward_$ = qty * (target - entry)`, plus `% of account`.
- Add fields to the embed.

**Tests:**
- Unit: embed contains projected risk/reward fields with correct math for long and short.

---

### WP-25 — Strategy Markdown Git Integration

**Goal:** Architecture §8.2 — strategy markdown changes are versioned in git.

**Deliverables:**
- `StrategyStore.save(...)` (or a new `commit_change` method) shells out to `git add` + `git commit` against the strategies dir, with a structured commit message including regime + rationale.
- Config flag to disable in tests / when not in a git repo.
- Wire `strategy_update` node to call it after merging proposed params.

**Tests:**
- Unit (using `tmp_path` git repo): saving a markdown change creates a commit with the expected message.
- Unit: disabled flag short-circuits cleanly.

---

### WP-26 — Credential Vault & In-Memory Signer

**Goal:** Architecture §6.5 — exchange credentials should not sit in plain env vars at request time.

**Deliverables:**
- `talim/security/vault.py` — loads credentials once at startup, holds them in memory, exposes a `sign(payload)` interface so callers never see the raw secret.
- `CcxtExchange` updated to consume the signer rather than reading env directly.
- Document key-rotation procedure in `.env.example`.

**Tests:**
- Unit: vault loads from env, raw secret is not accessible after init.
- Unit: signer produces a deterministic signature for a known payload.

---

### WP-27 — MCP Tool Wrappers

**Goal:** Architecture §11 — expose Talim capabilities as MCP tools so external agents can call them.

**Deliverables:**
- `talim/app/tools/` package with thin wrappers for: `get_positions`, `get_pnl`, `run_backtest`, `propose_strategy_update`, `query_episodic_memory`.
- MCP server entry point (stdio) that registers all tools.
- Each wrapper validates inputs and returns JSON-serialisable output.

**Tests:**
- Unit: each tool wrapper round-trips a representative call against mocks.
- Unit: MCP server lists the expected tool set on init.

---

### WP-28 — Historical Data Ingestion (Databento / Tardis)

**Goal:** Architecture §7.3 — ingest real historical bars for backtests and regime library building.

**Deliverables:**
- `scripts/ingest_databento.py` — CLI that downloads bars for a symbol+date-range and writes Parquet in the layout expected by `data_loader.load_ohlcv`.
- `scripts/ingest_tardis.py` — same shape, Tardis source.
- Idempotent (skip dates already on disk).
- Add cron entry to `scripts/cron.txt` for the nightly data update (currently only the heartbeat exists).

**Tests:**
- Unit: ingest scripts dry-run against a recorded HTTP fixture, verify Parquet shape on disk.

---

### WP-29 — Backtest Engine: vectorbt Path (optional)

**Goal:** Original WP-12 named vectorbt; we shipped an `on_bar` replay for live/backtest parity. Add a vectorbt-backed engine as an alternate, faster path for parameter sweeps.

**Deliverables:**
- `talim/backtest/vectorbt_engine.py` — translates strategy entry/exit conditions to vectorbt signals; runs sweeps in seconds.
- Parity test: a known strategy + dataset produces metrics within tolerance of the `on_bar` engine.
- Engine selection flag on `BacktestRequest`.

**Tests:**
- Unit: vectorbt path returns same total trades / net PnL as on_bar path on a synthetic dataset (within float tolerance).

---

### WP-30 — Integration Test Matrix Closeout

**Goal:** Tick the 8 unchecked rows in PROGRESS.md's "Integration Test Checklist".

**Deliverables:**
- For each pair (WP-02+04, 03+06, 08+09, 08+10, 11+15, 11+16, 09+12, 17+07), either:
  - Identify the existing test that already covers it and mark the row, or
  - Write a new focused integration test.
- Update PROGRESS.md.

**Tests:**
- The 8 integration tests (new or existing) all green.

---

### WP-31 — PoC Success Criteria Verification

**Goal:** Tick the 7 unchecked PoC criteria in PROGRESS.md.

**Deliverables:**
- Run `docker compose up` against a real Docker daemon and capture the output (criterion 1 — currently only file-shape smoke tests exist).
- For criteria 2–7, link each to a passing test or a recorded manual run.
- Update PROGRESS.md with verification dates.

**Tests:**
- Healthcheck script passes against the live stack.
- Manual run log committed under `docs/poc-verification.md`.

---

## Phase 8: Production Readiness

These work packages cover everything required to take Talim from a PoC with a green test suite to a deployment that can actually place real orders against a live exchange. Grouped by concern; most are parallelisable after WP-32.

### WP-32 — Live Exchange Wiring & Testnet Soak

**Goal:** Replace MockExchange with a real ccxt-backed exchange against a testnet/paper account and run the full graph against it for a sustained period.

**Deliverables:**
- Wire `CcxtExchange.from_vault(...)` into the compose startup path (currently only `MockExchange` is configured).
- Config flag `TALIM_EXCHANGE_MODE=mock|testnet|live` gating which exchange the `configure_execute` call receives.
- Support for at least one testnet (Binance testnet or Alpaca paper).
- A runbook in `docs/exchange-setup.md` for provisioning API keys and dropping them in the vault.

**Tests:**
- Integration test against a recorded ccxt testnet response (httpx mock) covering order placement, fill polling, position query.
- Manual soak: 2+ weeks on testnet, daily episodic memory review, no drift.

---

### WP-33 — Live Price Feed Integration

**Goal:** Stream real ticks into the scanner instead of replaying Parquet.

**Deliverables:**
- Flesh out `talim/connectors/pricefeed/binance.py` ccxt.pro websocket subscription.
- Add one futures feed (Databento live or IBKR) for ES — the PoC strategies target ES futures which crypto feeds can't provide.
- Reconnect / gap-fill logic: on disconnect, backfill missing bars from the REST API before resuming.
- `configure_scanner` accepts a live feed; compose stack has a `TALIM_PRICEFEED=mock|binance|databento` env.

**Tests:**
- Unit: reconnect handler backfills correctly across a simulated disconnect.
- Integration: scanner consumes live feed for N bars and emits at least one regime fingerprint.

---

### WP-34 — Position Monitor & Stop/Target Enforcement

**Goal:** The PoC exits positions only inside the backtest engine. In production, something must watch live ticks against open position stops/targets and close them.

**Deliverables:**
- New `talim/app/nodes/position_monitor.py` node that reads open positions and the latest tick, fires an exit signal when stop/target is touched.
- Alternative (or complementary): place bracket orders at entry time via `exchange.place_bracket_order(...)` and extend `BaseExchange` accordingly.
- Scheduled through the 5-min scanner tick (or a dedicated 30s heartbeat).

**Tests:**
- Unit: monitor fires exit signal when price crosses stop; doesn't fire when within bounds.
- Integration: e2e entry → tick crosses target → exit node records fill + closes position.

---

### WP-35 — Order Reconciliation Loop

**Goal:** If the process crashes between "exchange filled" and "episodic record persisted", state diverges from reality. A reconciler must detect and repair this.

**Deliverables:**
- New `talim/app/nodes/reconcile.py` node that pulls live positions from exchange, diffs against `EpisodicMemory` + `open_pnl`, and emits repair events.
- Runs every N minutes via cron or a dedicated scheduler entry.
- Divergences logged and surfaced via Discord notify.

**Tests:**
- Unit: synthetic divergence (exchange has a position memory doesn't) produces a repair event.
- Unit: matching state produces no events.

---

### WP-36 — P&L Source of Truth

**Goal:** `open_pnl` / `daily_pnl` are currently updated opportunistically in `execute`. Production needs a periodic refresh pulled from exchange balances.

**Deliverables:**
- `talim/risk/pnl_tracker.py` with `refresh_from_exchange(exchange) -> PnLSnapshot`.
- Wired into a scheduled node or the reconciler from WP-35.
- `daily_pnl` resets on session boundary (configurable timezone).

**Tests:**
- Unit: refresh computes correct open/daily PnL from mock exchange balance + position history.
- Unit: session rollover resets daily_pnl.

---

### WP-37 — Discord Bot Runner Service

**Goal:** `TalimDiscordBot` exists but nothing actually runs it. Add it as a first-class compose service wired to `ReactionHandler → resume_graph`.

**Deliverables:**
- New compose service `discord-bot` that imports `talim.connectors.discord` and runs the bot event loop.
- Environment: `DISCORD_BOT_TOKEN`, `DISCORD_GUILD_ID`, `DISCORD_SIGNAL_CHANNEL_ID`.
- Bot posts embeds generated by `hitl_interrupt` and calls back into `/talim/resume` on reaction.
- Shared secret auth against the bridge.

**Tests:**
- Integration: fake Discord gateway delivers a reaction event; bot forwards it to the bridge; graph resumes.
- Manual: real Discord server, end-to-end HITL round trip.

---

### WP-38 — Scheduler / Cron Service

**Goal:** `scripts/cron.txt` documents what needs to run but nothing installs it. Ship a scheduler alongside the stack.

**Deliverables:**
- Add a `supercronic` or `ofelia` container to `docker-compose.yml` reading `scripts/cron.txt`.
- 5-min scanner heartbeat → POST `/talim/trigger` (new endpoint) → `cron_trigger` node.
- Nightly ingest (Databento + Tardis).
- Healthcheck verifies last-tick freshness.

**Tests:**
- Unit: new `/talim/trigger` endpoint enqueues a scan.
- Integration: compose up with scheduler container, verify scan ran within 6 min.

---

### WP-39 — Risk Rules Config & Kill Switch

**Goal:** Risk rules have defaults hardcoded. Production needs per-account JSON config + an emergency halt.

**Deliverables:**
- `config/risk.json` template with max position size, daily drawdown halt, per-instrument exposure, correlation limits.
- Loader + validator in `talim/risk/config.py`; `configure_risk_rules` accepts a path.
- New `/talim/halt` endpoint (shared-secret authed) that sets a `halted` flag in `TalimState` blocking all new signals until cleared via `/talim/resume-trading`.
- Discord `!halt` / `!resume` commands wired to the same endpoints.

**Tests:**
- Unit: halted state blocks signals at the router.
- Unit: config validator rejects missing/invalid fields.
- Integration: halt → signal fires → blocked → resume → next signal executes.

---

### WP-40 — Secrets Management

**Goal:** `.env` files are fine for PoC, not for anything touching real money. Move exchange keys + API secrets to a proper secrets manager.

**Deliverables:**
- Pluggable backend behind `Vault.load_from_env()`: env (current), AWS Secrets Manager, HashiCorp Vault, sops-encrypted files.
- `TALIM_SECRETS_BACKEND` env selects the backend.
- Docs in `docs/secrets.md` covering rotation and emergency revocation.

**Tests:**
- Unit: each backend loads known credentials; missing credentials raise the same error type.
- Unit: `sign(...)` output is backend-agnostic for identical inputs.

---

### WP-41 — Observability (Metrics, Logs, Alerts)

**Goal:** Nothing is shipped off the box today. At minimum: structured logs, Prometheus metrics, and alerting on "scanner silent".

**Deliverables:**
- Structured JSON logger config in `talim/logging.py`; every node logs `node`, `thread_id`, `latency_ms`, `outcome`.
- `/metrics` Prometheus endpoint on the bridge exposing: signals emitted, risk blocks, HITL pending, orders placed, reconciler divergences.
- Grafana dashboard JSON under `ops/grafana/talim.json`.
- Alertmanager rule: scanner hasn't emitted a tick in 10 min → page.
- Optional: ship logs to Loki or Datadog via compose-level log driver.

**Tests:**
- Unit: `/metrics` endpoint returns well-formed Prometheus text.
- Unit: log output is valid JSON per record.

---

### WP-42 — TLS & Public Reachability

**Goal:** Bridge is HTTP-only today. To receive external assistant / Discord webhooks from outside, it needs TLS.

**Deliverables:**
- Automate cert provisioning: either a Caddy sidecar (auto-Let's Encrypt) replacing nginx, or a nginx + certbot companion.
- Alternative path documented: Cloudflare Tunnel or Tailscale Funnel for zero-inbound deployments.
- Re-enable the TLS block in `nginx/nginx.conf` conditionally on cert presence.

**Tests:**
- Integration: stack boots with self-signed cert; curl over HTTPS succeeds.
- Manual: Let's Encrypt cert issuance against a staging domain.

---

### WP-43 — Backup & Disaster Recovery

**Goal:** Losing `working_memory.db` mid-HITL means losing in-flight interrupts; losing `episodic.db` means losing the decision journal.

**Deliverables:**
- `scripts/backup.sh` running `sqlite3 .backup` on each DB to a timestamped file + optional S3 upload.
- Cron entry for hourly `working_memory` snapshots and daily `episodic`/`pattern` snapshots.
- Restore runbook in `docs/disaster-recovery.md`.
- Redis AOF enabled in the compose config for durability.

**Tests:**
- Unit: backup script produces a restorable file.
- Manual: restore from backup into a fresh stack, verify graph resumes in-flight interrupts.

---

### WP-44 — Historical Data Backfill & Pattern Library Build

**Goal:** The ingest scripts exist but nothing's been backfilled; `PatternMemory` is empty, so the session matcher has nothing to compare against.

**Deliverables:**
- Runbook + one-shot job: ingest 2+ years of ES minute bars via Databento.
- Run the regime library builder against the backfilled data to populate `PatternMemory`.
- Commit the resulting fingerprint blob (or S3 pointer) so new deployments start with a warm library.
- Refresh job: weekly re-build of the pattern library.

**Tests:**
- Integration: empty PatternMemory → run builder against test Parquet → matcher returns candidates above the 30-minimum floor.

---

### WP-45 — Strategy Expansion & Tuning

**Goal:** Only two toy strategies ship. Before real capital, the strategy set needs to be broader and tuned on real data.

**Deliverables:**
- At least 2 additional strategies covering different regimes (e.g. volatility breakout, opening-range).
- Tuning workflow: for each strategy, run a backtest sweep over 2 years of ingested data and commit the chosen parameters.
- Strategy markdown docs updated with backtest results and regime applicability.

**Tests:**
- Each new strategy has a unit test for `on_bar` behaviour in its target regime.
- Backtest sweep reproducible via a pytest fixture.

---

### WP-46 — External Assistant Deployment

**Goal:** The bundled assistant stub is gone. Either deploy a real external assistant (for example OpenClaw) or document direct bridge usage.

**Deliverables:**
- Decision doc: deploy OpenClaw, replace with another assistant client, or use the bridge directly.
- If deploying: document the external assistant deployment and wire it to `/talim/converse` with the shared secret.
- If using direct bridge mode: document the caller contract and keep the compose stack assistant-free.

**Tests:**
- Integration: external assistant → bridge conversation round-trip (or: assistant-free bridge path documented cleanly with no dangling references).

---

### WP-47 — Portable Local Deployment & VPS Migration Layout

**Goal:** Make the local laptop setup the default development environment while keeping the stack easy to move to a VPS later without re-architecting storage, networking, or restore procedures.

**Deliverables:**
- Replace migration-hostile named volumes with explicit bind-mounted project directories where practical (for example `./state`, `./redis`, `./backups`, `./data`) so state can be copied directly to a new host.
- Document a local-first deployment layout covering OpenClaw + Talim + Redis + Grafana with private-only access and no public ingress requirement.
- Add a migration runbook: provision new host, install Docker/Tailscale/OpenClaw, copy state/config, restore Talim databases, start compose, verify health, switch client endpoints.
- Keep environment/config host-agnostic: no hardcoded laptop paths, no host-specific network assumptions, no mandatory public DNS requirement.

**Tests:**
- Manual: bring the stack up from a clean clone on a second machine using only the documented bind-mounted state/config layout.
- Manual: restore Talim state from copied directories/backups and confirm healthcheck + bridge endpoints succeed.

---

## Phase 10: Broker-Agnostic CFD Core (IG-First)

> These work packages adapt Talim from the current ES futures / Binance-oriented PoC into a broker-agnostic CFD trading architecture. `IG AU` is the first implementation target because its API surface is documented and demo-accessible, but the design should make a second venue such as `FOREX.com AU` an adapter exercise rather than a rewrite.

### WP-48 — CFD Venue Contract and Instrument Registry

**Goal:** Define the canonical CFD model Talim will use internally so broker-specific quirks do not leak into the strategy and risk layers.

**Deliverables:**
- Canonical instrument id scheme for CFD markets (for example `AU200.cash`, `AU200.fwd`, `EURUSD.cfd`).
- `CfdInstrumentSpec` / venue metadata model covering at least:
  - canonical instrument id
  - broker symbol / epic / market id
  - display name
  - asset class
  - quote currency
  - tick size and price precision
  - min size / size step
  - point value
  - margin rate / tiering support
  - financing model
  - session hours / calendar
  - position model hints (netted vs hedged)
- Venue capability model for order semantics such as:
  - market vs marketable-limit support
  - stop / limit / guaranteed stop support
  - partial fills
  - working orders
  - demo vs live environment split
- Registry/config format so a strategy can select a canonical instrument without hardcoding broker symbols.

**Tests:**
- Unit: instrument registry resolves canonical ids into venue-specific metadata.
- Unit: capability flags validate unsupported order combinations before broker calls.
- Unit: session/calendar metadata loads cleanly for AU index CFD instruments.

---

### WP-49 — IG AU Feasibility and Market Discovery

**Goal:** Lock down the first concrete venue by confirming the exact IG account, API, and product details required for AU index CFDs.

**Deliverables:**
- Decision doc covering:
  - IG account type and demo/live prerequisites
  - API key/session bootstrap flow
  - exact `Australia 200` tradable markets to support first (`cash` vs `futures` CFD)
  - order types and dealing-rule constraints returned by IG
  - rate limits, streaming limits, and relevant cost assumptions
- Market discovery script for pulling IG dealing rules and contract details for target instruments.
- IG-specific mapping entries for the initial CFD universe in the canonical registry.
- Clear go/no-go criteria for proceeding with IG as the first live-capable CFD venue.

**Tests:**
- Manual: authenticated demo API session succeeds and returns account + market metadata.
- Manual: target `Australia 200` market discovery returns usable dealing rules and identifiers.

---

### WP-50 — IG Exchange Adapter

**Goal:** Implement the first real CFD broker adapter against the broker-neutral venue contract.

**Deliverables:**
- `talim/connectors/exchange/ig_exchange.py` implementing `BaseExchange`.
- IG session/auth handling and token refresh lifecycle.
- Implementations for:
  - `place_order(...)`
  - `cancel_order(...)`
  - `get_positions()`
  - `get_account_balance()`
  - `get_order(...)`
- Normalisation layer from IG orders/positions/confirms into Talim models.
- Factory wiring so IG can be selected cleanly by configuration.

**Tests:**
- Unit: request/response mapping for IG orders, positions, balances, and order status.
- Integration: mocked IG round-trip for login → place order → fetch positions → cancel/close order.
- Integration: connector normalises IG payloads into Talim `Order` / `Position` models.

---

### WP-51 — CFD Market Data Pipeline (IG-First)

**Goal:** Replace the Binance-only live feed assumption with a CFD-capable data layer that can support both streaming and historical replay.

**Deliverables:**
- `talim/connectors/pricefeed/ig.py` or equivalent IG-specific feed implementation.
- Lightstreamer client wrapper plus REST fallback/backfill path.
- Local bar builder that aggregates live ticks/prices into Talim `OHLCVBar` intervals such as `5m`.
- Historical ingestion/cache pipeline for target CFD instruments into Parquet compatible with the backtest loader.
- Config path to select the IG CFD feed and canonical instrument ids instead of Binance symbols.

**Tests:**
- Unit: IG price payloads normalise into valid market snapshots and `OHLCVBar` objects.
- Unit: reconnect/backfill logic preserves bar continuity across a simulated disconnect.
- Integration: live/demo IG feed produces bars for the target AU index CFD.
- Integration: ingested Parquet files load cleanly through `talim/backtest/data_loader.py`.

---

### WP-52 — CFD Risk, P&L, and Session Model

**Goal:** Make Talim's execution and risk logic CFD-aware rather than relying on futures/spot assumptions.

**Deliverables:**
- Extend risk config and checks to consume canonical CFD instrument specs instead of futures-centric hardcoded groups.
- Margin-aware exposure model including tiered margin compatibility where available.
- Financing / overnight funding treatment for cash CFDs and spread-based handling for forward/futures-style CFDs.
- Session/calendar-aware scanner and execution rules for AU index CFD trading hours.
- Position/reconciliation updates that can respect broker-specific netting semantics while preserving canonical Talim state.

**Tests:**
- Unit: exposure and margin calculations are correct for the canonical AU index CFD spec.
- Unit: risk rules block positions that exceed available margin or configured CFD exposure limits.
- Unit: P&L calculation handles point value, financing, and session rollover inputs correctly.
- Integration: mocked broker positions reconcile cleanly into Talim state using canonical instrument ids.

**Status:** Completed on 2026-04-13 with CFD-aware margin utilisation, session gating, financing-aware snapshots, AU200 point-value metadata, and netted reconciliation behaviour.

---

### WP-53 — AU200 Strategy Package and IG Demo Soak

**Goal:** Validate the first end-to-end CFD path on `IG AU` with a strategy and dataset that match the target market.

**Deliverables:**
- At least one AU index CFD strategy package (for example `momentum-AU200`).
- Strategy markdown documenting market rationale, session assumptions, and tuned params.
- 1-2 years of historical AU index CFD bars in Parquet for backtests.
- Demo runbook covering login, feed startup, scanner cadence, HITL approval, order placement, and rollback.
- 2+ week IG demo soak checklist and post-soak go/no-go review doc.

**Tests:**
- Unit: strategy `on_bar` behaviour on synthetic AU index scenarios.
- Integration: backtest runs successfully against AU index Parquet data.
- Manual: end-to-end demo trade lifecycle on the target AU index CFD contract.
- Manual: recovery drill during an in-flight pending signal and during an open position.

**Status:** Completed on 2026-04-13 with `momentum-AU200`, timeframe-aware AU200 backtests, IG dataset build/runbook tooling, a soak checklist/review template, and the first recorded AU200 baseline run on IG demo historical data.

---

## Phase 11: Prediction Market Venue Enablement

### WP-54 — Polymarket Feasibility, Compliance, and Product Fit Gate

**Goal:** Establish whether a Polymarket integration is legally and operationally usable before spending time on connector work.

**Deliverables:**
- Short feasibility note covering:
  - jurisdiction/geoblock constraints for the intended operator location
  - whether the target use case is paper-only, research-only, or intended for live execution
  - whether Talim's current bar-based strategy/risk architecture is a good fit for event markets
- Decision memo with one of:
  - proceed with research-only integration
  - proceed with paper/simulated connector only
  - stop due to compliance/product mismatch
- Documented assumptions for:
  - wallet custody
  - USDC funding flow
  - event universe to trade
  - acceptable market liquidity thresholds

**Tests:**
- N/A: documentation and feasibility gate only.

---

### WP-55 — Polymarket Wallet Auth and Exchange Connector

**Goal:** Add the authenticated execution path required for signed CLOB trading rather than reusing the existing ccxt broker model.

**Deliverables:**
- `talim/connectors/exchange/polymarket.py` or equivalent connector module.
- Wallet/auth support for:
  - Polygon wallet key loading
  - L1 auth/signing bootstrap
  - L2 API credential usage
- Connector methods for:
  - place order
  - cancel order
  - get open orders
  - get fills/trades
  - get positions/balances
- Config surface for paper/mock mode vs authenticated live-capable mode.
- Clear separation between connector state and secret material.

**Tests:**
- Unit: signed request construction uses the expected auth headers and payload shape.
- Unit: order placement/cancel/status parsing handles success and common failure responses.
- Integration: mocked authenticated connector can create/cancel orders and refresh balances/positions.

---

### WP-56 — Polymarket Market Data and WebSocket Feed

**Goal:** Build a venue-specific data layer for event markets, which are orderbook/probability-driven rather than conventional OHLCV-only bars.

**Deliverables:**
- Market discovery client for event/market metadata.
- Orderbook/trade feed client using Polymarket's websocket/public APIs.
- Normalised internal market snapshot model capturing at least:
  - market id / slug
  - best bid / ask
  - midpoint / implied probability
  - spread
  - depth / recent trades
  - time to resolution
- Optional derived bar/snapshot series for research/backtesting where needed.
- Historical capture job for market snapshots/trades into a replayable local format.

**Tests:**
- Unit: API/websocket payloads normalise into stable market snapshot objects.
- Unit: reconnect/resubscribe logic preserves stream continuity after a disconnect.
- Integration: selected market metadata and live orderbook snapshots load for a mocked/recorded session.

---

### WP-57 — Prediction Market Position, Risk, and Settlement Model

**Goal:** Extend Talim's futures/CFD-biased risk model to handle binary outcome markets, capped payout profiles, and event resolution.

**Deliverables:**
- Instrument/market spec registry for prediction markets including:
  - event id
  - market id
  - outcome token
  - tick size
  - resolution timestamp
  - category / topic
  - liquidity metrics
- Position model updates for:
  - YES/NO style outcome exposure
  - max loss / max payout
  - collateral consumption
  - realized vs unresolved P&L
- Risk rules for:
  - event concentration
  - correlated outcome exposure
  - liquidity/spread thresholds
  - stale market / near-resolution trading restrictions
- Settlement/reconciliation flow for resolved markets and redeemed collateral.

**Tests:**
- Unit: max loss, payout, and marked-to-mid P&L calculations are correct for binary outcome positions.
- Unit: risk rules block oversized or illiquid prediction-market positions.
- Integration: mocked resolved market positions reconcile into settled Talim state cleanly.

---

### WP-58 — Event-Driven Strategy and Backtest Framework

**Goal:** Add a strategy and replay model that suits prediction markets instead of assuming ATR/regime logic from continuous financial bars.

**Deliverables:**
- Event-market strategy interface or extensions for signals driven by:
  - price/probability dislocations
  - spread/depth changes
  - event state changes
  - optional external catalysts/news inputs
- At least one baseline strategy package for paper evaluation.
- Historical replay format and backtest harness for market snapshots/trades plus final resolution outcomes.
- Evaluation metrics suited to prediction markets:
  - expected value
  - realized payout
  - time-to-resolution exposure
  - liquidity/slippage sensitivity
- Documentation on where the current ES/AU200 strategy assumptions do not transfer.

**Tests:**
- Unit: baseline strategy emits deterministic signals for synthetic event-market scenarios.
- Integration: replay harness can simulate entry, exit, and resolution across historical snapshot data.
- Integration: summary metrics reflect capped payout profiles and unresolved-position handling.

---

## Phase 12: Second CFD Venue Portability

### WP-59 — FOREX.com AU Feasibility and Market Mapping

**Goal:** Validate whether the broker-neutral CFD core built for IG can be applied to `FOREX.com AU` without structural changes.

**Deliverables:**
- Decision doc covering:
  - account/API entitlement path
  - exact target AU index CFD identifiers
  - order-type and position-model differences vs IG
  - rate-limit, auth, and demo/live environment differences
- Mapping document from canonical CFD instrument ids to `FOREX.com` symbols.
- Gap analysis against the Phase 10 venue contract:
  - supported as-is
  - requires optional capability flags
  - requires structural changes

**Tests:**
- Manual: authenticated API session succeeds and returns account metadata.
- Manual: tradable instrument lookup returns the target AU index CFD contract.

---

### WP-60 — FOREX.com Exchange and Price Feed Adapters

**Goal:** Implement `FOREX.com` on top of the broker-neutral CFD architecture, not as a parallel one-off stack.

**Deliverables:**
- `talim/connectors/exchange/forexcom_exchange.py` implementing the Phase 10 CFD venue contract.
- `talim/connectors/pricefeed/forexcom.py` or equivalent feed adapter using canonical instrument ids.
- Response normalisers for orders, balances, positions, and live/demo market data.
- Factory/config wiring to select IG or `FOREX.com` cleanly without changing strategy/risk code.

**Tests:**
- Unit: `FOREX.com` payload mapping for orders, balances, positions, and price data.
- Integration: mocked API round-trip for login → place order → fetch positions → cancel/close order.
- Integration: feed adapter emits canonical bars/snapshots compatible with the existing scanner.

---

### WP-61 — Multi-Broker CFD Conformance and Demo Regression

**Goal:** Prove that the canonical CFD model is genuinely portable across brokers rather than only looking generic on paper.

**Deliverables:**
- Conformance test suite that runs the same broker-agnostic assertions against IG and `FOREX.com` adapters.
- Regression checklist covering:
  - canonical instrument resolution
  - order placement semantics
  - stop/limit handling
  - position reconciliation
  - margin/P&L consistency
  - bar continuity and session handling
- Demo soak runbooks for both brokers using the same Talim strategy/risk flow.

**Tests:**
- Integration: shared broker-agnostic adapter tests pass for both IG and `FOREX.com` implementations.
- Manual: end-to-end demo trade lifecycle succeeds on both brokers for the target AU index CFD path.
