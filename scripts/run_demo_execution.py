#!/usr/bin/env python3
"""Run the deterministic Talim demo execution harness and print JSON."""

from __future__ import annotations

import argparse
import json

from talim.app.demo_harness import run_mock_demo_execution


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-dir", default="state/demo-execution")
    parser.add_argument("--thread-id", default="demo-exec-1")
    parser.add_argument("--instrument", default="ES")
    parser.add_argument("--strategy", default="momentum-US500")
    parser.add_argument("--qty", type=float, default=1.0)
    parser.add_argument("--bar-window", type=int, default=80)
    return parser


def main() -> int:
    args = _parser().parse_args()
    result = run_mock_demo_execution(
        state_dir=args.state_dir,
        thread_id=args.thread_id,
        instrument=args.instrument,
        strategy=args.strategy,
        qty=args.qty,
        bar_window=args.bar_window,
    )
    print(json.dumps(result.to_dict(), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
