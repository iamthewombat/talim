# Authoring a Strategy

A Talim strategy is a Python class that consumes `OHLCVBar` objects one at a
time and returns `Signal` objects when entry/exit criteria are met. The same
class runs live and in backtest — there is no parallel implementation.

## Skeleton

```python
from talim.models.bar import OHLCVBar
from talim.models.signal import Signal
from talim.strategy.base import BaseStrategy
from talim.strategy.indicators import AtrStream, EmaStream, RsiStream


class MyStrategy(BaseStrategy):
    # Class-level defaults become the parameter set. load_params(dict)
    # overrides them at runtime.
    rsi_period: int = 14
    oversold: float = 30.0
    overbought: float = 70.0

    def __init__(self) -> None:
        self._init_indicators()

    def _init_indicators(self) -> None:
        self._rsi = RsiStream(self.rsi_period)
        self._atr = AtrStream(period=14)

    @property
    def name(self) -> str:
        return "my-strategy"   # must match the directory name in strategies/

    def reset(self) -> None:
        self._init_indicators()

    def load_params(self, params: dict) -> None:
        super().load_params(params)
        self._init_indicators()   # rebuild streams when periods change

    def on_bar(self, bar: OHLCVBar) -> Signal | None:
        atr = self._atr.update(bar.high, bar.low, bar.close)
        rsi = self._rsi.update(bar.close)
        if rsi is None:
            return None  # still warming up
        ...
        return Signal(...)
```

Place the class in `strategies/<name>/strategy.py` and add a short
`strategies/<name>/<name>.md` documenting the parameters and logic.

## Indicator library

`talim.strategy.indicators` provides the common building blocks. Use these
instead of hand-rolling math so every strategy gets the same numerical
behaviour and warm-up semantics:

| Indicator | Streaming class | Vectorised | Notes |
|---|---|---|---|
| EMA | `EmaStream(period)` | `ema(values, period)` | Seeds from first value; `k = 2/(period+1)` |
| SMA | `SmaStream(period)` | `sma(values, period)` | Returns `None` until window full |
| ATR (Wilder) | `AtrStream(period=14)` | `atr_wilder(highs, lows, closes, period)` | Matches the in-strategy ATR we've used since day one |
| RSI (Wilder) | `RsiStream(period=14)` | `rsi_wilder(values, period)` | Returns `None` until `period + 1` samples |
| Bollinger | `BollingerStream(period, num_std)` | `bollinger(values, period, num_std)` | Population std (divides by `n`) |
| MACD | `MacdStream(fast, slow, signal)` | `macd(values, fast, slow, signal)` | Three EMAs; no warm-up `None` |
| Stochastic | `StochasticStream(k_period, d_period)` | `stochastic(highs, lows, closes, k, d)` | %K 0..100, %D is the SMA of %K |
| Donchian | `DonchianStream(period)` | `donchian(highs, lows, period)` | Highest high / lowest low |

Every streaming class has the same shape:

```python
stream = EmaStream(period=10)
value = stream.update(bar.close)   # returns the new value (or None during warm-up)
stream.value                       # current value without re-consuming a bar
stream.reset()                     # clear state
```

The streaming and vectorised forms are held to bit-for-bit parity by tests
in `tests/test_indicators.py`. You can use the vectorised form for research
notebooks and trust that live bar-by-bar replay will produce the same
numbers.

## Parameter handling

- Declare parameters as class attributes with defaults and type hints.
- `BaseStrategy.load_params(dict)` sets attributes via `setattr`, so only
  names that exist on the class are honoured.
- If your strategy uses indicators with periods from parameters, **rebuild
  the streams** in `load_params` (see the skeleton above). Otherwise the
  stream keeps the period it was constructed with.

WP-72 will replace the freeform dict with a declarative schema. Until then,
validate ranges yourself if a param change could produce garbage.

## Signal shape

A `Signal` must have:

- `instrument` (usually `bar.instrument`)
- `strategy` (usually `self.name`)
- `side` (`"long"` or `"short"`)
- `entry_price` (typically `bar.close`)
- `stop`, `target` — price levels, usually sized off ATR
- `rationale` — short human string that will appear in the HITL prompt
- `regime_context` — short label if the strategy needs a regime gate,
  empty string otherwise
- `timestamp` — typically `bar.timestamp`

See `talim/models/signal.py` for the full dataclass.

## Testing

Add a class in `tests/test_strategy.py` covering:

- `test_generates_signals` on a price path that should trigger entries
- `test_signal_is_valid` that `Signal` fields are well-formed
- `test_no_signal_on_few_bars` verifies the warm-up guard
- `test_load_params` confirms parameter attributes are settable
- `test_reset` confirms state clears

The existing strategy tests are good templates.

## Backtesting

```bash
python scripts/run_backtest.py \
    --strategy my-strategy \
    --instrument US500.cash \
    --data-dir data/ig \
    --timeframe 5m \
    --params '{"rsi_period": 10}'
```

Put Parquet data under `data/<venue>/<instrument>/<timeframe>.parquet`. See
`docs/backtest-data-strategy.md` for the chosen data sources.
