
"""
BINARY ENGINE - MULTI-TIMEFRAME STRATEGY

Markets:
R_10, R_25, R_50, R_75, R_100

M5: Market direction confirmation
M3: Momentum confirmation
M1: Original entry strategy
Bollinger Bands: 22, deviation 2
MACD: 13, 29, 8
Expiry: 3 minutes

DEMO / TEST ONLY.
No trades are placed by this module.

All supplied candles must be CLOSED candles,
ordered oldest first.
"""


SUPPORTED_MARKETS = (
    "R_10",
    "R_25",
    "R_50",
    "R_75",
    "R_100",
)


def calculate_bollinger_bands(prices, period=22, deviation=2):
    if period < 2 or len(prices) < period:
        return None

    window = [float(x) for x in prices[-period:]]
    middle = sum(window) / period

    variance = sum(
        (price - middle) ** 2
        for price in window
    ) / period

    std_dev = variance ** 0.5

    return {
        "upper": middle + deviation * std_dev,
        "middle": middle,
        "lower": middle - deviation * std_dev,
    }


def calculate_ema(values, period):
    if period < 1 or len(values) < period:
        return []

    multiplier = 2.0 / (period + 1)
    ema = sum(values[:period]) / period
    result = [ema]

    for value in values[period:]:
        ema = (value - ema) * multiplier + ema
        result.append(ema)

    return result


def calculate_macd(
    prices,
    fast=13,
    slow=29,
    signal_period=8,
):
    if fast < 1 or slow <= fast or signal_period < 1:
        raise ValueError("Invalid MACD periods.")

    if len(prices) < slow + signal_period:
        return None

    fast_ema = calculate_ema(prices, fast)
    slow_ema = calculate_ema(prices, slow)

    offset = slow - fast

    macd_line = [
        fast_value - slow_value
        for fast_value, slow_value in zip(
            fast_ema[offset:],
            slow_ema,
        )
    ]

    signal_line = calculate_ema(
        macd_line,
        signal_period,
    )

    if len(signal_line) < 2:
        return None

    aligned_macd = macd_line[-len(signal_line):]

    histogram = [
        macd_value - signal_value
        for macd_value, signal_value in zip(
            aligned_macd,
            signal_line,
        )
    ]

    return {
        "macd": aligned_macd,
        "signal": signal_line,
        "histogram": histogram,
    }


def _timeframe_direction(prices):
    """
    Higher-timeframe confirmation.

    Bullish: MACD > signal AND histogram > 0
    Bearish: MACD < signal AND histogram < 0

    A new crossover is not required on M5 or M3.
    """
    data = calculate_macd(
        prices,
        fast=13,
        slow=29,
        signal_period=8,
    )

    if data is None:
        return None

    macd = data["macd"][-1]
    signal = data["signal"][-1]
    histogram = data["histogram"][-1]

    if macd > signal and histogram > 0:
        return "CALL"

    if macd < signal and histogram < 0:
        return "PUT"

    return None


def generate_signal(
    closed_prices,
    closed_opens=None,
    closed_prices_m3=None,
    closed_prices_m5=None,
    symbol="R_100",
):
    """
    M1 entry strategy with M3 and M5 confirmation.

    closed_prices:
        M1 closing prices, oldest first.

    closed_opens:
        M1 opening prices, oldest first.

    closed_prices_m3:
        M3 closing prices, oldest first.

    closed_prices_m5:
        M5 closing prices, oldest first.

    Only CLOSED candle data may be supplied.
    This function generates signals; it places no trades.
    """

    def result(direction=None, status="NO SIGNAL", **extra):
        output = {
            "symbol": symbol,
            "direction": direction,
            "status": status,
            "strategy": "MTF_M5_M3_M1",
            "expiry": "3 MINUTES" if direction else None,
            "entry": "NEXT M1 CANDLE" if direction else None,
            "test_only": True,
        }
        output.update(extra)
        return output

    if symbol not in SUPPORTED_MARKETS:
        return result(
            status="UNSUPPORTED MARKET",
            supported_markets=list(SUPPORTED_MARKETS),
        )

    if (
        closed_prices_m3 is None
        or closed_prices_m5 is None
    ):
        return result(
            status="WAITING FOR M3/M5 DATA",
            reason="M3 and M5 candle data must be connected.",
        )

    if (
        closed_opens is None
        or len(closed_opens) != len(closed_prices)
    ):
        return result(
            status="WAITING FOR M1 OPEN DATA",
        )

    if (
        len(closed_prices) < 40
        or len(closed_prices_m3) < 40
        or len(closed_prices_m5) < 40
    ):
        return result(
            status="WAITING FOR MORE DATA",
            reason="At least 40 closed candles are required per timeframe.",
        )

    try:
        m1 = [float(x) for x in closed_prices]
        m3 = [float(x) for x in closed_prices_m3]
        m5 = [float(x) for x in closed_prices_m5]
        opens = [float(x) for x in closed_opens]

        bands = calculate_bollinger_bands(
            m1,
            period=22,
            deviation=2,
        )

        macd_data = calculate_macd(
            m1,
            fast=13,
            slow=29,
            signal_period=8,
        )

        if bands is None or macd_data is None:
            return result(status="WAITING FOR MORE DATA")

        # -----------------------------------------------------
        # M5 + M3 MULTI-TIMEFRAME CONFIRMATION
        # -----------------------------------------------------

        m5_direction = _timeframe_direction(m5)
        m3_direction = _timeframe_direction(m3)

        # -----------------------------------------------------
        # ORIGINAL M1 STRATEGY
        # -----------------------------------------------------

        previous_macd = macd_data["macd"][-2]
        current_macd = macd_data["macd"][-1]

        previous_signal = macd_data["signal"][-2]
        current_signal = macd_data["signal"][-1]

        previous_histogram = macd_data["histogram"][-2]
        current_histogram = macd_data["histogram"][-1]

        price = m1[-1]
        candle_open = opens[-1]

        bullish_cross = (
            previous_macd <= previous_signal
            and current_macd > current_signal
        )

        bearish_cross = (
            previous_macd >= previous_signal
            and current_macd < current_signal
        )

        bullish_histogram_zero_cross = (
            previous_histogram <= 0
            and current_histogram > 0
        )

        bearish_histogram_zero_cross = (
            previous_histogram >= 0
            and current_histogram < 0
        )

        inside_bands = (
            bands["lower"] < price < bands["upper"]
        )

        # -----------------------------------------------------
        # ALL THREE TIMEFRAMES MUST AGREE
        # -----------------------------------------------------

        call_confirmed = (
            m5_direction == "CALL"
            and m3_direction == "CALL"
            and bullish_cross
            and bullish_histogram_zero_cross
            and inside_bands
        )

        put_confirmed = (
            m5_direction == "PUT"
            and m3_direction == "PUT"
            and bearish_cross
            and bearish_histogram_zero_cross
            and inside_bands
        )

        direction = None
        status = "NO SIGNAL"

        if call_confirmed:
            direction = "CALL"
            status = "CALL SETUP CONFIRMED"

        elif put_confirmed:
            direction = "PUT"
            status = "PUT SETUP CONFIRMED"

        elif not inside_bands:
            status = "PRICE OUTSIDE BOLLINGER BANDS"

        elif m5_direction is None or m3_direction is None:
            status = "WAITING FOR MTF CONFIRMATION"

        elif m5_direction != m3_direction:
            status = "M5/M3 DIRECTION CONFLICT"

        elif m1_direction := (
            "CALL" if bullish_cross
            and bullish_histogram_zero_cross
            else "PUT" if bearish_cross
            and bearish_histogram_zero_cross
            else None
        ):
            if m1_direction != m5_direction:
                status = "M1/M5/M3 DIRECTION CONFLICT"
            else:
                status = "M1 SETUP INCOMPLETE"

        else:
            status = "M1 MACD/HISTOGRAM SETUP NOT CONFIRMED"

        return result(
            direction=direction,
            status=status,
            price=price,
            candle_open=candle_open,
            bb_upper=bands["upper"],
            bb_middle=bands["middle"],
            bb_lower=bands["lower"],
            inside_bands=inside_bands,
            m5_direction=m5_direction,
            m3_direction=m3_direction,
            bullish_cross=bullish_cross,
            bearish_cross=bearish_cross,
            bullish_histogram_zero_cross=(
                bullish_histogram_zero_cross
            ),
            bearish_histogram_zero_cross=(
                bearish_histogram_zero_cross
            ),
            macd_previous=previous_macd,
            macd=current_macd,
            signal_previous=previous_signal,
            signal=current_signal,
            histogram_previous=previous_histogram,
            histogram=current_histogram,
        )

    except (TypeError, ValueError, IndexError):
        return result(
            status="INVALID CANDLE DATA",
            reason="Check that all candle prices are numeric.",
        )
