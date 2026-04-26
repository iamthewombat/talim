# OpenClaw Secrets and Env Reference

This doc keeps the OpenClaw-side and Talim-side configuration aligned for the
same-host integration.

## What OpenClaw Must Know

OpenClaw only needs the minimum Talim client configuration:

- Talim base URL
- `TALIM_BRIDGE_SECRET`

Recommended default:

```text
Talim base URL: http://127.0.0.1:8080/talim
```

Use a private hostname or Tailscale URL only if OpenClaw cannot reach
`127.0.0.1` from its runtime environment.

## What Talim Must Know

For this integration, Talim must have:

- `TALIM_BRIDGE_SECRET`
- runtime selection envs
- IG demo envs for the first broker-backed milestone

Minimum runtime selection example:

```env
TALIM_EXCHANGE_MODE=testnet
TALIM_EXCHANGE_NAME=ig
TALIM_PRICEFEED=ig
TALIM_PRICEFEED_TIMEFRAME=5m
TALIM_INSTRUMENTS=AU200.cash
TALIM_STRATEGIES=momentum-AU200
TALIM_DEFAULT_QTY=1
TALIM_CHECKPOINT_DB=/app/state/talim_checkpoints.db
TALIM_EPISODIC_DB=/app/state/episodic.db
TALIM_RISK_CONFIG=config/risk.json
```

Accepted IG demo-style envs already documented in the repo:

```env
IG_DEMO_API_KEY=...
IG_DEMO_LOGIN=...
IG_DEMO_PASSWORD=...
IG_ENVIRONMENT=demo
```

The repo also documents the alternate credential form:

```env
IG_API_KEY=...
IG_IDENTIFIER=...
IG_PASSWORD=...
IG_ENVIRONMENT=demo
```

See [exchange-setup.md](exchange-setup.md) for the full venue matrix.

## Source Of Truth

Use this rule consistently:

- Talim `.env` is authoritative for Talim runtime behavior.
- OpenClaw stores only the minimum Talim client values it needs:
  - Talim base URL
  - `TALIM_BRIDGE_SECRET`

Do not duplicate Talim's broker runtime envs into OpenClaw unless OpenClaw
itself needs them for some unrelated feature.

## Secret Rotation

When rotating `TALIM_BRIDGE_SECRET`:

1. generate a new long random value
2. update Talim's `.env`
3. update OpenClaw's secret/config
4. restart or reload the affected services
5. verify:
   - `GET /talim/operator/status`
   - `POST /talim/sync?thread_id=cron-main`

If only one side is rotated, all authenticated OpenClaw ↔ Talim calls will
start failing with `401`.

## Automation Warning

Do not use the Talim dashboard's manual secret-paste flow for automation.

That flow is intended for a human browser session only. OpenClaw should send
the `X-Talim-Secret` header directly on every Talim API call.
