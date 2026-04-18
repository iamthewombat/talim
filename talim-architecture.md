# Talim — Agentic Trading System Architecture

> Version 1.0 — Architecture reference document  
> Status: Design phase

---

## 1. Overview

Talim is a personal agentic trading system built to monitor markets, detect regime changes, run simultaneous strategies, execute trades with human-in-the-loop confirmation, and backtest adjustments in near real time. She runs as a persistent process on a VPS, communicates via Discord, and is orchestrated using LangGraph.

Talim is not a monolithic trading bot. She is a reasoning agent backed by deterministic signal computation, with an LLM called only when judgment is required. The majority of her work — scanning price bars, computing ATR, checking thresholds — runs as pure Python with no LLM involved.

### Design principles

- **Bus-first internally** — components communicate through a shared LangGraph state object, not direct calls
- **LLM on the edges** — deterministic code handles the fast path; LLM is invoked for reasoning tasks only
- **One orchestrator** — a single LangGraph application holds all state; no competing orchestration layers
- **Parity by architecture** — strategy code is identical between live execution and backtesting; only the data source changes
- **Human stays in the loop** — no live trade executes without an explicit approval from Discord
- **Memory is typed** — four distinct memory stores, each with a clear scope; nothing crosses boundaries

---

## 2. System components

### 2.1 External assistant client (optional)

An external assistant client — for example OpenClaw, a Discord bot, or another private tool — may sit in front of Talim. It handles general tasks such as calendar, research, reminders, and non-trading chat. It has no knowledge of Talim's internal state unless Talim returns it through the bridge.

Its only connection to Talim is the **bridge API** — a small HTTP contract. When the assistant detects a trading-related intent in an incoming message, it forwards it to Talim via `POST /talim/converse`. Talim's reply is returned to the caller, which can then render or relay it however it wants.

The assistant layer is optional scaffolding. Talim functions independently of it.

**What the external assistant handles directly (without routing to Talim):**

- Calendar and scheduling queries
- General research and web search
- News summaries unrelated to open positions
- Personal reminders and tasks

**What the external assistant routes to Talim:**

- Any message about strategies, positions, regime, signals
- Backtest requests
- Commands to pause, adjust, or override strategies
- Requests for P&L or portfolio status

### 2.2 Talim (trading agent)

Talim is a **LangGraph application** running as a persistent Python process. She has two independent entry points:

1. **Cron trigger** — fires every 5 minutes during market hours, initiates the signal scanning loop
2. **Bridge POST** — receives forwarded messages from an external assistant client

Both entry points flow through the same LangGraph graph, sharing the same state object.

---

## 3. Infrastructure

### 3.1 Hosting

**OVH VPS — vps-2025-model1**

| Resource | Spec |
|----------|------|
| vCores | 4 |
| RAM | 8 GB |
| Storage | 75 GB NVMe |
| Network | 400 Mbps, unlimited traffic |
| OS | Ubuntu 24.04 |
| Region | Sydney (for APAC exchange proximity) |

**RAM budget estimate:**

| Component | Estimated usage |
|-----------|----------------|
| Redis Streams (internal bus) | ~200 MB |
| Talim LangGraph process | ~1.5 GB |
| External assistant client | ~500 MB |
| SQLite + OS + headroom | ~1 GB |
| **Total** | **~3.2 GB** (~5 GB spare) |

### 3.2 Deployment

Docker Compose manages all services. Each service has a restart policy of `always` so a crashed component recovers automatically without intervention.

```
services:
  talim          # LangGraph application
  redis          # Internal event bus
  nginx          # Reverse proxy for bridge API
```

The OVH VPS runs the full stack. The spare laptop is the development environment — the stack runs identically locally. No cloud services are required for core operation.

---

## 4. LangGraph graph definition

### 4.1 State object

The state object is a `TypedDict` checkpointed to SQLite after every node. It survives process restarts. This is Talim's working memory.

```python
class TalimState(TypedDict):
    # Market state
    last_tick: datetime
    instrument: str
    current_bar: OHLCVBar
    atr_current: float
    atr_ratio: float          # current / 20-day avg
    regime: str               # "momentum" | "mean_reversion" | "ranging" | "high_vol"
    regime_fingerprint: list[float]   # 6-feature vector

    # Portfolio state
    positions: list[Position]
    open_pnl: float
    daily_pnl: float

    # Strategy state
    active_strategies: list[str]       # names of active strategy MD files
    strategy_params: dict              # live param values per strategy

    # Decision state
    pending_signal: Signal | None      # signal awaiting HITL approval
    pending_backtest: BacktestRequest | None
    discord_thread_id: str | None      # thread to reply to

    # Conversation state
    messages: list[dict]               # current conversation history
    last_user_message: str | None

    # Result state
    backtest_result: BacktestResult | None
    last_action: str | None
```

### 4.2 Graph nodes

**Deterministic nodes (no LLM):**

| Node | Entry point | What it does |
|------|------------|--------------|
| `signal_scanner` | Cron | Pulls latest bars, computes ATR, regime fingerprint, checks signal thresholds |
| `converse` | Bridge POST | Parses incoming message, loads relevant strategy markdowns into state |
| `risk_check` | After router | Validates position limits, max drawdown, correlation checks before approving a trade |
| `execute` | After HITL approval | Calls exchange MCP tool, updates state with fill details |

**LLM-routed nodes:**

| Node | LLM tier | What it does |
|------|----------|--------------|
| `router` | Ollama (fast) | Reads current state, decides which branch to take |
| `strategy_update` | Claude | Reads strategy MD, proposes param changes, drafts Discord alert |
| `backtest_run` | — | Triggers vectorbt locally or QuantConnect via MCP |
| `notify` | Claude | Formats result or observation into a Discord message |
| `hitl_interrupt` | — | Freezes graph, posts to Discord, waits for approval reaction |

### 4.3 Conditional edges (router logic)

The router inspects current state after every scan and conversation and routes to exactly one branch:

```
no threshold crossed    →  END (silent)
regime change detected  →  strategy_update → notify → END
user asked question     →  notify → END
backtest requested      →  backtest_run → notify → END
trade signal fired      →  risk_check → hitl_interrupt → [approve] → execute → END
                                                         [reject]  → END
```

### 4.4 HITL interrupt

The human-in-the-loop interrupt is a native LangGraph feature. When a trade signal passes risk_check, the graph:

1. Formats a rich Discord message including entry price, strategy rationale, regime context, estimated risk, and P&L projection
2. Posts it to `#talim-alerts`
3. Freezes the graph state to SQLite
4. Waits indefinitely

When you react with ✅ or ❌ (or reply via slash command), the external assistant or Discord integration translates the reaction to a `POST /talim/resume` call. LangGraph resumes from the checkpoint with full context intact, including the pending signal and all market state at the time the signal fired.

If the VPS restarts while a signal is pending, the interrupt resumes correctly on restart — the SQLite checkpoint is the source of truth.

---

## 5. LLM routing

Talim uses two LLM tiers. The routing decision is deterministic code inside the `router` node — not itself an LLM call.

| Task | LLM | Rationale |
|------|-----|-----------|
| 5-min heartbeat signal scan | None | Pure maths — ATR, fingerprint computation |
| Classify Discord message intent | Ollama (Mistral 7B) | Simple classification, ~288 calls/day |
| Draft routine regime observation | Ollama | Templated output, local model sufficient |
| Strategy reasoning + param advice | Claude API | Requires deep context + nuance |
| Interpret backtest results | Claude API | Multi-metric reasoning with market knowledge |
| Confirm live strategy change | Claude API | High stakes, needs full strategy markdown context |
| Conversation about market / regime | Claude API | Open-ended reasoning |

**Cost implication:** most of Talim's daily activity never touches an API. Claude is called perhaps 5–20 times per day for genuinely reasoning-heavy tasks.

---

## 6. Connectors (MCP tool layer)

All external systems are accessed through a standard MCP tool interface. Talim calls tools by name; the implementation is swappable without changing graph logic.

### 6.1 Exchange connector

Abstracts across all execution venues behind a common interface:

```python
exchange.place_order(instrument, side, qty, order_type, params)
exchange.cancel_order(order_id)
exchange.get_positions()
exchange.get_account_balance()
```

**Supported venues:**
- Crypto: Binance, Bybit (via `ccxt`)
- Futures: Interactive Brokers (via `ib_insync`)
- CFDs: CMC Markets, IG (via broker REST APIs)

Credentials are loaded from the credential vault at process startup. API keys are IP-whitelisted and carry trade-only permissions — no withdrawal access on any exchange key.

### 6.2 Backtest connector

```python
backtest.run(strategy_name, param_variant, matched_dates)
backtest.run_qc(strategy_code, param_variant, date_range)   # QuantConnect MCP
```

Default implementation uses vectorbt locally against Parquet files. QuantConnect MCP is available as an alternative for cross-validation on a different data source. Talim does not care which runs — the connector decides based on data availability and request type.

### 6.3 Price feed connector

Maintains persistent WebSocket connections to exchange feeds. Normalises all tick and bar data to a common schema before publishing to the internal event bus:

```python
{
  "instrument": "ES",
  "timestamp": "2026-03-22T00:15:00Z",
  "open": 5241.25,
  "high": 5244.50,
  "low": 5239.75,
  "close": 5243.00,
  "volume": 12840
}
```

### 6.4 Discord connector

Two-way. Outbound: posts formatted alerts to `#talim-alerts` and replies to `#talim-chat`. Inbound: an external assistant or Discord integration listens for reactions and commands, then translates them to bridge API calls.

**Discord channel structure:**

| Channel | Purpose |
|---------|---------|
| `#talim-chat` | Open conversation with Talim — strategy discussion, questions, ad hoc requests |
| `#talim-alerts` | Trade signals and confirmation requests (Talim posts, you react) |
| `#talim-log` | Structured event log — regime changes, strategy updates, backtest completions |

### 6.5 Credential vault

Secrets are loaded once at process startup into memory. Never written to disk at runtime. Never passed to LLM context.

For the crypto wallet, the private key is held in an in-memory signer. The signer is invoked at the network boundary only — Talim calls `signer.sign(transaction)` and receives a signed transaction back. The key itself never appears in any LLM prompt or log.

---

## 7. Backtesting

### 7.1 Parity rule

Strategy logic code is identical between live execution and backtest. The only difference is the data source:

- **Live:** `strategy.on_bar(live_feed.next_bar())`
- **Backtest:** `strategy.on_bar(historical_df.iloc[i])`

This is enforced architecturally — the same Python module is imported in both paths.

### 7.2 Regime matching

Before running a backtest, Talim finds historically similar market conditions using nearest-neighbour matching on a 6-feature fingerprint:

| Feature | Description |
|---------|-------------|
| `atr_ratio` | Current ATR / 20-day average |
| `adx` | Trend strength |
| `price_position` | Close position in recent high-low range (0–1) |
| `range_expansion` | Today's range vs 10-day average |
| `session_return` | Normalised open-to-now return |
| `volume_ratio` | Current volume vs average |

The regime library is a SQLite table of pre-computed fingerprints for every historical session. Matching is numpy array arithmetic — runs in under a millisecond for 5 years of daily data.

```python
distances = np.linalg.norm(library_features - today_fingerprint, axis=1)
matched_dates = library_dates[distances <= SIMILARITY_THRESHOLD]
```

Domain filters are applied on top of the distance threshold (exclude macro event windows, match session type, require minimum 30 matches for statistical validity).

### 7.3 Data sources

| Instrument | Source | Format | Granularity |
|------------|--------|--------|-------------|
| ES futures | Databento | Parquet | 5-min OHLCV |
| BTC, ETH perps | Tardis | Parquet | 5-min OHLCV |
| XJO / SPI200 | Databento | Parquet | 5-min OHLCV |

Historical data is stored locally on the VPS. A nightly cron job appends the previous day's bars and updates the regime library.

### 7.4 Backtest result schema

```python
{
  "strategy": "momentum-ES",
  "param_a": {"stop_loss_pts": 22},
  "param_b": {"stop_loss_pts": 7},
  "matched_sessions": 67,
  "avg_distance": 0.84,
  "results": {
    "param_a": {"net_pnl": 14200, "sharpe": 0.84, "max_dd": -8400, "win_rate": 0.52},
    "param_b": {"net_pnl": 18900, "sharpe": 1.12, "max_dd": -5100, "win_rate": 0.44}
  },
  "talim_assessment": "...",   # LLM-generated interpretation
  "statistical_power": "good"
}
```

---

## 8. Memory architecture

Four distinct memory stores. Assistant-side memory is separate from Talim's internal stores.

### 8.1 Talim — working memory (Type A)

**Store:** SQLite via LangGraph `SqliteSaver`  
**Contents:** The full state object — positions, regime, pending signals, conversation history  
**Lifetime:** Persistent across restarts. Updated after every node execution.  
**Access:** LangGraph reads and writes automatically via checkpointer

### 8.2 Talim — semantic memory (Type B)

**Store:** Markdown files on filesystem, git-tracked  
**Contents:** One `.md` file per strategy. Contains rationale, regime applicability, parameter definitions, backtest history, and decision log.  
**Lifetime:** Persistent and version-controlled. Talim reads at conversation time, writes after decisions.  
**Access:** `strategy_store.read(name)` / `strategy_store.write(name, content)`

**Strategy markdown template:**

```markdown
# Strategy: momentum-ES

## Purpose
Trend-following on ES 5-min bars. Designed for momentum regimes (ADX > 25, ATR ratio 0.8–1.4).

## Regime applicability
- Suitable: momentum, high-vol trending
- Avoid: ranging, mean-reversion

## Current parameters
- entry_signal: ema_cross_20_50
- stop_loss_pts: 22
- target_pts: 44
- max_position_size: 2 contracts

## Backtest history
| Date | Change | ATR regime | Sharpe before | Sharpe after |
|------|--------|-----------|---------------|--------------|
| 2026-03-22 | stop 22→7 | high-vol | 0.84 | 1.12 |

## Decision log
2026-03-22: Tightened stop during high-vol session (ATR ratio 1.64).
  Approved by Justin. Reverted at session close.
```

### 8.3 Talim — episodic memory (Type C)

**Store:** SQLite, append-only  
**Contents:** Every signal, approval decision, and trade outcome with full context  
**Lifetime:** Permanent. Never deleted. Used for retrospective queries.

```sql
CREATE TABLE decisions (
  id          INTEGER PRIMARY KEY,
  timestamp   DATETIME NOT NULL,
  instrument  TEXT NOT NULL,
  strategy    TEXT NOT NULL,
  signal_type TEXT NOT NULL,       -- 'entry' | 'exit' | 'strategy_change' | 'backtest'
  regime      TEXT,
  atr_ratio   REAL,
  action      TEXT NOT NULL,       -- what Talim proposed
  approved    BOOLEAN,             -- NULL if autonomous (no HITL needed)
  outcome     TEXT,                -- filled in after trade closes
  pnl         REAL,
  notes       TEXT                 -- LLM-generated context at decision time
);
```

### 8.4 Talim — pattern memory (Type D)

**Store:** SQLite table (`regime_library`)  
**Contents:** Pre-computed 6-feature fingerprints for every historical session  
**Lifetime:** Updated nightly by cron job  
**Access:** Numpy nearest-neighbour search at backtest time

### 8.5 External assistant memory

**Store:** Depends on the assistant implementation (for example OpenClaw state/config or another external memory store)  
**Contents:** Personal preferences, calendar context, general facts about you  
**Scope:** Never contains trading state, positions, or strategy information

**Hard boundary:** Talim's SQLite databases and markdown files are not mounted into the assistant runtime. The assistant cannot read or write Talim's memory directly.

---

## 9. Strategy definition format

Strategies live as code (Python) and documentation (Markdown). The two are linked by name.

```
/strategies/
  momentum-ES/
    strategy.py        # live-runnable code
    momentum-ES.md     # Talim's memory of this strategy
  mean-reversion-ES/
    strategy.py
    mean-reversion-ES.md
  ...
```

The Python file contains the `on_bar()` function and parameter definitions. The markdown file contains the rationale, history, and Talim's evolving understanding of when to apply it. Both are git-tracked.

---

## 10. Regime detection

Regime detection runs as a continuous background process, publishing `regime.signal` events to the internal bus when the current regime classification changes.

**Six-feature fingerprint:**

```python
def compute_fingerprint(bars: pd.DataFrame) -> np.ndarray:
    return np.array([
        bars['atr'].iloc[-1] / bars['atr'].rolling(20).mean().iloc[-1],  # atr_ratio
        compute_adx(bars, period=14).iloc[-1],                            # trend strength
        (bars['close'].iloc[-1] - bars['low'].rolling(10).min().iloc[-1])
        / (bars['high'].rolling(10).max() - bars['low'].rolling(10).min()).iloc[-1],  # price_position
        (bars['high'].iloc[-1] - bars['low'].iloc[-1])
        / (bars['high'] - bars['low']).rolling(10).mean().iloc[-1],       # range_expansion
        (bars['close'].iloc[-1] - bars['open'].iloc[0]) / bars['close'].iloc[0],  # session_return
        bars['volume'].iloc[-1] / bars['volume'].rolling(20).mean().iloc[-1],     # volume_ratio
    ])
```

**Regime labels** are assigned by clustering the fingerprint library (k-means, k=4) and labelling clusters from historical context. Labels are: `momentum`, `mean_reversion`, `ranging`, `high_vol`.

---

## 11. Deployment topology

```
OVH VPS (Sydney)
├── Docker Compose
│   ├── talim/
│   │   ├── app/           # LangGraph application
│   │   │   ├── graph.py   # StateGraph definition
│   │   │   ├── nodes/     # One file per node
│   │   │   ├── tools/     # MCP tool wrappers
│   │   │   └── state.py   # TalimState TypedDict
│   │   ├── strategies/    # strategy.py + .md per strategy
│   │   ├── data/          # Parquet files (OHLCV history)
│   │   └── db/            # SQLite files
│   │       ├── langgraph.db      # LangGraph checkpoints
│   │       ├── regime_library.db # fingerprint library
│   │       └── decisions.db      # episodic memory
│   ├── redis/             # Internal event bus
│   └── nginx/             # Reverse proxy, TLS termination
│
└── Cron jobs
    ├── */5 * * * *   talim heartbeat trigger (market hours)
    └── 0 2 * * *     nightly data update + regime library rebuild
```

---

## 12. Key technology choices

| Component | Choice | Rationale |
|-----------|--------|-----------|
| Orchestration | LangGraph | Persistent state, durable HITL interrupts, conditional edges |
| Personal assistant | External assistant client (for example OpenClaw) | Keep the bridge boundary stable; deploy the assistant independently |
| Backtest engine | vectorbt | Fast, pandas-native, parity with live code |
| Backtest cross-check | QuantConnect MCP | Independent data source for validation |
| Crypto exchange | ccxt | Unified API across Binance, Bybit etc. |
| Futures / CFD | ib_insync / broker REST | IBKR API for futures; CMC/IG for CFDs |
| Internal bus | Redis Streams | Persistent, fast, handles heterogeneous event types |
| LangGraph state | SqliteSaver | Lightweight, no external dependency, survives restarts |
| LLM (reasoning) | Claude API | Deep context handling, strategy markdown reasoning |
| LLM (fast tasks) | Ollama (Mistral 7B) | Local, free, sufficient for classification |
| Historical data | Databento + Tardis | Institutional-quality futures and crypto bars |
| Data format | Parquet | Columnar, fast reads for backtesting |
| Strategy versioning | Git | Full history of every strategy evolution |
| Hosting | OVH VPS | 4 vCores / 8 GB / Sydney DC, ~$30 AUD/month |

---

## 13. What is NOT in scope (v1)

The following are identified future enhancements, deliberately excluded from v1 to keep initial complexity manageable:

- **Vector database** — semantic search over past decisions; plain SQLite + numpy is sufficient initially
- **Auto-parameter evolution (ATLAS-style)** — Karpathy autoresearch loop applied to strategy prompts; a future enhancement once base system is stable
- **Multi-instrument parallelism** — v1 runs strategies sequentially per heartbeat; parallel runners are an optimisation
- **Mobile app** — Discord is the interface; a dedicated app is a future concern
- **Live P&L dashboard** — Discord log provides sufficient visibility for v1

---

## 14. Open decisions

These items have been discussed but not finalised:

| Decision | Options | Notes |
|----------|---------|-------|
| CFD broker | CMC Markets, IG, Saxo | Depends on instrument coverage for XJO/SPI200 |
| Crypto wallet custody | In-memory signer, hardware wallet | Hardware wallet preferred above position threshold |
| Ollama model | Mistral 7B, Llama 3.1 8B | Benchmark both on classification tasks before committing |
| QuantConnect tier | Free (limited backtest minutes) vs paid | Assess whether local vectorbt is sufficient first |
| Regime clustering k | 4 labels (initial) | Tune after first month of fingerprint data |
| HITL timeout | None (wait forever) vs 30 min auto-cancel | Risk preference — auto-cancel is safer for overnight signals |
