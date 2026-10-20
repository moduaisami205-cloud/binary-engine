
"""Binary Engine Strategy v0.3
EMA 20/50 + RSI 14 + Stochastic 14,3,3
Strong closed-candle confirmation.
M1 timeframe, intended 3-minute expiry.
TEST ONLY - no real trades.
"""


def generate_strategy_signal(candles):
    """Candles must be closed and ordered oldest first.
    Required keys: open, high, low, close.
    """

    if not isinstance(candles, list) or len(candles) < 70:
        return {
            "signal": "NO SIGNAL",
            "reason": "At least 70 closed candles are required."
        }

    try:
        opens = [float(c["open"]) for c in candles]
        highs = [float(c["high"]) for c in candles]
        lows = [float(c["low"]) for c in candles]
        closes = [float(c["close"]) for c in candles]
    except (KeyError, TypeError, ValueError):
        return {
            "signal": "NO SIGNAL",
            "reason": "Invalid candle data."
        }

    series = (opens, highs, lows, closes)
    if any(
        not all(x == x and abs(x) != float("inf") for x in values)
        for values in series
    ):
        return {
            "signal": "NO SIGNAL",
            "reason": "Candle values must be finite."
        }

    for o, h, l, c in zip(opens, highs, lows, closes):
        if l > min(o, c) or h < max(o, c) or l > h:
            return {
                "signal": "NO SIGNAL",
                "reason": "Invalid OHLC candle."
            }

    def ema(values, period):
        alpha = 2 / (period + 1)
        current = sum(values[:period]) / period
        result = [None] * (period - 1) + [current]
        for value in values[period:]:
            current = alpha * value + (1 - alpha) * current
            result.append(current)
        return result

    def rsi(values, period=14):
        changes = [values[i] - values[i - 1]
                   for i in range(1, len(values))]
        gains = [max(x, 0) for x in changes]
        losses = [max(-x, 0) for x in changes]

        avg_gain = sum(gains[:period]) / period
        avg_loss = sum(losses[:period]) / period

        def calc(gain, loss):
            if loss == 0:
                return 100.0 if gain > 0 else 50.0
            return 100 - 100 / (1 + gain / loss)

        result = [None] * period + [calc(avg_gain, avg_loss)]

        for i in range(period, len(gains)):
            avg_gain = ((period - 1) * avg_gain + gains[i]) / period
            avg_loss = ((period - 1) * avg_loss + losses[i]) / period
            result.append(calc(avg_gain, avg_loss))

        return result

    def sma(values, period):
        return [
            sum(values[i - period + 1:i + 1]) / period
            for i in range(period - 1, len(values))
        ]

    ema20 = ema(closes, 20)[-1]
    ema50 = ema(closes, 50)[-1]
    rsi_now = rsi(closes, 14)[-1]

    # Stochastic 14,3,3
    raw_k = []
    for i in range(13, len(candles)):
        lowest = min(lows[i - 13:i + 1])
        highest = max(highs[i - 13:i + 1])
        raw_k.append(
            50.0 if highest == lowest
            else 100 * (closes[i] - lowest) / (highest - lowest)
        )

    smooth_k = sma(raw_k, 3)
    smooth_d = sma(smooth_k, 3)

    k_prev, k_now = smooth_k[-2], smooth_k[-1]
    d_prev, d_now = smooth_d[-2], smooth_d[-1]

    candle_range = highs[-1] - lows[-1]
    if candle_range <= 0:
        return {
            "signal": "NO SIGNAL",
            "reason": "Latest candle has no range."
        }

    body_strength = abs(closes[-1] - opens[-1]) / candle_range
    bullish = closes[-1] > opens[-1] and body_strength >= 0.60
    bearish = closes[-1] < opens[-1] and body_strength >= 0.60

    call_confirmed = (
        ema20 > ema50
        and rsi_now > 50
        and k_prev <= d_prev
        and k_now > d_now
        and bullish
    )

    put_confirmed = (
        ema20 < ema50
        and rsi_now < 50
        and k_prev >= d_prev
        and k_now < d_now
        and bearish
    )

    details = {
        "timeframe": "M1",
        "intended_expiry_minutes": 3,
        "ema20": round(ema20, 6),
        "ema50": round(ema50, 6),
        "rsi14": round(rsi_now, 2),
        "stochastic_k": round(k_now, 2),
        "stochastic_d": round(d_now, 2),
        "candle_body_percent": round(body_strength * 100, 2),
        "volume_confirmation": "UNAVAILABLE",
        "test_only": True,
    }

    if call_confirmed:
        return {
            "signal": "CALL",
            "reason": "All available CALL conditions confirmed.",
            "details": details,
        }

    if put_confirmed:
        return {
            "signal": "PUT",
            "reason": "All available PUT conditions confirmed.",
            "details": details,
        }

    return {
        "signal": "NO SIGNAL",
        "reason": "Conditions are not fully aligned.",
        "details": details,
    }
