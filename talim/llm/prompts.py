"""Prompt templates for Talim's LLM-powered nodes (WP-13).

Each function returns a fully rendered string. Templates are intentionally
small and explicit so future tweaks can be diffed cleanly.
"""

from __future__ import annotations

from typing import Any


def strategy_reasoning_prompt(
    strategy_name: str,
    current_params: dict,
    regime: str,
    backtest_results: list[dict] | None = None,
) -> str:
    """Ask the LLM to propose updated parameters for a strategy."""
    bt_section = ""
    if backtest_results:
        lines = []
        for i, r in enumerate(backtest_results, 1):
            lines.append(
                f"  variant {i}: params={r.get('param_variant', {})} "
                f"sharpe={r.get('sharpe_ratio', 0):.2f} "
                f"net_pnl={r.get('net_pnl', 0):.2f} "
                f"win_rate={r.get('win_rate', 0):.2f}"
            )
        bt_section = "\n\nBacktest results (sorted best first):\n" + "\n".join(lines)

    return (
        f"You are tuning the trading strategy '{strategy_name}'.\n"
        f"Current regime: {regime}\n"
        f"Current parameters: {current_params}{bt_section}\n\n"
        "Propose adjusted parameters for the current regime. Respond with a "
        "single JSON object containing only the parameters to change, plus a "
        "short 'rationale' field explaining the change."
    )


def backtest_interpretation_prompt(results: list[dict]) -> str:
    """Ask the LLM to summarise a set of backtest results in plain English."""
    rows = "\n".join(
        f"  - params={r.get('param_variant', {})} sharpe={r.get('sharpe_ratio', 0):.2f} "
        f"net={r.get('net_pnl', 0):.2f} dd={r.get('max_drawdown', 0):.2f} "
        f"trades={r.get('total_trades', 0)}"
        for r in results
    )
    return (
        "Interpret these backtest results for a trader. Highlight the best "
        "variant, any concerning drawdowns, and whether the differences look "
        "statistically meaningful given the trade count.\n\n"
        f"Results:\n{rows}"
    )


def regime_observation_prompt(
    regime: str,
    fingerprint: list[float],
    atr_ratio: float,
    prior_regime: str | None = None,
) -> str:
    """Ask the LLM to write a one-paragraph observation about the regime."""
    transition = (
        f"Previous regime was '{prior_regime}'. " if prior_regime else ""
    )
    fp = ", ".join(f"{x:.2f}" for x in fingerprint)
    return (
        f"{transition}The detected regime is '{regime}'.\n"
        f"Fingerprint (ADX, ATR ratio, trend, vol, vol_ratio, momentum): [{fp}]\n"
        f"ATR ratio (current/avg): {atr_ratio:.2f}\n\n"
        "Write one short paragraph (3 sentences max) observing what this "
        "means for active strategies."
    )


def message_classification_prompt(message: str) -> str:
    """Classify a user message into one of: question, command, backtest, other."""
    return (
        "Classify the following trader message into exactly one category: "
        "QUESTION, COMMAND, BACKTEST, OTHER. Respond with only the category "
        "label.\n\n"
        f"Message: {message!r}"
    )


def render(template: str, **kwargs: Any) -> str:
    """Generic template renderer for ad-hoc prompts (str.format under the hood)."""
    return template.format(**kwargs)
