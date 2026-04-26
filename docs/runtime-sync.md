# Runtime Sync and Reconciliation

WP-65 adds a small authenticated maintenance path for keeping Talim's runtime
state aligned with the broker after the graph has started.

## Endpoint

```http
POST /talim/sync?thread_id=cron-main
X-Talim-Secret: <shared secret>
```

The endpoint is intended for the scheduler and for operator clients such as
OpenClaw. It is separate from `/talim/trigger`: trigger scans for new signals,
whereas sync only refreshes existing broker/runtime state.

## What It Does

- Pulls current broker positions through the configured `BaseExchange`.
- Refreshes P&L through the persistent runtime `PnLTracker`.
- Runs reconciliation against episodic memory and the checkpointed graph state.
- Persists `active_positions`, `account_balance`, `open_pnl`, `daily_pnl`, and
  `last_action` into the requested thread checkpoint.
- Writes `pending_notification` when reconciliation finds divergences.
- Skips checkpoint updates when the thread is paused at HITL, so a scheduled
  sync cannot alter a pending approval/rejection flow.

## Response Shape

```json
{
  "thread_id": "cron-main",
  "snapshot_exists": true,
  "paused": false,
  "next_nodes": [],
  "state_updated": true,
  "position_count": 1,
  "positions": [
    {
      "instrument": "AU200.cash",
      "side": "long",
      "qty": 1.0,
      "entry_price": 9000.0,
      "stop": 8950.0,
      "target": 9075.0,
      "strategy": "momentum-AU200",
      "open_pnl": 0.0
    }
  ],
  "pnl": {
    "open_pnl": 0.0,
    "daily_pnl": 0.0,
    "account_balance": 95000.0,
    "position_count": 1,
    "timestamp": "2026-04-18T04:00:00+00:00"
  },
  "repair_count": 0,
  "repairs": [],
  "pending_notification": null
}
```

## Scheduler Cadence

`scripts/cron.txt` runs:

- `/talim/trigger` every five minutes on weekdays.
- `/talim/sync?thread_id=cron-main` every five minutes, offset by one minute.

That gives the scanner first chance to produce a HITL signal, then lets sync
refresh broker state shortly afterwards. If the scan has paused at HITL, sync
returns `state_updated=false` and leaves the checkpoint untouched.

## Operator Guidance

OpenClaw should call `/talim/sync` before showing account state if it needs a
fresh broker snapshot. For approving/rejecting a trade, use the operator HITL
endpoints documented in [openclaw-operator-interface.md](openclaw-operator-interface.md).
