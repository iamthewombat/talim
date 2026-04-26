"""Tests for the shared indicator library."""

from __future__ import annotations

import math

import pytest

from talim.strategy.indicators import (
    AtrStream,
    BollingerStream,
    DonchianStream,
    EmaStream,
    MacdStream,
    RsiStream,
    SmaStream,
    StochasticStream,
    atr_wilder,
    bollinger,
    donchian,
    ema,
    macd,
    rsi_wilder,
    sma,
    stochastic,
)


# ---------------------------------------------------------------------------
# EMA
# ---------------------------------------------------------------------------


def test_ema_seeds_from_first_value():
    values = [10.0, 11.0, 12.0, 13.0, 14.0]
    out = ema(values, period=3)
    assert out[0] == 10.0
    # k = 2 / (3+1) = 0.5
    assert out[1] == pytest.approx(0.5 * 11.0 + 0.5 * 10.0)
    assert out[2] == pytest.approx(0.5 * 12.0 + 0.5 * out[1])


def test_ema_stream_parity_with_vectorised():
    values = [100.0, 101.5, 102.0, 99.0, 98.5, 101.0, 103.0, 104.5]
    period = 5
    stream = EmaStream(period)
    streamed = [stream.update(v) for v in values]
    assert streamed == pytest.approx(ema(values, period))


def test_ema_rejects_zero_period():
    with pytest.raises(ValueError):
        EmaStream(0)
    with pytest.raises(ValueError):
        ema([1.0], 0)


def test_ema_reset_clears_state():
    stream = EmaStream(3)
    stream.update(10.0)
    stream.update(20.0)
    stream.reset()
    assert stream.value is None
    assert stream.update(5.0) == 5.0


# ---------------------------------------------------------------------------
# SMA
# ---------------------------------------------------------------------------


def test_sma_returns_none_during_warmup():
    out = sma([1.0, 2.0, 3.0, 4.0], period=3)
    assert out[0] is None
    assert out[1] is None
    assert out[2] == pytest.approx(2.0)
    assert out[3] == pytest.approx(3.0)


def test_sma_stream_parity_with_vectorised():
    values = [5.0, 6.0, 7.0, 8.0, 9.0, 10.0, 11.0]
    period = 4
    stream = SmaStream(period)
    streamed = [stream.update(v) for v in values]
    assert streamed == sma(values, period)


def test_sma_reset_clears_state():
    stream = SmaStream(3)
    stream.update(1.0)
    stream.update(2.0)
    stream.reset()
    assert stream.update(10.0) is None


# ---------------------------------------------------------------------------
# ATR (Wilder / RMA)
# ---------------------------------------------------------------------------


def test_atr_wilder_seeds_from_first_tr():
    highs = [110.0, 112.0, 111.0]
    lows = [100.0, 105.0, 104.0]
    closes = [105.0, 108.0, 107.0]
    out = atr_wilder(highs, lows, closes, period=14)
    # First TR = 110 - 100 = 10
    assert out[0] == pytest.approx(10.0)
    # Second TR = max(112-105, |112-105|, |105-105|) = 7
    # atr = 7 * (1/14) + 10 * (13/14)
    assert out[1] == pytest.approx(7.0 / 14 + 10.0 * 13 / 14)


def test_atr_stream_parity_with_vectorised():
    highs = [110.0, 112.0, 111.0, 113.5, 114.0, 112.0]
    lows = [100.0, 105.0, 104.0, 108.0, 109.5, 106.0]
    closes = [105.0, 108.0, 107.0, 112.0, 110.0, 108.0]
    period = 14
    stream = AtrStream(period)
    streamed = [stream.update(h, lo, c) for h, lo, c in zip(highs, lows, closes)]
    assert streamed == pytest.approx(atr_wilder(highs, lows, closes, period))


def test_atr_matches_legacy_strategy_computation():
    """Reproduces the inline ATR math that existed in momentum-US500 before WP-71."""

    def _legacy(h: float, lo: float, prev_close: float | None, prev_atr: float) -> float:
        tr = (
            h - lo
            if prev_close is None
            else max(h - lo, abs(h - prev_close), abs(lo - prev_close))
        )
        period = 14
        if prev_atr == 0.0:
            return tr
        k = 1.0 / period
        return tr * k + prev_atr * (1 - k)

    highs = [110.0, 112.0, 111.0, 113.5, 114.0, 112.0]
    lows = [100.0, 105.0, 104.0, 108.0, 109.5, 106.0]
    closes = [105.0, 108.0, 107.0, 112.0, 110.0, 108.0]

    legacy_out: list[float] = []
    atr = 0.0
    prev_close: float | None = None
    for h, lo, c in zip(highs, lows, closes):
        atr = _legacy(h, lo, prev_close, atr)
        legacy_out.append(atr)
        prev_close = c

    stream = AtrStream(14)
    streamed = [stream.update(h, lo, c) for h, lo, c in zip(highs, lows, closes)]
    assert streamed == pytest.approx(legacy_out)


def test_atr_rejects_mismatched_lengths():
    with pytest.raises(ValueError):
        atr_wilder([1.0, 2.0], [1.0], [1.0, 2.0], period=14)


# ---------------------------------------------------------------------------
# RSI (Wilder)
# ---------------------------------------------------------------------------


def test_rsi_all_gains_returns_100():
    values = [float(i) for i in range(1, 20)]
    out = rsi_wilder(values, period=14)
    assert out[14] == pytest.approx(100.0)


def test_rsi_no_movement_returns_50():
    values = [100.0] * 20
    out = rsi_wilder(values, period=14)
    assert out[14] == pytest.approx(50.0)


def test_rsi_warmup_returns_none():
    out = rsi_wilder([1.0, 2.0, 3.0], period=14)
    assert all(v is None for v in out)


def test_rsi_stream_parity_with_vectorised():
    values = [
        100.0, 101.0, 99.5, 102.0, 103.5, 101.5, 100.0, 99.0,
        98.5, 100.0, 101.5, 103.0, 104.5, 103.5, 102.0, 100.5,
        99.0, 101.0, 103.0, 105.0,
    ]
    period = 14
    stream = RsiStream(period)
    streamed = [stream.update(v) for v in values]
    vectorised = rsi_wilder(values, period)
    for s, v in zip(streamed, vectorised):
        if v is None:
            assert s is None
        else:
            assert s == pytest.approx(v)


def test_rsi_bounded_0_to_100():
    values = [100.0, 95.0, 90.0, 85.0, 80.0, 75.0] * 5
    out = rsi_wilder(values, period=14)
    for v in out:
        if v is not None:
            assert 0.0 <= v <= 100.0


# ---------------------------------------------------------------------------
# Bollinger Bands
# ---------------------------------------------------------------------------


def test_bollinger_known_values():
    values = [float(i) for i in range(1, 21)]  # 1..20
    out = bollinger(values, period=20, num_std=2.0)
    # First 19 entries are warm-up
    assert all(v is None for v in out[:19])
    band = out[19]
    assert band is not None
    assert band.middle == pytest.approx(10.5)
    # Population variance of 1..20 is 33.25 (sum of (x-10.5)^2 / 20)
    expected_std = math.sqrt(33.25)
    assert band.upper == pytest.approx(10.5 + 2 * expected_std)
    assert band.lower == pytest.approx(10.5 - 2 * expected_std)


def test_bollinger_stream_parity_with_vectorised():
    values = [100.0, 102.0, 98.0, 101.5, 99.0, 103.0, 97.5, 100.5, 101.0, 102.5]
    period = 5
    stream = BollingerStream(period, num_std=2.0)
    streamed = [stream.update(v) for v in values]
    vectorised = bollinger(values, period, num_std=2.0)
    for s, v in zip(streamed, vectorised):
        if v is None:
            assert s is None
        else:
            assert s.middle == pytest.approx(v.middle)
            assert s.upper == pytest.approx(v.upper)
            assert s.lower == pytest.approx(v.lower)


# ---------------------------------------------------------------------------
# MACD
# ---------------------------------------------------------------------------


def test_macd_stream_parity_with_vectorised():
    values = [100.0 + (i % 7) * 0.5 for i in range(30)]
    stream = MacdStream(fast_period=12, slow_period=26, signal_period=9)
    streamed = [stream.update(v) for v in values]
    vectorised = macd(values, fast_period=12, slow_period=26, signal_period=9)
    for s, v in zip(streamed, vectorised):
        assert s.macd == pytest.approx(v.macd)
        assert s.signal == pytest.approx(v.signal)
        assert s.histogram == pytest.approx(v.histogram)


def test_macd_histogram_equals_macd_minus_signal():
    values = [100.0 + i for i in range(30)]
    out = macd(values)
    for v in out:
        assert v.histogram == pytest.approx(v.macd - v.signal)


# ---------------------------------------------------------------------------
# Stochastic
# ---------------------------------------------------------------------------


def test_stochastic_at_window_low_is_zero():
    highs = [10.0] * 14
    lows = [5.0] * 14
    closes = [5.0] * 14
    out = stochastic(highs, lows, closes, k_period=14, d_period=3)
    assert out[-1] is not None
    assert out[-1].k == pytest.approx(0.0)


def test_stochastic_at_window_high_is_100():
    highs = [10.0] * 14
    lows = [5.0] * 14
    closes = [10.0] * 14
    out = stochastic(highs, lows, closes, k_period=14, d_period=3)
    assert out[-1] is not None
    assert out[-1].k == pytest.approx(100.0)


def test_stochastic_stream_parity_with_vectorised():
    highs = [10.0 + (i % 5) for i in range(20)]
    lows = [5.0 + (i % 5) for i in range(20)]
    closes = [7.5 + (i % 5) for i in range(20)]
    stream = StochasticStream(k_period=5, d_period=3)
    streamed = [stream.update(h, lo, c) for h, lo, c in zip(highs, lows, closes)]
    vectorised = stochastic(highs, lows, closes, k_period=5, d_period=3)
    for s, v in zip(streamed, vectorised):
        if v is None:
            assert s is None
        else:
            assert s.k == pytest.approx(v.k)
            if v.d is None:
                assert s.d is None
            else:
                assert s.d == pytest.approx(v.d)


# ---------------------------------------------------------------------------
# Donchian
# ---------------------------------------------------------------------------


def test_donchian_tracks_window_extremes():
    highs = [10.0, 11.0, 12.0, 13.0, 14.0]
    lows = [5.0, 6.0, 5.5, 4.5, 5.0]
    out = donchian(highs, lows, period=3)
    assert out[0] is None
    assert out[1] is None
    assert out[2].upper == 12.0
    assert out[2].lower == 5.0
    assert out[2].middle == 8.5
    assert out[4].upper == 14.0
    assert out[4].lower == 4.5


def test_donchian_stream_parity_with_vectorised():
    highs = [10.0, 11.0, 12.0, 13.0, 14.0, 12.5, 11.5]
    lows = [5.0, 6.0, 5.5, 4.5, 5.0, 5.5, 6.0]
    period = 3
    stream = DonchianStream(period)
    streamed = [stream.update(h, lo) for h, lo in zip(highs, lows)]
    vectorised = donchian(highs, lows, period)
    for s, v in zip(streamed, vectorised):
        if v is None:
            assert s is None
        else:
            assert s.upper == v.upper
            assert s.lower == v.lower
            assert s.middle == v.middle
