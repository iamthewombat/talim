# PoC Success Criteria — Verification

Verified 2026-04-07. Stack brought up via `docker compose up --build -d`; healthcheck via `./scripts/healthcheck.sh`.

| # | Criterion | Verified | Evidence |
|---|-----------|----------|----------|
| 1 | Start stack with `docker compose up` | ✅ | `docker compose ps` shows redis (healthy), talim (healthy), nanoclaw (up), nginx (up). `./scripts/healthcheck.sh` → "All services healthy." |
| 2 | Replay historical bars, detect regimes, fire signals | ✅ | `tests/e2e/test_market_day.py::test_full_market_day` replays bars through MockPriceFeed → scanner → fingerprint/classifier → strategy `on_bar` → Signal emitted. |
| 3 | Receive trade alert in Discord with context | ✅ | `tests/test_discord.py::TestFormatter` covers embed formatting (regime + risk/reward); `tests/e2e/test_market_day.py` registers a Discord-style reaction handler against the formatted embed. |
| 4 | React with checkmark, see MockExchange log fill | ✅ | `tests/e2e/test_market_day.py::test_full_market_day` and `tests/test_execute_node.py::test_execute_places_order_and_records_decision` — reaction → resume_graph → execute node → MockExchange.place_order. |
| 5 | Ask "what's my P&L?" and get accurate response | ✅ | `tests/test_bridge.py` POSTs `/talim/converse` with a P&L question and the converse node returns the rendered MockLLMClient answer using state.open_pnl/daily_pnl. |
| 6 | Request backtest and see Sharpe/drawdown results | ✅ | `tests/test_backtest.py` and `tests/test_vectorbt_engine.py` exercise both engines; `tests/e2e/test_market_day.py` runs a multi-variant backtest end-to-end and asserts BacktestResult fields populated. |
| 7 | All decisions logged in episodic memory | ✅ | `tests/test_memory.py::TestEpisodicMemory` round-trips records (incl. WP-21 columns); `tests/e2e/test_market_day.py` asserts the post-run episodic count increases after the executed trade. |

## Stack snapshot

```
NAME             SERVICE    STATUS
talim-redis      redis      Up (healthy)
talim-app        talim      Up (healthy)
talim-nanoclaw   nanoclaw   Up
talim-nginx      nginx      Up   0.0.0.0:8080->80
```

## Healthcheck output

```
OK:   redis ping
OK:   bridge /health via nginx
OK:   bridge /talim/health direct
OK:   nanoclaw running
All services healthy.
```
