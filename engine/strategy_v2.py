
from typing import Any


EMA_FAST = 20
EMA_SLOW = 50
RSI_PERIOD = 14
MIN_CANDLES_M1 = 70
MIN_CANDLES_M5 = 70
BODY_RATIO_MIN = 0.60
RSI_CALL_MIN = 52.0
RSI_PUT_MAX = 48.0


def ema(values: list[float], period: int) -> list[float]:
    if len(values) < period:
        return []

    multiplier = 2 / (period + 1)
    result = [sum(values[:period]) / period]

    for value in values[period:]:
        result.append(
            (value - result[-1]) * multiplier + result[-1]
        )

    return [float("nan")] * (period - 1) + result


def rsi(values: list[float], period: int = RSI_PERIOD) -> list[float]:
    if len(values) <= period:
        return []

    gains = []
    losses = []

    for i in range(1, len(values)):
        change = values[i] - values[i - 1]
        gains.append(max(change, 0.0))
        losses.append(max(-change, 0.0))

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    result = [float("nan")] * period

    def calculate_rsi(gain: float, loss: float) -> float:
        if loss == 0:
            return 100.0 if gain > 0 else 50.0
        return 100.0 - (100.0 / (1.0 + gain / loss))

    result.append(calculate_rsi(avg_gain, avg_loss))

    for i in range(period, len(gains)):
        avg_gain = (
            avg_gain * (period - 1) + gains[i]
        ) / period
        avg_loss = (
            avg_loss * (period - 1) + losses[i]
        ) / period
        result.append(calculate_rsi(avg_gain, avg_loss))

    return result


def _valid_candle(candle: dict[str, Any]) -> bool:
    try:
        values = [
            float(candle["open"]),
            float(candle["high"]),
            float(candle["low"]),
            float(candle["close"]),
        ]
        return (
            all(value == value for value in values)
            and values[1] >= values[2]
            and values[1] >= max(values[0], values[3])
            and values[2] <= min(values[0], values[3])
        )
    except (KeyError, TypeError, ValueError):
        return False


def generate_strategy_v2(
    candles_m1: list[dict[str, Any]],
    candles_m5: list[dict[str, Any]],
) -> dict[str, Any]:
    """Generate a test-only M5-trend / M1-entry signal.

    Pass only fully closed candles, ordered oldest to newest.
    """

    if len(candles_m1) < MIN_CANDLES_M1:
        return {
            "signal": "NO SIGNAL",
            "reason": "At least 70 closed M1 candles are required.",
            "test_only": True,
        }

    if len(candles_m5) < MIN_CANDLES_M5:
        return {
            "signal": "NO SIGNAL",
            "reason": "At least 70 closed M5 candles are required.",
            "test_only": True,
        }

    if not all(_valid_candle(c) for c in candles_m1):
        return {
            "signal": "NO SIGNAL",
            "reason": "Invalid M1 candle data.",
            "test_only": True,
        }

    if not all(_valid_candle(c) for c in candles_m5):
        return {
            "signal": "NO SIGNAL",
            "reason": "Invalid M5 candle data.",
            "test_only": True,
        }

    close_m1 = [float(c["close"]) for c in candles_m1]
    close_m5 = [float(c["close"]) for c in candles_m5]

    ema20_m5 = ema(close_m5, EMA_FAST)
    ema50_m5 = ema(close_m5, EMA_SLOW)
    ema20_m1 = ema(close_m1, EMA_FAST)
    rsi_m1 = rsi(close_m1)

    if not ema20_m5 or not ema50_m5 or not ema20_m1 or not rsi_m1:
        return {
            "signal": "NO SIGNAL",
            "reason": "Not enough data to calculate indicators.",
            "test_only": True,
        }

    trend_fast = ema20_m5[-1]
    trend_slow = ema50_m5[-1]

    if trend_fast > trend_slow:
        trend = "CALL"
    elif trend_fast < trend_slow:
        trend = "PUT"
    else:
        return {
            "signal": "NO SIGNAL",
            "reason": "M5 trend is unclear.",
            "test_only": True,
        }

    candle = candles_m1[-1]
    open_price = float(candle["open"])
    high = float(candle["high"])
    low = float(candle["low"])
    close = float(candle["close"])

    candle_range = high - low
    body_ratio = (
        abs(close - open_price) / candle_range
        if candle_range > 0
        else 0.0
    )

    rsi_value = rsi_m1[-1]
    pullback_ema = ema20_m1[-2]

    # Previous closed candle must touch/cross EMA20.
    previous = candles_m1[-2]
    previous_low = float(previous["low"])
    previous_high = float(previous["high"])
    pullback_found = previous_low <= pullback_ema <= previous_high

    bullish_candle = close > open_price
    bearish_candle = close < open_price

    if trend == "CALL":
        confirmed = (
            pullback_found
            and bullish_candle
            and body_ratio >= BODY_RATIO_MIN
            and rsi_value > RSI_CALL_MIN
        )
    else:
        confirmed = (
            pullback_found
            and bearish_candle
            and body_ratio >= BODY_RATIO_MIN
            and rsi_value < RSI_PUT_MAX
        )

    details = {
        "trend_m5": trend,
        "ema20_m5": round(trend_fast, 6),
        "ema50_m5": round(trend_slow, 6),
        "ema20_m1": round(ema20_m1[-1], 6),
        "rsi14_m1": round(rsi_value, 2),
        "candle_body_ratio": round(body_ratio, 3),
        "pullback_found": pullback_found,
        "test_only": True,
    }

    if confirmed:
        return {
            "signal": trend,
            "reason": "M5 trend, M1 pullback, RSI and closed-candle confirmation aligned.",
            **details,
        }

    return {
        "signal": "NO SIGNAL",
        "reason": "M1 entry conditions are not all aligned.",
        **details,
    }
