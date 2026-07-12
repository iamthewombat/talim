# AGENTS.md

## Current Project Direction

- Talim is the trading agent. OpenClaw is expected to be an external interface that talks to Talim through the bridge API; the bundled NanoClaw stub path has been removed from the runtime assumptions.
- The current trading focus is index CFDs (`US500.cash`, `AU200.cash`) through the broker-neutral CFD layer, with first-party `ig` and `forexcom` adapters. The live runtime currently scans US500 through the FOREX.com feed.
- Binance remains available only through the generic `CcxtExchange` path for Binance/Bybit-style venues. Do not treat Binance credentials as required for the CFD path.

## Credential Rules

- `BINANCE_API_KEY` / `BINANCE_API_SECRET` are used only when `TALIM_EXCHANGE_MODE` is `testnet` or `live` and `TALIM_EXCHANGE_NAME=binance`.
- `TALIM_PRICEFEED=binance` uses the public Binance ccxt.pro feed scaffold and does not consume the Binance API key/secret.
- `TALIM_EXCHANGE_NAME=ig` uses IG env vars such as `IG_API_KEY`, `IG_DEMO_API_KEY`, `IG_IDENTIFIER`, `IG_PASSWORD`, `IG_CST`, and `IG_SECURITY_TOKEN`.
- `TALIM_EXCHANGE_NAME=forexcom` uses `FOREXDOTCOM_LOGIN`, `FOREXDOTCOM_PASSWORD`, `FOREXDOTCOM_APP_KEY`, and optional account id env vars.
- `TALIM_DISCORD_POSITION_WEBHOOK` (renamed from `TALIM_DISCORD_CLOSEOUT_WEBHOOK`) is the Discord webhook for position open/close push cards; it is optional and independent of the unused native Discord bot token.
- The default exchange mode is `mock`; credentials present in `.env` do not activate a live broker by themselves.
- Never commit `.env` or real broker credentials.

## Operational Notes

- Default FastAPI startup uses `talim.app.runtime.bootstrap_runtime()` to wire
  exchange/feed/strategy/risk/checkpoint contexts. If adding runtime env vars,
  update `.env.example`, `docker-compose.yml`, and the exchange setup docs.
- Active roadmap/progress files are indexed in `CENTRAL_PROGRESS.md`. When
  creating a new durable Talim planning, progress, checklist, or roadmap
  markdown file, append it to that central index in the same session with status
  and pickup guidance.
- Use `scripts/run_demo_execution.py` as the local proof that scan -> HITL ->
  approve -> execute -> memory -> reconcile still works before attempting real
  broker demo execution.
- Exit signals must use `BaseExchange.close_position(...)`; do not place a
  raw opposite entry order unless the adapter explicitly implements that as its
  close mechanism.
- HITL semantics: entry signals pause at `hitl_interrupt` and approvals are
  re-validated at decision time (`Runtime.resume` refreshes broker state and
  bars, re-runs strategy validation and risk checks; stale/invalid approvals
  are blocked). Protective exit signals from `position_monitor` bypass HITL
  and execute directly after risk checks — do not add an approval gate to the
  exit path without a decision from Justin.
- Backtest comparisons should use the standardised cost model
  (`--costs-venue` on `scripts/run_backtest.py`; assumptions in
  `config/backtest_costs.json`). Baselines are re-recorded with
  `scripts/rerecord_baselines.py` on a machine with the ingested datasets —
  see `docs/backtest-comparison-rules.md` before changing strategy defaults.
- OpenClaw/operator clients should use `/talim/operator/*` endpoints for HITL
  decisions and `/talim/sync` for fresh broker position/P&L reconciliation,
  rather than reading LangGraph checkpoints directly.
- Prefer the CFD conformance tests when touching IG or FOREX.com behavior.
- Keep broker-specific behavior inside adapters, normalisers, and the CFD registry. Strategy, risk, and scanner code should work with canonical instrument ids such as `AU200.cash`.
- For Docker runs, broker env vars are explicitly forwarded through `docker-compose.yml`; update both `.env.example` and compose if adding a new required venue env var.
