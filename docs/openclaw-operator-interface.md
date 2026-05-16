# OpenClaw Operator Interface

WP-64 exposes a small authenticated HTTP contract for an external operator
client such as OpenClaw. It is intentionally narrower than the full bridge:
OpenClaw can inspect status, inspect a pending HITL signal, approve/reject it,
review current positions/recent decisions, and ask Talim to refresh broker
state through the WP-65 sync endpoint.

All endpoints require:

```http
X-Talim-Secret: <TALIM_BRIDGE_SECRET>
```

## Status

```http
GET /talim/operator/status
```

Returns runtime config and account shape:

```json
{
  "halted": false,
  "runtime": {
    "exchange_mode": "testnet",
    "exchange_name": "ig",
    "pricefeed_name": "ig",
    "pricefeed_timeframe": "5m",
    "instruments": ["AU200.cash"],
    "strategies": ["momentum-AU200"],
    "subscriptions": ["AU200.cash"],
    "pricefeed_connected": true,
    "default_qty": 1.0,
    "position_count": 0,
    "account_balance": 100000.0
  }
}
```

## Pending Signal

```http
GET /talim/operator/pending?thread_id=cron-main
```

Returns the current checkpointed HITL state for a graph thread:

```json
{
  "thread_id": "cron-main",
  "exists": true,
  "paused": true,
  "next_nodes": ["execute"],
  "signal_id": "SIG-ABC123DEF456",
  "dashboard_url": "http://127.0.0.1:8080/talim/dashboard/signal.html?signal=SIG-ABC123DEF456",
  "pending_signal": {
    "signal_id": "SIG-ABC123DEF456",
    "instrument": "AU200.cash",
    "strategy": "momentum-AU200",
    "side": "long",
    "entry_price": 7700.0,
    "stop": 7680.0,
    "target": 7740.0,
    "rationale": "..."
  },
  "pending_notification": "...",
  "signal_approved": null,
  "last_action": null
}
```

`paused=true` with a non-null `pending_signal` is the normal approval state.
When a pending signal exists, Talim records/updates a durable `signals` row,
returns its `signal_id` plus a dashboard deep link, and includes advisory
strategy validation status. In WP-77 this validation is indicative only; WP-78
will enforce it during approval.

## Signal Detail

```http
GET /talim/operator/signals/SIG-ABC123DEF456
```

Returns the durable signal lifecycle row, including original signal fields,
status, dashboard URL, latest validation fields when implemented, and stored
context from the HITL checkpoint.

## Approve Or Reject

```http
POST /talim/operator/decision
Content-Type: application/json

{
  "thread_id": "cron-main",
  "approved": true,
  "signal_id": "SIG-ABC123DEF456"
}
```

Approval first verifies the optional `signal_id` still matches the current
pending signal, refreshes broker state, runs strategy-specific signal
validation, and reruns risk checks. Only then does it resume the graph and
route to `execute`. If the id does not match, Talim refuses the decision and
leaves the current pending signal untouched. If validation or risk blocks the
signal, Talim records the refusal, clears the pending signal, and returns a
blocking reason without placing an order. Rejection clears the pending signal
and routes to notification without placing an order.

Response:

```json
{
  "thread_id": "cron-main",
  "approved": true,
  "pending_signal_cleared": true,
  "last_action": "executed enter long AU200.cash (momentum-AU200)"
}
```

## Positions

```http
GET /talim/operator/positions
```

Returns broker positions normalised to Talim's `Position` shape.

For a fresh broker snapshot before rendering account state, call:

```http
POST /talim/sync?thread_id=cron-main
```

Sync refreshes positions/P&L and runs reconciliation. It returns
`state_updated=false` when the thread is paused at HITL, which is intentional:
scheduled/operator sync must not disturb a pending approval decision.

## Integration Usage Pattern

For the first same-host OpenClaw integration, use `thread_id=cron-main` as the
only approval thread and follow this request sequence:

1. `GET /talim/operator/status`
2. `POST /talim/sync?thread_id=cron-main`
3. `GET /talim/operator/pending?thread_id=cron-main`
4. `GET /talim/operator/positions`
5. `GET /talim/operator/decisions?limit=20`

Rules:

- OpenClaw should call `/talim/sync` before rendering account state if it
  needs a fresh snapshot.
- OpenClaw should treat `/talim/operator/pending` as the approval source of
  truth.
- OpenClaw should use `/talim/operator/decision` only for `thread_id=cron-main`
  in v1 unless you intentionally add multi-thread HITL behavior later.

## Recent Decisions

```http
GET /talim/operator/decisions?limit=20&instrument=AU200.cash&strategy=momentum-AU200
```

Returns episodic decisions newest first. `limit` is clamped to `1..200`.

## Local Proof

Before wiring OpenClaw to real demo credentials, run:

```bash
./.venv/bin/python scripts/run_demo_execution.py --state-dir state/demo-execution
```

That validates the same scan -> HITL -> approve -> execute -> memory ->
reconcile path against `MockExchange`.
