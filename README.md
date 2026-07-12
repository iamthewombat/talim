# Talim

Agentic trading assistant powered by LangGraph. Talim monitors markets, detects regime changes, generates trade signals through pluggable strategies, routes them through risk checks and human-in-the-loop approval, executes against an exchange, and answers questions through a conversational bridge — all orchestrated as a stateful, checkpointed graph with persistent memory.

**Status:** 50+ work packages complete · 686 tests green · all 7 PoC success criteria verified ([docs/poc-verification.md](docs/poc-verification.md)). Work-package status lives in [PROGRESS.md](PROGRESS.md).

## Architecture

### End-to-end data flow

```
        ┌───────────────────────────┐   ┌───────────────────────────┐
        │      EXTERNAL INPUTS      │   │      EXTERNAL OUTPUTS     │
        │                           │   │                           │
        │  ▸ Databento / Tardis     │   │  ▸ Exchange (ccxt: orders)│
        │  ▸ Binance / IBKR feed    │   │  ▸ Discord (embeds + rx)  │
        │  ▸ Discord reactions      │   │  ▸ Bridge client replies  │
        │  ▸ Bridge client messages │   │  ▸ Episodic journal       │
        │  ▸ Claude / Ollama APIs   │   │                           │
        └─────────────┬─────────────┘   └─────────────▲─────────────┘
                      │                               │
                      ▼                               │
┌─────────────────────────────────────────────────────┴─────────────────────┐
│                           NGINX (reverse proxy + TLS)                      │
│                       :80/:443  →  /talim/*  →  bridge:8000                │
└──────────────────────────────┬─────────────────────────────────────────────┘
                               │
                               ▼
┌────────────────────────────────────────────────────────────────────────────┐
│                          TALIM CONTAINER (FastAPI + LangGraph)             │
│                                                                            │
│   ┌──────────────────────────┐        ┌─────────────────────────────┐      │
│   │   FastAPI Bridge API     │        │   Scheduler / Cron Hook     │      │
│   │   POST /talim/converse   │        │   every 5m → cron_trigger   │      │
│   │   POST /talim/resume     │        │   nightly → ingest scripts  │      │
│   │   POST /talim/trigger    │        └──────────────┬──────────────┘      │
│   │   POST /talim/sync       │                       │                     │
│   │   X-Talim-Secret auth    │                       │                     │
│   └────────────┬─────────────┘                       │                     │
│                │                                     │                     │
│                ▼                                     ▼                     │
│   ┌────────────────────────────────────────────────────────────────────┐   │
│   │                      LANGGRAPH BRAIN (StateGraph)                  │   │
│   │                                                                    │   │
│   │    cron_trigger ──▶ signal_scanner ─▶ position_monitor ──┐         │   │
│   │                                                          ▼         │   │
│   │    bridge_message ─▶ converse ─────▶ router ─┬─▶ risk_check        │   │
│   │                                          │      │        │         │   │
│   │                                          │  (entries) (prot.exits) │   │
│   │                                          │      ▼        │         │   │
│   │                                          │ hitl_interrupt│         │   │
│   │                                          │   [PAUSE]     │         │   │
│   │                                          │      ▼        ▼         │   │
│   │                                          │     execute ─▶ END      │   │
│   │                                          │                         │   │
│   │                                          ├─▶ strategy_update ─▶ notify │
│   │                                          ├─▶ backtest_run ───▶ notify  │
│   │                                          ├─▶ notify ──────────▶ END    │
│   │                                          └─▶ END                       │
│   │                                                                    │   │
│   │    State: TalimState (26 fields)                                   │   │
│   │    Checkpointer: SqliteSaver (survives restarts, resumes HITL)     │   │
│   └─────────────┬────────────────────┬─────────────────┬───────────────┘   │
│                 │                    │                 │                   │
│                 ▼                    ▼                 ▼                   │
│   ┌─────────────────────┐ ┌───────────────────┐ ┌───────────────────┐      │
│   │  Regime Engine      │ │    Strategies     │ │    Risk Rules     │      │
│   │                     │ │                   │ │                   │      │
│   │  ▸ 9-feat fingerprnt│ │  ▸ BaseStrategy   │ │  ▸ qty / exposure │      │
│   │  ▸ k-means classify │ │  ▸ on_bar(bar)    │ │  ▸ daily drawdown │      │
│   │  ▸ Session matcher  │ │  ▸ momentum-US500 │ │  ▸ correlation    │      │
│   │  ▸ Macro calendar   │ │  ▸ mean-rev-US500 │ │  ▸ kill switch    │      │
│   │    (FOMC/CPI excl)  │ │  ▸ markdown store │ │                   │      │
│   └─────────────────────┘ └───────────────────┘ └───────────────────┘      │
│                                                                            │
│   ┌─────────────────────┐ ┌───────────────────┐ ┌───────────────────┐      │
│   │   LLM Layer         │ │  Backtest Engine  │ │   MCP Tools       │      │
│   │                     │ │                   │ │                   │      │
│   │  ▸ Claude (reason)  │ │  ▸ on_bar replay  │ │  ▸ get_positions  │      │
│   │  ▸ Ollama (classify)│ │  ▸ vectorbt opt.  │ │  ▸ get_pnl        │      │
│   │  ▸ Prompt templates │ │  ▸ metrics/sweeps │ │  ▸ run_backtest   │      │
│   │  ▸ MockLLMClient    │ │  ▸ Parquet loader │ │  ▸ query_episodic │      │
│   └─────────────────────┘ └───────────────────┘ └───────────────────┘      │
│                                                                            │
│   ┌─────────────────────┐ ┌───────────────────┐ ┌───────────────────┐      │
│   │   Security          │ │   Connectors      │ │   Event Bus       │      │
│   │                     │ │                   │ │                   │      │
│   │  ▸ Vault (HMAC)     │ │  ▸ PriceFeed      │ │  ▸ Redis Streams  │      │
│   │  ▸ sign(ex, payload)│ │    (mock/binance) │ │  ▸ BarEvent       │      │
│   │  ▸ No secret getter │ │  ▸ Exchange       │ │  ▸ SignalEvent    │      │
│   │  ▸ Shared-secret    │ │    (mock/ccxt)    │ │  ▸ RegimeChange   │      │
│   │    bridge auth      │ │  ▸ Discord bot    │ │  ▸ TradeEvent     │      │
│   └─────────────────────┘ └───────────────────┘ └───────────────────┘      │
└────────┬───────────────────────────┬─────────────────────────┬─────────────┘
         │                           │                         │
         ▼                           ▼                         ▼
┌─────────────────┐         ┌─────────────────┐       ┌────────────────────┐
│ MEMORY (SQLite) │         │ REDIS CONTAINER │       │ EXTERNAL ASSISTANT │
│                 │         │                 │       │    CLIENT(S)       │
│ ▸ episodic.db   │         │ ▸ Streams       │       │                    │
│   (decisions)   │         │ ▸ Consumer grps │       │  ▸ OpenClaw        │
│ ▸ pattern.db    │         │ ▸ AOF durable   │       │  ▸ Direct bridge   │
│   (fingerprints)│         │                 │       │    callers         │
│ ▸ working.db    │         └─────────────────┘       │  ▸ Shared secret   │
│   (SqliteSaver  │                                   │                    │
│    checkpoints) │                                   └────────────────────┘
└─────────────────┘
```

### Deployment topology (Docker Compose)

```
                         ┌───────────────────────┐
                         │   host :8080 / :8443  │
                         └───────────┬───────────┘
                                     │
                      ┌──────────────┴──────────────┐
                      │      nginx (reverse proxy)  │
                      │   talim-nginx · nginx:alpine│
                      └──────┬───────────────┬──────┘
                             │               │
                    /talim/* │
                             ▼
                  ┌──────────────────┐
                  │      talim       │
                  │   talim-app      │
                  │   :8000 (uvicorn)│
                  │   healthcheck ✓  │
                  └──────┬───────────┘
                         │
              ┌──────────┼──────────┐
              ▼          ▼          ▼
        ┌─────────┐ ┌─────────┐ ┌────────────┐
        │  redis  │ │ sqlite  │ │  host vols │
        │ :6379   │ │ volume  │ │ data/ logs/│
        │ healthy │ │ (dbs)   │ │            │
        └─────────┘ └─────────┘ └────────────┘
```

### HITL sequence (signal → alert → resume)

The PoC Discord reaction path below still works, but the production flow is:
an OpenClaw watcher polls `/talim/operator/pending` and posts alerts to
Discord; the operator approves from the dashboard signal page or via
OpenClaw commands; and every approval is re-validated at decision time
(fresh bars, strategy-specific validation, re-run risk checks) before
execution — stale or invalidated signals are blocked, not executed
(WP-75–WP-80). Protective exit signals from `position_monitor` skip HITL
entirely and go straight to execution after risk checks.

```
 scanner     router    risk_check  hitl_interrupt   Discord        human      execute   exchange
    │           │           │            │             │             │           │          │
    │─ Signal ─▶│           │            │             │             │           │          │
    │           │─ check ──▶│            │             │             │           │          │
    │           │           │─ approve ─▶│             │             │           │          │
    │           │           │            │── embed ───▶│             │           │          │
    │           │           │            │  (checkpoint saved)       │           │          │
    │           │           │            │    [GRAPH PAUSED]         │           │          │
    │           │           │            │             │── render ──▶│           │          │
    │           │           │            │             │             │           │          │
    │           │           │            │             │◀── ✅ react─│           │          │
    │           │           │            │◀──── POST /talim/resume ──│           │          │
    │           │           │            │                                       │          │
    │           │           │            │─── resume_graph(approved=True) ──────▶│          │
    │           │           │            │                                       │─ order ─▶│
    │           │           │            │                                       │◀── fill ─│
    │           │           │            │                                       │          │
    │           │           │            │◀──── episodic.record_decision ────────│          │
    │           │           │            │                                       │          │
    │           │           │            │─── notify (fill confirmation) ───────▶│          │
```

### Key properties

- **Live/backtest parity** — the same `on_bar` code path drives both real-time scanning and historical backtests, so signals are reproducible by construction.
- **Stateful pause/resume** — HITL interrupts persist via `SqliteSaver`; a process restart mid-approval doesn't lose the pending signal.
- **Dependency injection throughout** — `configure_scanner`, `configure_risk_rules`, `configure_llm_client`, `configure_execute` keep every node hermetic and test-friendly.
- **Graceful degradation** — missing vectorbt falls back to on_bar; missing Claude falls back to Ollama or deterministic templates; missing Ollama falls back to Claude or rules.
- **No secret leakage** — exchange API secrets load once into `Vault._secrets` and are only observable through `sign(exchange, payload)`; there is no getter.

## What's Built

### Core Data Models (`talim/models/`)
- **OHLCVBar**, **Position**, **Signal**, **BacktestRequest/Result**
- **TalimState** — TypedDict schema for the LangGraph state (26 fields, incl. `last_tick`, `instrument`, `open_pnl`, `daily_pnl`, `last_action`, `discord_thread_id`, `messages`)
- All models support `to_dict()` / `from_dict()` for checkpointing

### Regime Engine (`talim/regime/`)
- 9-feature fingerprint (ADX, ATR ratio, trend slope, volatility, volume ratio, momentum, price position, range expansion, session return)
- Macro-event calendar (`talim/regime/calendar.py` + `macro_events.json`) excludes FOMC/CPI days from session matching
- Session matcher enforces a 30-candidate minimum floor and filters by session type
- k-means classification → `momentum`, `mean_reversion`, `high_vol`, `ranging`
- Session matcher (Euclidean distance over historical fingerprints)
- Library builder for the pattern memory store

### Strategy Framework (`talim/strategy/`)
- `BaseStrategy.on_bar(bar) -> Signal | None`
- Dynamic loader (`strategies/{name}/strategy.py`)
- Markdown store for strategy documents (consumed by LLM nodes)

| Strategy | Logic | Stop | Target |
|----------|-------|------|--------|
| **momentum-US500** | EMA(8) / EMA(21) crossover | 1.5× ATR | 3.0× ATR |
| **mean-reversion-US500** | Bollinger Band (20, 2σ) reversion | 2.0× ATR | 1.5× ATR |
| **momentum-AU200** | EMA(13) / EMA(34) crossover with ATR gap filter | 1.6× ATR | 2.8× ATR |

### Memory (`talim/memory/`)
- **EpisodicMemory** — decision journal (signals, approvals, fills, outcomes)
- **PatternMemory** — packed-blob fingerprint library
- **WorkingMemory** — `SqliteSaver` checkpointer for graph state (survives restarts)

### Event Bus (`talim/bus/`)
- Redis Streams pub/sub with consumer groups
- `BarEvent`, `RegimeChangeEvent`, `SignalEvent`, `TradeEvent`

### Connectors (`talim/connectors/`)
- **Price feeds:** `BasePriceFeed`, `MockPriceFeed` (DataFrame/Parquet/CSV replay), Binance ccxt.pro scaffold, IG CFD REST feed, FOREX.com REST feed, normalisers, price-feed factory
- **Exchanges:** `BaseExchange`, `MockExchange` (in-memory fills + position tracking with flip/partial-close), `CcxtExchange` for Binance/Bybit-style venues, first-party IG and FOREX.com CFD adapters, env credential loader
- **Discord:** rich-embed formatter (signals/backtests/regimes/log), `ReactionHandler` mapping ✅/❌ to HITL resume, `TalimDiscordBot` discord.py shell

### Current Venue Status

- The current CFD path targets index CFDs (`US500.cash`, `AU200.cash`) via `ig` or `forexcom`, using the broker-neutral CFD registry and adapter layer. The live runtime currently scans US500 through the FOREX.com feed.
- Binance credentials are not required for the AU200 CFD path. `BINANCE_API_KEY` / `BINANCE_API_SECRET` are used only when `TALIM_EXCHANGE_MODE=testnet|live` and `TALIM_EXCHANGE_NAME=binance`.
- `TALIM_PRICEFEED=binance` selects the public Binance ccxt.pro feed scaffold and does not consume the Binance API key/secret.
- The default runtime remains `TALIM_EXCHANGE_MODE=mock`; adding broker credentials to `.env` does not activate them unless the exchange mode/name and execution context are wired accordingly.
- Docker Compose explicitly forwards the supported broker env vars from `.env` into the `talim` container.

### Runtime Bootstrap

`talim.app.runtime.bootstrap_runtime()` is the live composition root used by the
default FastAPI app. It reads `.env`/environment settings and wires:

- selected exchange via `TALIM_EXCHANGE_MODE` / `TALIM_EXCHANGE_NAME`
- selected price feed via `TALIM_PRICEFEED` / `TALIM_PRICEFEED_TIMEFRAME`
- subscribed instruments from `TALIM_INSTRUMENTS`
- loaded strategy packages from `TALIM_STRATEGIES`
- default execution size from `TALIM_DEFAULT_QTY`
- persistent graph checkpoints from `TALIM_CHECKPOINT_DB`
- episodic decision memory from `TALIM_EPISODIC_DB`
- risk rules from `TALIM_RISK_CONFIG`

For `testnet` or `live`, `TALIM_INSTRUMENTS` and `TALIM_STRATEGIES` are
required explicitly so Talim does not accidentally trade a default strategy.

### Demo Execution Harness

Before using real broker demo credentials, run the deterministic mock execution
harness:

```bash
./.venv/bin/python scripts/run_demo_execution.py --state-dir state/demo-execution
```

It proves the runtime can complete scan -> HITL -> approve -> execute ->
episodic memory -> reconcile with one paper order and zero reconciliation
divergences. See [docs/live-demo-execution.md](docs/live-demo-execution.md).

### Operator / OpenClaw API

External operator clients can use the authenticated operator endpoints instead
of reaching into checkpoints directly:

- `GET /talim/operator/status`
- `GET /talim/operator/pending?thread_id=cron-main`
- `POST /talim/operator/decision` (optionally signal-id-scoped; approvals are re-validated before execution)
- `GET /talim/operator/positions`
- `GET /talim/operator/decisions` (entry/exit rows are explicitly paired)
- `GET /talim/operator/strategies` + `POST /talim/operator/strategies/{name}/enable|disable`
- `GET /talim/operator/backtests` + `GET /talim/operator/backtests/{id}`
- `GET /talim/operator/signals/{signal_id}` + `GET /talim/operator/signals/{signal_id}/chart`
- `POST /talim/sync?thread_id=cron-main`

See [docs/openclaw-operator-interface.md](docs/openclaw-operator-interface.md).

### Operator Dashboard

A static single-page dashboard is mounted at `/talim/dashboard/` (runtime
status, positions, pending HITL approve/reject, strategies, decisions,
backtest history, P&L), with a mobile-friendly signal detail page at
`/talim/dashboard/signal.html?signal=<signal_id>` (candlestick chart with
EMA overlays, entry/stop/target lines, live validation status) and an
open-positions page at `/talim/dashboard/positions.html`. Signals are
durable rows with stable ids and deep links; every pending signal carries a
strategy-specific validation status. Discord receives push notifications on
position open/close via `TALIM_DISCORD_POSITION_WEBHOOK`. See
[docs/operator-dashboard.md](docs/operator-dashboard.md).

### OpenClaw Host Deployment

If you're moving Talim onto the same host as OpenClaw, start with:

- [docs/openclaw-talim-host-integration.md](docs/openclaw-talim-host-integration.md)
- [docs/openclaw-host-cutover-checklist.md](docs/openclaw-host-cutover-checklist.md)
- [docs/openclaw-secrets-and-env.md](docs/openclaw-secrets-and-env.md)

### Runtime Sync / Reconciliation

`POST /talim/sync` refreshes broker positions and P&L, runs the existing
exchange-vs-memory-vs-state reconciliation check, and persists safe checkpoint
updates for the requested thread. It deliberately skips checkpoint mutation
while a HITL thread is paused so scheduled syncs cannot disturb a pending
approve/reject decision. See [docs/runtime-sync.md](docs/runtime-sync.md).

### LangGraph Brain (`talim/app/`)
The full graph topology:

```
cron_trigger ──▶ signal_scanner ──▶ position_monitor ──┐
                                                       ▼
bridge_message ──▶ converse ──▶ router ──┬─▶ risk_check ──┬─▶ hitl_interrupt ─[pause]─▶ execute ─▶ END
                                         │                └─▶ execute ─▶ END  (protective exits skip HITL)
                                         ├─▶ strategy_update ─▶ notify ─▶ END
                                         ├─▶ backtest_run ─▶ notify ─▶ END
                                         ├─▶ notify ─▶ END
                                         └─▶ END
```

Real implementations of every node:
- **signal_scanner** — pulls bars from the configured feed, computes ATR + regime fingerprint, runs each active strategy via the same `on_bar` interface used by backtests, writes a `pending_signal` if any strategy fires
- **router** + **edges** — deterministic 5-branch routing with priority (signal > regime > backtest > message > end)
- **risk_check** — enforces qty, total exposure, daily drawdown, same-instrument stacking, and correlation rules; blocked signals are routed through `notify` with the rejection reason
- **position_monitor** — checks open positions against strategy stop/target levels between scans and emits protective `exit` signals that bypass HITL after risk checks
- **hitl_interrupt** — formats the signal into an embed-ready message and pauses the graph (`interrupt_after`); operator approvals go through `Runtime.resume`, which refreshes broker state and bars, re-runs strategy-specific signal validation and risk checks, and only then executes — invalid/stale approvals are blocked and recorded on the durable signal row (WP-78)
- **strategy_update** — calls Claude with a strategy reasoning prompt, parses a JSON proposal, merges it into `strategy_params`
- **backtest_run** — runs the on_bar replay engine over multiple param variants and writes a sorted-by-Sharpe `backtest_result` list
- **converse** — parses an inbound message, activates referenced strategies, optionally classifies intent via Ollama
- **notify** — formats backtest results / pending notifications / user replies through the LLM when configured, falls back to deterministic templates otherwise

- **execute** — places the approved order via an injected exchange, writes an episodic record (with `signal_type`, `atr_ratio`, `action`, `notes`), and updates `open_pnl`/`last_action`. Supports both `enter` and `exit` signal actions; risk_check applies lighter rules to exits.

Dependency injection points (`configure_scanner`, `configure_risk_rules`, `configure_llm_client`, `configure_execute`) keep tests hermetic.

### MCP Tools (`talim/app/tools/`)
Thin wrappers exposed over an MCP stdio server: `get_positions`, `get_pnl`, `run_backtest`, `propose_strategy_update`, `query_episodic_memory`. Each takes a `ToolContext` and returns JSON-serialisable dicts.

### Security (`talim/security/`)
`Vault` loads exchange credentials from env once, stores secrets in a private dict (no getter), and exposes HMAC-SHA256 `sign(exchange, payload)`. `CcxtExchange.from_vault(...)` consumes it without ever touching the raw secret.

### Backtest Engine (`talim/backtest/`)
- `run_backtest(strategy_name, param_variants, ...)` replays bars through the strategy's own `on_bar` method (live/backtest parity)
- Per-trade exit simulation: stop or target — whichever the next bar's high/low touches first
- Position sizing models (`fixed_qty` / `risk_pct` with caps and compounding) via `BacktestSizingConfig`
- Standardised cost model (WP-86): per-venue spread/slippage/commission assumptions from `config/backtest_costs.json`, applied as adverse fills against mid-based bars — see [docs/backtest-cost-assumptions.md](docs/backtest-cost-assumptions.md)
- `compute_metrics`: net PnL, Sharpe, Sortino, max drawdown, win rate, profit factor, trade count
- Parquet data loader (per-day or single-file layouts; fails loudly on missing timeframes, wrong price types, or duplicate bars)
- Run history (`BacktestHistory`, SQLite) — every CLI/node/baseline run is recorded and queryable via the operator API
- Baseline snapshots: `scripts/rerecord_baselines.py` re-records the standard baseline set with costs applied ([docs/backtest-comparison-rules.md](docs/backtest-comparison-rules.md))
- Optional vectorbt fast path (`talim/backtest/vectorbt_engine.py`) selectable via `BacktestRequest.engine="vectorbt"`, with graceful fallback to on_bar when the package isn't installed
- Wired into the graph as the `backtest_run` node

### Data Ingestion (`scripts/`)
- `scripts/ingest_databento.py` + `scripts/ingest_tardis.py` — argparse CLIs with idempotent per-day skip, injectable `fetch_fn` for tests
- `scripts/ingest_forexcom_prices.py` — FOREX.com REST bar history → Parquet with dataset manifests
- Dukascopy deep-history backfill (WP-74): `scripts/ingest_dukascopy_ticks.py` (BI5 tick download → OHLCV Parquet with resume state and raw-hour caching), `build_dukascopy_canonical_bars.py`, `scan_dukascopy_coverage.py`, `retry_dukascopy_fetch_errors.py`, `run_dukascopy_year_pull_and_retry.py`
- Nightly cron entry in `scripts/cron.txt`

### LLM Layer (`talim/llm/`)
- `LLMClient` wraps **Claude** (reasoning) and **Ollama** (fast classification) with graceful fallback
- Prompt templates: strategy reasoning, backtest interpretation, regime observation, message classification
- `MockLLMClient` with canned responses + responder callbacks for deterministic tests

### Bridge API (`talim/api/`)
- FastAPI app with `POST /talim/converse` and `POST /talim/resume`
- `X-Talim-Secret` shared-secret auth (constant-time compare)
- External assistant clients (for example OpenClaw or a direct caller) can forward trading requests to the bridge using the shared secret

### Deployment (`Dockerfile`, `docker-compose.yml`, `nginx/`, `scripts/`)
- Four-service compose stack: `redis`, `talim`, `scheduler`, `nginx`
- Talim image runs `uvicorn talim.api.bridge:create_app --factory`
- Nginx reverse proxy with optional TLS
- `scripts/healthcheck.sh` verifies all services
- `scripts/cron.txt` for the 5-minute heartbeat trigger, offset broker-state sync, and nightly data update
- `.env.example` documents every required env var

## Project Structure

```
talim/
├── api/             # FastAPI bridge + shared-secret auth
├── app/             # LangGraph state, graph, edges, nodes, entrypoints, resume
│   └── nodes/       # signal_scanner, router, risk_check, hitl_interrupt,
│                    # backtest_run, converse, strategy_update, notify, execute
├── backtest/        # Engine, data loader, metrics
├── bus/             # Redis Streams pub/sub
├── connectors/
│   ├── discord/     # Bot, formatter, reaction handler
│   ├── exchange/    # Mock + ccxt + IG + FOREX.com
│   └── pricefeed/   # Mock + Binance + IG + FOREX.com + normalisers
├── llm/             # Client (Claude + Ollama), prompts, mock
├── memory/          # Episodic, pattern, working (SQLite)
├── models/          # Bar, position, signal, backtest, state
├── regime/          # Fingerprint, classifier, matcher, library
├── risk/            # Configurable RiskRules
└── strategy/        # BaseStrategy, loader, markdown store
strategies/
├── momentum-US500/
├── momentum-AU200/
└── mean-reversion-US500/
tests/
├── e2e/test_market_day.py   # Full simulated market day
└── test_*.py                # 56 unit/integration files (686 tests)
docker-compose.yml · Dockerfile · nginx/nginx.conf · scripts/
```

## Setup

Requires Python 3.11+.

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## Running Tests

```bash
pytest tests/                      # full suite (686 tests)
pytest tests/e2e/test_market_day.py -v   # simulated market day only
```

No external services required — Redis tests use `fakeredis`, SQLite uses tmp dirs, the LLM is stubbed via `MockLLMClient`, and the price feed/exchange/discord layers all have in-memory mocks. The backup tests shell out to the `sqlite3` CLI, so have it installed (`apt install sqlite3`).

## Running the Stack

```bash
cp .env.example .env
# fill in TALIM_BRIDGE_SECRET (required) and any selected venue credentials
# default venue mode is mock; Binance keys are optional and ccxt-only

docker compose up --build -d
./scripts/healthcheck.sh
```

The bridge is reachable at `http://localhost:8080/talim/health` (via nginx).

## End-to-End Scenario

`tests/e2e/test_market_day.py` exercises the complete pipeline against mocks:

1. Startup wires scanner, risk rules, LLM, episodic memory, and `MockExchange`
2. Scanner replays a sine-wave price tape; momentum-US500 fires a signal
3. Risk check passes; the graph pauses at `hitl_interrupt`
4. The signal is rendered into a Discord embed and registered with `ReactionHandler`
5. A ✅ reaction calls `resume_graph(approved=True)`; the graph runs `execute` and clears the pending signal
6. The decision is persisted to `EpisodicMemory`; the mock exchange records the fill
7. `bridge_message("what's my P&L?")` flows through `converse → router → notify` and returns the LLM-rendered reply
8. A regime change drives `strategy_update`, which produces a JSON parameter proposal via the mocked LLM
9. A multi-variant backtest runs through the engine and returns results sorted by Sharpe
10. Final assertions verify the episodic memory, exchange position, and full state

## Dependencies

LangGraph · pandas · numpy · scikit-learn · ccxt · Redis · FastAPI · uvicorn · discord.py · Anthropic SDK · pyarrow

Full list in [pyproject.toml](pyproject.toml). Status by work package: [PROGRESS.md](PROGRESS.md).
