# Talim

Agentic trading assistant powered by LangGraph. Talim monitors markets, detects regime changes, generates trade signals through pluggable strategies, routes them through risk checks and human-in-the-loop approval, executes against an exchange, and answers questions through a conversational bridge — all orchestrated as a stateful, checkpointed graph with persistent memory.

**Status:** 31 work packages complete (19 PoC + 12 spec reconciliation) · 302 tests green · all 7 PoC success criteria verified ([docs/poc-verification.md](docs/poc-verification.md)).

## Architecture

### End-to-end data flow

```
        ┌───────────────────────────┐   ┌───────────────────────────┐
        │      EXTERNAL INPUTS      │   │      EXTERNAL OUTPUTS     │
        │                           │   │                           │
        │  ▸ Databento / Tardis     │   │  ▸ Exchange (ccxt: orders)│
        │  ▸ Binance / IBKR feed    │   │  ▸ Discord (embeds + rx)  │
        │  ▸ Discord reactions      │   │  ▸ NanoClaw replies       │
        │  ▸ NanoClaw messages      │   │  ▸ Episodic journal       │
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
│   │   X-Talim-Secret auth    │                       │                     │
│   └────────────┬─────────────┘                       │                     │
│                │                                     │                     │
│                ▼                                     ▼                     │
│   ┌────────────────────────────────────────────────────────────────────┐   │
│   │                      LANGGRAPH BRAIN (StateGraph)                  │   │
│   │                                                                    │   │
│   │    cron_trigger ──▶ signal_scanner ───┐                            │   │
│   │                                       ▼                            │   │
│   │    bridge_message ─▶ converse ─▶ router ─┬─▶ risk_check            │   │
│   │                                          │        │                │   │
│   │                                          │        ▼                │   │
│   │                                          │   hitl_interrupt        │   │
│   │                                          │     [PAUSE]             │   │
│   │                                          │        │                │   │
│   │                                          │        ▼                │   │
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
│   │  ▸ Session matcher  │ │  ▸ momentum-ES    │ │  ▸ correlation    │      │
│   │  ▸ Macro calendar   │ │  ▸ mean-rev-ES    │ │  ▸ kill switch    │      │
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
│ MEMORY (SQLite) │         │ REDIS CONTAINER │       │  NANOCLAW          │
│                 │         │                 │       │  CONTAINER         │
│ ▸ episodic.db   │         │ ▸ Streams       │       │                    │
│   (decisions)   │         │ ▸ Consumer grps │       │  ▸ Intent router   │
│ ▸ pattern.db    │         │ ▸ AOF durable   │       │  ▸ Forwards trade  │
│   (fingerprints)│         │                 │       │    Qs to bridge    │
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
                    /talim/* │               │ (future: /nanoclaw/*)
                             ▼               ▼
                  ┌──────────────────┐ ┌───────────────────┐
                  │      talim       │ │     nanoclaw      │
                  │   talim-app      │ │  talim-nanoclaw   │
                  │   :8000 (uvicorn)│ │   (stub today)    │
                  │   healthcheck ✓  │ │                   │
                  └──────┬───────────┘ └───────────────────┘
                         │
              ┌──────────┼──────────┐
              ▼          ▼          ▼
        ┌─────────┐ ┌─────────┐ ┌────────────┐
        │  redis  │ │ sqlite  │ │  host vols │
        │ :6379   │ │ volume  │ │ data/ logs/│
        │ healthy │ │ (dbs)   │ │            │
        └─────────┘ └─────────┘ └────────────┘
```

### HITL sequence (signal → Discord → resume)

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
| **momentum-ES** | EMA(8) / EMA(21) crossover | 1.5× ATR | 3.0× ATR |
| **mean-reversion-ES** | Bollinger Band (20, 2σ) reversion | 2.0× ATR | 1.5× ATR |

### Memory (`talim/memory/`)
- **EpisodicMemory** — decision journal (signals, approvals, fills, outcomes)
- **PatternMemory** — packed-blob fingerprint library
- **WorkingMemory** — `SqliteSaver` checkpointer for graph state (survives restarts)

### Event Bus (`talim/bus/`)
- Redis Streams pub/sub with consumer groups
- `BarEvent`, `RegimeChangeEvent`, `SignalEvent`, `TradeEvent`

### Connectors (`talim/connectors/`)
- **Price feeds:** `BasePriceFeed`, `MockPriceFeed` (DataFrame/Parquet/CSV replay), Binance ccxt.pro scaffold, normaliser
- **Exchanges:** `BaseExchange`, `MockExchange` (in-memory fills + position tracking with flip/partial-close), `CcxtExchange`, env credential loader
- **Discord:** rich-embed formatter (signals/backtests/regimes/log), `ReactionHandler` mapping ✅/❌ to HITL resume, `TalimDiscordBot` discord.py shell

### LangGraph Brain (`talim/app/`)
The full graph topology:

```
cron_trigger ──▶ signal_scanner ──┐
                                  ▼
bridge_message ──▶ converse ──▶ router ──┬─▶ risk_check ─▶ hitl_interrupt ─[pause]─▶ execute ─▶ END
                                         ├─▶ strategy_update ─▶ notify ─▶ END
                                         ├─▶ backtest_run ─▶ notify ─▶ END
                                         ├─▶ notify ─▶ END
                                         └─▶ END
```

Real implementations of every node:
- **signal_scanner** — pulls bars from the configured feed, computes ATR + regime fingerprint, runs each active strategy via the same `on_bar` interface used by backtests, writes a `pending_signal` if any strategy fires
- **router** + **edges** — deterministic 5-branch routing with priority (signal > regime > backtest > message > end)
- **risk_check** — enforces qty, total exposure, daily drawdown, same-instrument stacking, and correlation rules; blocked signals are routed through `notify` with the rejection reason
- **hitl_interrupt** — formats the signal into an embed-ready message and pauses the graph (`interrupt_after`); resumes via `talim.app.resume.resume_graph(thread_id, approved)` which injects `signal_approved` into checkpointed state
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
- `compute_metrics`: net PnL, Sharpe, max drawdown, win rate, trade count
- Parquet data loader (per-day or single-file layouts)
- Optional vectorbt fast path (`talim/backtest/vectorbt_engine.py`) selectable via `BacktestRequest.engine="vectorbt"`, with graceful fallback to on_bar when the package isn't installed
- Wired into the graph as the `backtest_run` node

### Data Ingestion (`scripts/`)
- `scripts/ingest_databento.py` + `scripts/ingest_tardis.py` — argparse CLIs with idempotent per-day skip, injectable `fetch_fn` for tests
- Nightly cron entry in `scripts/cron.txt`

### LLM Layer (`talim/llm/`)
- `LLMClient` wraps **Claude** (reasoning) and **Ollama** (fast classification) with graceful fallback
- Prompt templates: strategy reasoning, backtest interpretation, regime observation, message classification
- `MockLLMClient` with canned responses + responder callbacks for deterministic tests

### Bridge API (`talim/api/`)
- FastAPI app with `POST /talim/converse` and `POST /talim/resume`
- `X-Talim-Secret` shared-secret auth (constant-time compare)
- Stub `nanoclaw/router.py` that classifies an incoming message and forwards trading questions to the bridge

### Deployment (`Dockerfile`, `docker-compose.yml`, `nginx/`, `scripts/`)
- Four-service compose stack: `redis`, `talim`, `nanoclaw`, `nginx`
- Talim image runs `uvicorn talim.api.bridge:create_app --factory`
- Nginx reverse proxy with optional TLS
- `scripts/healthcheck.sh` verifies all services
- `scripts/cron.txt` for the 5-minute heartbeat trigger and nightly data update
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
│   ├── exchange/    # Mock + ccxt
│   └── pricefeed/   # Mock + Binance + normaliser
├── llm/             # Client (Claude + Ollama), prompts, mock
├── memory/          # Episodic, pattern, working (SQLite)
├── models/          # Bar, position, signal, backtest, state
├── regime/          # Fingerprint, classifier, matcher, library
├── risk/            # Configurable RiskRules
└── strategy/        # BaseStrategy, loader, markdown store
strategies/
├── momentum-ES/
└── mean-reversion-ES/
nanoclaw/            # Stub intent router that forwards to the bridge
tests/
├── e2e/test_market_day.py   # Full simulated market day
└── test_*.py                # 16 unit/integration files (266 tests)
docker-compose.yml · Dockerfile · nginx/nginx.conf · scripts/
```

## Setup

Requires Python 3.11+.

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pip install langgraph-checkpoint-sqlite pyarrow requests
```

## Running Tests

```bash
pytest tests/                      # full suite (302 tests)
pytest tests/e2e/test_market_day.py -v   # simulated market day only
```

No external services required — Redis tests use `fakeredis`, SQLite uses tmp dirs, the LLM is stubbed via `MockLLMClient`, and the price feed/exchange/discord layers all have in-memory mocks.

## Running the Stack

```bash
cp .env.example .env
# fill in TALIM_BRIDGE_SECRET (required) and ANTHROPIC_API_KEY etc.

docker compose up --build -d
./scripts/healthcheck.sh
```

The bridge is reachable at `http://localhost:8080/talim/health` (via nginx).

## End-to-End Scenario

`tests/e2e/test_market_day.py` exercises the complete pipeline against mocks:

1. Startup wires scanner, risk rules, LLM, episodic memory, and `MockExchange`
2. Scanner replays a sine-wave price tape; momentum-ES fires a signal
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
