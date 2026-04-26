# Strategy Activation Controls (WP-70)

Operators can enable or disable strategies on a running Talim deployment
without restarting the stack. This is useful when a strategy misbehaves,
when you want to dark-launch a new one, or when a broker outage makes a
particular instrument unsafe to trade.

## What changes when a strategy is enabled or disabled

- **`Runtime._active_strategies`** — the authoritative in-process list. Every
  `seed_state()` (used by `cron_trigger` and `bridge_message`) reads from it,
  so the very next scan respects the toggle.
- **Scanner registry** — `enable_strategy` loads the module via
  `load_strategy(name)` and registers the instance in the scanner's DI
  context. If the module fails to load, the runtime bails *before* mutating
  state and no audit row is written.
- **Checkpointed state** — the updated `active_strategies` list flows into
  the next graph invocation through `seed_state`. The scanner distinguishes
  `active_strategies = []` (disable everything) from a missing key (fall
  back to every loaded strategy).
- **Episodic audit** — every enable/disable is recorded in the
  `strategy_activations` table (`state/episodic.db`) with timestamp, actor,
  and a `notes` field (`noop` when the call was a no-op).

## Pending HITL signals are preserved

Disabling a strategy does **not** clear any `pending_signal` it produced. The
checkpointed thread still resolves through `/talim/resume` or
`/talim/operator/decision` exactly as before. New signals from that strategy
simply stop being produced.

This matters when you're shutting a strategy down mid-trade: the operator
can still approve or reject the signal that's already in flight.

## Operator endpoints

All endpoints require the shared-secret header (`X-Talim-Secret`).

- `GET /talim/operator/strategies` — returns
  `{"active": [...], "available": [...]}`. `available` is every strategy
  directory under `strategies/` with a `strategy.py` file, whether active
  or not.
- `POST /talim/operator/strategies/{name}/enable` — activates a strategy.
  Returns `404` when no `strategies/{name}/strategy.py` exists. Re-enabling
  an already-active strategy is a no-op but still produces an audit row.
- `POST /talim/operator/strategies/{name}/disable` — deactivates. Idempotent;
  disabling an already-inactive strategy is a no-op but audited.

## Persistence model

Toggles live for the lifetime of the Python process. Environment-driven
`TALIM_STRATEGIES` is the source of truth on boot; hot toggles do not
modify env. If you want a change to survive a restart, update
`TALIM_STRATEGIES` in your `.env`/compose file as well as toggling the
live runtime.

## Safe toggling during an open position

1. **Disable** the strategy via the operator endpoint — new scans will skip it.
2. Open positions opened by that strategy continue to be managed by
   `position_monitor` (which watches stops/targets regardless of whether
   the originating strategy is still active).
3. To fully wind down, close remaining positions through the normal
   exchange/broker path, or via a manual exit signal.
4. Leave the audit trail alone; it's how you reconstruct *why* a strategy
   was disabled when you review the session log later.

## Audit log shape

```
id | timestamp | strategy | action  | actor    | notes | created_at
---+-----------+----------+---------+----------+-------+------------
 1 | 2026-...  | momentum-US500 | disable | operator |      | 2026-...
 2 | 2026-...  | momentum-US500 | enable  | operator | noop | 2026-...
```

Query via `EpisodicMemory.query_activations(strategy=..., limit=...)` or
surface through the dashboard (WP-69 consumes these rows).
