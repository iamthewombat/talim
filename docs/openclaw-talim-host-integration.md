# OpenClaw + Talim Host Integration

Use this doc first when moving Talim onto the same host as an already-running
OpenClaw instance.

This is the intended topology for the first integrated deployment:

- `OpenClaw` is the operator-facing interface layer.
- `Talim` is the trading runtime, broker adapter layer, and stateful operator
  API.
- `nginx` fronts Talim at `/talim/*`.
- `scheduler` continues to drive `/talim/trigger` and `/talim/sync`.
- `redis` and the SQLite state files remain Talim internals.

This guide does not replace the lower-level source docs:

- API contract: [openclaw-operator-interface.md](openclaw-operator-interface.md)
- Runtime sync behavior: [runtime-sync.md](runtime-sync.md)
- Dashboard fallback: [operator-dashboard.md](operator-dashboard.md)
- Talim host migration mechanics: [vps-migration.md](vps-migration.md)
- Venue/runtime envs: [exchange-setup.md](exchange-setup.md)

## Target Network Path

For a same-host deployment, OpenClaw should call Talim through nginx, not the
raw FastAPI port.

Preferred base URL:

```text
http://127.0.0.1:8080/talim
```

Use a private hostname or Tailscale address only if OpenClaw cannot reach
localhost from its own runtime context:

```text
http://<private-hostname>:8080/talim
```

Do not use a public internet URL for this phase.

## Auth Contract

OpenClaw must send the shared bridge secret on every Talim API call:

```http
X-Talim-Secret: <TALIM_BRIDGE_SECRET>
```

Rules:

- `TALIM_BRIDGE_SECRET` must be identical in Talim and OpenClaw.
- OpenClaw should store only the Talim base URL and this secret for the Talim
  integration.
- Do not rely on the dashboard's manual secret-paste flow for automation.

See [openclaw-secrets-and-env.md](openclaw-secrets-and-env.md).

## Responsibilities

Keep the ownership split explicit:

- `Talim` owns:
  - the trading runtime
  - exchange and price-feed adapters
  - cron-driven scan/sync scheduling
  - positions, decisions, checkpoints, reconciliation, and risk rules
  - the authenticated operator API under `/talim/operator/*`
- `OpenClaw` owns:
  - operator UX
  - action routing and presentation
  - calling Talim's API with the correct auth header
  - deciding when to show status, pending approvals, positions, and history

OpenClaw should not replace Talim's scheduler in v1.

## First Integrated Milestone

### 1. Move Talim to the host

Follow [vps-migration.md](vps-migration.md) to copy the repo, `.env`, and
state directories onto the OpenClaw host.

Bring up Talim first in `mock` mode so the integration can be proven without a
broker:

```env
TALIM_EXCHANGE_MODE=mock
TALIM_EXCHANGE_NAME=
TALIM_PRICEFEED=mock
TALIM_INSTRUMENTS=US500.cash
TALIM_STRATEGIES=momentum-US500
```

Then start the stack:

```bash
docker compose up -d --build
docker compose ps
```

### 2. Verify Talim locally

From the host:

```bash
curl -fsS http://127.0.0.1:8080/talim/health
curl -fsS http://127.0.0.1:8080/talim/halt-status
curl -fsS -H "X-Talim-Secret: $TALIM_BRIDGE_SECRET" \
  http://127.0.0.1:8080/talim/operator/status
```

If these fail, stop here and fix Talim before wiring OpenClaw.

### 3. Point OpenClaw at Talim

Configure OpenClaw with:

- Talim base URL: `http://127.0.0.1:8080/talim`
- Talim secret: `TALIM_BRIDGE_SECRET`

OpenClaw's first useful integration flow should be:

1. `GET /talim/operator/status`
2. `POST /talim/sync?thread_id=cron-main`
3. `GET /talim/operator/pending?thread_id=cron-main`
4. `GET /talim/operator/positions`
5. `GET /talim/operator/decisions?limit=20`

Write actions for v1:

- approve/reject: `POST /talim/operator/decision`
- optional halt/resume: `POST /talim/halt`, `POST /talim/resume-trading`
- optional strategy toggles:
  - `POST /talim/operator/strategies/{name}/enable`
  - `POST /talim/operator/strategies/{name}/disable`
- optional backtest visibility:
  - `GET /talim/operator/backtests`
  - `GET /talim/operator/backtests/{run_id}`

### 4. Prove the mock HITL flow

OpenClaw should be able to:

1. read runtime status
2. request a fresh broker/runtime snapshot with `/talim/sync`
3. detect a pending HITL signal from `/talim/operator/pending`
4. approve or reject with `/talim/operator/decision`
5. observe updated positions and decisions afterwards

If you want a local proof before touching the live runtime, run:

```bash
./.venv/bin/python scripts/run_demo_execution.py --state-dir state/demo-execution
```

### 5. Switch Talim to IG demo

Once the mock flow works through OpenClaw, change Talim to IG demo:

```env
TALIM_EXCHANGE_MODE=testnet
TALIM_EXCHANGE_NAME=ig
TALIM_PRICEFEED=ig
TALIM_PRICEFEED_TIMEFRAME=5m
TALIM_INSTRUMENTS=AU200.cash
TALIM_STRATEGIES=momentum-AU200
TALIM_DEFAULT_QTY=1
```

Use one of the IG credential styles already accepted by the repo. The most
explicit demo form is:

```env
IG_DEMO_API_KEY=...
IG_DEMO_LOGIN=...
IG_DEMO_PASSWORD=...
IG_ENVIRONMENT=demo
```

See [exchange-setup.md](exchange-setup.md) for the full matrix.

### 6. Validate one small protected demo order

Before leaving the stack unattended:

1. confirm IG auth works on the host
2. confirm the feed connects
3. approve one smallest permitted demo trade from OpenClaw
4. confirm the broker shows the attached protection
5. confirm `/talim/operator/positions` and `/talim/operator/decisions` reflect it
6. call `/talim/sync?thread_id=cron-main` and require no unexplained drift

## Fallback Operator Path

Keep Talim's built-in dashboard available on the host:

```text
http://127.0.0.1:8080/talim/dashboard/
```

Use it as:

- a fallback manual operator console
- a parity check while wiring OpenClaw
- a debugging surface if OpenClaw and Talim disagree

OpenClaw-native flow is still the preferred routine path.

## What Not To Change In V1

- Do not move scheduling out of Talim.
- Do not expose Talim or OpenClaw publicly.
- Do not bypass nginx and point OpenClaw at Talim's raw `:8000`.
- Do not add multi-thread HITL behavior in OpenClaw yet; use
  `thread_id=cron-main` for the first integrated flow.

## Next Doc

When you are ready to perform the host move, use
[openclaw-host-cutover-checklist.md](openclaw-host-cutover-checklist.md).
