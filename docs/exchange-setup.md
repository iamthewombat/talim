# Exchange Setup

Talim supports three exchange modes via `TALIM_EXCHANGE_MODE`:

| Mode | What it does | Credentials needed? |
|------|-------------|---------------------|
| `mock` (default) | In-memory `MockExchange` — instant fills, no network | No |
| `testnet` | Real sandbox/demo adapter: ccxt sandbox for Binance/Bybit, IG demo for IG | Yes |
| `live` | Real production adapter: ccxt production for Binance/Bybit, broker live for CFDs | Yes |

## Supported exchanges

Any exchange supported by [ccxt](https://github.com/ccxt/ccxt). Tested with:

- **Binance** via `CcxtExchange` (futures testnet available)
- **Bybit** via `CcxtExchange` (testnet available)
- **IG AU** (custom OTC CFD adapter, demo/live auth supported)
- **FOREX.com AU** (custom CFD adapter, demo/live auth supported)

## Current credential status

The active CFD architecture is broker-neutral AU200 trading via `ig` or
`forexcom`. Binance credentials are optional and belong to the older ccxt
crypto/testnet path.

`BINANCE_API_KEY` / `BINANCE_API_SECRET` are used only when all of these are
true:

```env
TALIM_EXCHANGE_MODE=testnet
TALIM_EXCHANGE_NAME=binance
```

or:

```env
TALIM_EXCHANGE_MODE=live
TALIM_EXCHANGE_NAME=binance
```

They are not used by `TALIM_EXCHANGE_NAME=ig`, `TALIM_EXCHANGE_NAME=forexcom`,
or the AU200 CFD registry. They are also not used by `TALIM_PRICEFEED=binance`;
that price feed currently uses the public ccxt.pro feed scaffold.

Adding keys to `.env` does not activate a broker by itself. The runtime must
select the broker with `TALIM_EXCHANGE_MODE` and `TALIM_EXCHANGE_NAME`.
Non-FastAPI/test entrypoints still need to configure the execute context
explicitly if they bypass the runtime bootstrap.

The production FastAPI app now calls `talim.app.runtime.bootstrap_runtime()` by
default, which wires the selected exchange, feed, strategy list, scanner,
execute context, risk config, and persistent checkpointer into the graph.

Minimum live/demo runtime selection:

```env
TALIM_EXCHANGE_MODE=testnet
TALIM_EXCHANGE_NAME=ig              # or forexcom, binance
TALIM_PRICEFEED=ig                  # or forexcom, binance, mock
TALIM_PRICEFEED_TIMEFRAME=5m
TALIM_INSTRUMENTS=AU200.cash
TALIM_STRATEGIES=momentum-AU200
TALIM_DEFAULT_QTY=1
TALIM_CHECKPOINT_DB=/app/state/talim_checkpoints.db
TALIM_EPISODIC_DB=/app/state/episodic.db
TALIM_RISK_CONFIG=config/risk.json
```

For `testnet` or `live`, `TALIM_INSTRUMENTS` and `TALIM_STRATEGIES` are
required explicitly as a safety gate.

Before attempting broker demo execution, run the local mock proof:

```bash
./.venv/bin/python scripts/run_demo_execution.py --state-dir state/demo-execution
```

See [docs/live-demo-execution.md](../docs/live-demo-execution.md:1).
For OpenClaw/operator approval flow details, see
[docs/openclaw-operator-interface.md](../docs/openclaw-operator-interface.md:1).
For runtime broker-state reconciliation, see
[docs/runtime-sync.md](../docs/runtime-sync.md:1).

## IG AU CFD discovery

`IG` is now wired into `create_exchange()` as a first-party OTC CFD adapter. The broker-agnostic CFD work includes:

- canonical CFD registry in [config/cfd_instruments.json](../config/cfd_instruments.json:1)
- IG market discovery client in [ig_discovery.py](../talim/connectors/exchange/ig_discovery.py:1)
- IG exchange adapter in [ig_exchange.py](../talim/connectors/exchange/ig_exchange.py:1)
- IG price feed in [ig.py](../talim/connectors/pricefeed/ig.py:1)
- price-feed factory in [factory.py](../talim/connectors/pricefeed/factory.py:1)
- discovery CLI in [ig_market_discovery.py](../scripts/ig_market_discovery.py:1)
- ingestion CLI in [ingest_ig_prices.py](../scripts/ingest_ig_prices.py:1)

Set either login credentials or pre-issued session tokens in `.env`:

```env
IG_API_KEY=
IG_IDENTIFIER=
IG_PASSWORD=
IG_ENVIRONMENT=demo
```

Or using the demo-style env names already accepted by the loader:

```env
IG_DEMO_API_KEY=
IG_DEMO_LOGIN=
IG_DEMO_PASSWORD=
```

Create the adapter in demo mode:

```env
TALIM_EXCHANGE_MODE=testnet
TALIM_EXCHANGE_NAME=ig
IG_DEMO_API_KEY=...
IG_DEMO_LOGIN=...
IG_DEMO_PASSWORD=...
```

Use the IG price feed in the same environment:

```env
TALIM_PRICEFEED=ig
TALIM_PRICEFEED_TIMEFRAME=5m
```

Create the adapter in live mode:

```env
TALIM_EXCHANGE_MODE=live
TALIM_EXCHANGE_NAME=ig
IG_API_KEY=...
IG_IDENTIFIER=...
IG_PASSWORD=...
IG_ENVIRONMENT=live
```

Then discover the `Australia 200` market metadata:

```bash
./.venv/bin/python scripts/ig_market_discovery.py --canonical-id AU200.cash --json
```

See [docs/ig-cfd-feasibility.md](../docs/ig-cfd-feasibility.md:1) for the verification checklist before implementing the real IG exchange adapter.
See the same doc for the currently resolved demo epics (`IX.D.ASX.IFT.IP` and `IX.D.ASX.FWM2.IP`) and the remaining metadata gaps.

Fetch and persist recent AU200 bars:

```bash
./.venv/bin/python scripts/ingest_ig_prices.py --instrument AU200.cash --timeframe 5m --bars 200
```

Build the baseline AU200 backtest dataset within IG's default allowance:

```bash
./.venv/bin/python scripts/build_au200_dataset.py --profile backtest-baseline
```

See [docs/au200-demo-soak.md](../docs/au200-demo-soak.md:1) for the AU200 strategy runbook, allowance-aware dataset profiles, and soak checklist.

## FOREX.com AU CFD setup

`FOREX.com` is wired into the same broker-neutral CFD path as IG:

- FOREX.com discovery client in [forexcom_discovery.py](../talim/connectors/exchange/forexcom_discovery.py:1)
- FOREX.com exchange adapter in [forexcom_exchange.py](../talim/connectors/exchange/forexcom_exchange.py:1)
- FOREX.com price feed in [forexcom.py](../talim/connectors/pricefeed/forexcom.py:1)
- shared CFD conformance tests in [test_cfd_conformance.py](../tests/test_cfd_conformance.py:1)

Example demo configuration:

```env
TALIM_EXCHANGE_MODE=testnet
TALIM_EXCHANGE_NAME=forexcom
TALIM_PRICEFEED=forexcom
TALIM_PRICEFEED_TIMEFRAME=5m
FOREXDOTCOM_LOGIN=...
FOREXDOTCOM_PASSWORD=...
FOREXDOTCOM_APP_KEY=...
FOREXDOTCOM_ENVIRONMENT=demo
```

`FOREXDOTCOM_ENVIRONMENT` controls demo/live endpoint selection for this
adapter. See [docs/forexcom-cfd-feasibility.md](../docs/forexcom-cfd-feasibility.md:1) for the current AU200 market mapping and gap analysis.

## Setting up ccxt testnet credentials

### Binance Futures Testnet

1. Go to https://testnet.binancefuture.com
2. Log in with GitHub
3. Create an API key
4. Add to your `.env`:

```env
TALIM_EXCHANGE_MODE=testnet
TALIM_EXCHANGE_NAME=binance
BINANCE_API_KEY=your-testnet-api-key
BINANCE_API_SECRET=your-testnet-api-secret
```

### Bybit Testnet

1. Go to https://testnet.bybit.com
2. Create an account and API key
3. Add to your `.env`:

```env
TALIM_EXCHANGE_MODE=testnet
TALIM_EXCHANGE_NAME=bybit
BYBIT_API_KEY=your-testnet-api-key
BYBIT_API_SECRET=your-testnet-api-secret
```

## Going live

1. Create API keys on your chosen exchange with **trade** and **read** permissions only (no withdrawal)
2. Restrict IP access to your server's IP
3. Update `.env` for the selected venue. For the Binance ccxt path:

```env
TALIM_EXCHANGE_MODE=live
TALIM_EXCHANGE_NAME=binance
BINANCE_API_KEY=your-live-api-key
BINANCE_API_SECRET=your-live-api-secret
```

4. Set appropriate risk rules in `config/risk.json` for your account size
5. Restart the stack: `docker compose up -d`

For CFD venues, use `TALIM_EXCHANGE_NAME=ig` or `TALIM_EXCHANGE_NAME=forexcom`
and the venue-specific credentials above instead of Binance keys.

## How Binance ccxt credentials flow

```
.env → BINANCE_API_KEY / BINANCE_API_SECRET
  → Vault.load_from_env(["binance"])
    → vault._secrets["binance"] = secret (private, no getter)
    → vault.public("binance") = PublicCredential(api_key=...)
      → CcxtExchange.from_vault("binance", vault, sandbox=True/False)
        → ccxt.binance({apiKey: ..., secret: ...})
```

After `Vault.load_from_env()`, the raw secret is only accessible inside
the vault's `_secrets` dict. `CcxtExchange.from_vault` reads it once to
pass to ccxt's own request signer.

## Testnet soak checklist

Before switching to `live`, run on `testnet` for 2+ weeks and verify:

- [ ] Scanner fires signals at expected frequency
- [ ] Risk check blocks appropriately sized positions
- [ ] HITL approve/reject cycle works end-to-end
- [ ] Execute node places orders that appear on the exchange
- [ ] Reconciler reports no divergences after 24h
- [ ] Episodic memory records match exchange trade history
- [ ] Daily P&L tracker resets on session boundary
- [ ] Kill switch (`/talim/halt`) blocks new signals immediately
