# Live Demo Execution Harness

WP-63 adds a repeatable execution harness for proving the runtime path before
real broker demo orders are attempted.

## Local Mock Proof

Run the deterministic mock harness:

```bash
./.venv/bin/python scripts/run_demo_execution.py --state-dir state/demo-execution
```

The harness performs:

1. Bootstrap Talim through `talim.app.runtime.bootstrap_runtime`.
2. Load deterministic bars into `MockPriceFeed`.
3. Trigger the graph scanner.
4. Confirm the graph pauses at HITL with a pending signal.
5. Approve the signal through the same resume path used by the bridge.
6. Execute the order through `MockExchange`.
7. Confirm episodic memory recorded the approved decision.
8. Reconcile exchange positions against memory and state.

Expected result shape:

```json
{
  "decision_count": 1,
  "order_count": 1,
  "position_count": 1,
  "reconcile_divergences": 0
}
```

## IG / FOREX.com Demo Progression

Do not jump from this mock harness directly to live trading. Use this order:

1. Run the local mock harness and confirm zero reconciliation divergences.
2. Configure one broker demo venue only.
3. Confirm broker auth and price-feed polling.
4. Run the CFD soak checklist in `docs/cfd-soak-runbook.md`.
5. Place the smallest permitted demo order after HITL approval.
6. Confirm the broker position appears through `get_positions`.
7. Confirm episodic memory has the matching approved decision.
8. Run reconciliation and require zero divergences before any longer soak.

Example IG demo runtime config:

```env
TALIM_EXCHANGE_MODE=testnet
TALIM_EXCHANGE_NAME=ig
TALIM_PRICEFEED=ig
TALIM_PRICEFEED_TIMEFRAME=5m
TALIM_INSTRUMENTS=AU200.cash
TALIM_STRATEGIES=momentum-AU200
TALIM_DEFAULT_QTY=1
```

Example FOREX.com demo runtime config:

```env
TALIM_EXCHANGE_MODE=testnet
TALIM_EXCHANGE_NAME=forexcom
TALIM_PRICEFEED=forexcom
TALIM_PRICEFEED_TIMEFRAME=5m
TALIM_INSTRUMENTS=AU200.cash
TALIM_STRATEGIES=momentum-AU200
TALIM_DEFAULT_QTY=1
```

## Remaining Limitations

- The harness is automated for `mock` only. Real broker demo execution remains a
  controlled manual step because it can place actual demo orders.
- Broker-side protective stops/targets are now propagated on supported adapter
  payloads; validate the first demo order in the broker UI before leaving any
  soak unattended.
- Reconciliation is scheduled through `/talim/sync`, but operator review is
  still required for any non-zero reconciliation divergence.
