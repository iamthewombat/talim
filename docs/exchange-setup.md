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
