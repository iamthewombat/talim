# Exchange Setup

Talim supports three exchange modes via `TALIM_EXCHANGE_MODE`:

| Mode | What it does | Credentials needed? |
|------|-------------|---------------------|
| `mock` (default) | In-memory `MockExchange` — instant fills, no network | No |
| `testnet` | Real ccxt exchange in sandbox/paper mode | Yes |
| `live` | Real ccxt exchange against production | Yes |

## Supported exchanges

Any exchange supported by [ccxt](https://github.com/ccxt/ccxt). Tested with:

- **Binance** (futures testnet available)
- **Bybit** (testnet available)
- **IG AU** (custom OTC CFD adapter, demo/live auth supported)

## IG AU CFD discovery

`IG` is now wired into `create_exchange()` as a first-party OTC CFD adapter. The broker-agnostic CFD work includes:

- canonical CFD registry in [config/cfd_instruments.json](/Users/justinluu/code/paige/talim/config/cfd_instruments.json:1)
- IG market discovery client in [ig_discovery.py](/Users/justinluu/code/paige/talim/talim/connectors/exchange/ig_discovery.py:1)
- IG exchange adapter in [ig_exchange.py](/Users/justinluu/code/paige/talim/talim/connectors/exchange/ig_exchange.py:1)
- IG price feed in [ig.py](/Users/justinluu/code/paige/talim/talim/connectors/pricefeed/ig.py:1)
- price-feed factory in [factory.py](/Users/justinluu/code/paige/talim/talim/connectors/pricefeed/factory.py:1)
- discovery CLI in [ig_market_discovery.py](/Users/justinluu/code/paige/talim/scripts/ig_market_discovery.py:1)
- ingestion CLI in [ingest_ig_prices.py](/Users/justinluu/code/paige/talim/scripts/ingest_ig_prices.py:1)

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

See [docs/ig-cfd-feasibility.md](/Users/justinluu/code/paige/talim/docs/ig-cfd-feasibility.md:1) for the verification checklist before implementing the real IG exchange adapter.
See the same doc for the currently resolved demo epics (`IX.D.ASX.IFT.IP` and `IX.D.ASX.FWM2.IP`) and the remaining metadata gaps.

Fetch and persist recent AU200 bars:

```bash
./.venv/bin/python scripts/ingest_ig_prices.py --instrument AU200.cash --timeframe 5m --bars 200
```

Build the baseline AU200 backtest dataset within IG's default allowance:

```bash
./.venv/bin/python scripts/build_au200_dataset.py --profile backtest-baseline
```

See [docs/au200-demo-soak.md](/Users/justinluu/code/paige/talim/docs/au200-demo-soak.md:1) for the AU200 strategy runbook, allowance-aware dataset profiles, and soak checklist.

## Setting up testnet credentials

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
3. Update `.env`:

```env
TALIM_EXCHANGE_MODE=live
TALIM_EXCHANGE_NAME=binance
BINANCE_API_KEY=your-live-api-key
BINANCE_API_SECRET=your-live-api-secret
```

4. Set appropriate risk rules in `config/risk.json` for your account size
5. Restart the stack: `docker compose up -d`

## How credentials flow

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
