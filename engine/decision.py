
"""
BINARY ENGINE - DECISION ENGINE

TEST ONLY:
- Reads public Deriv candles.
- Displays MACD and Bollinger Bands values.
- Checks strategy and daily risk limits.
- Never places or records a real trade.
"""

import json
from datetime import datetime, timezone

from websocket import create_connection

from engine.signals import generate_signal
from risk import DailyRiskManager


WS_URL = "wss://api.derivws.com/trading/v1/options/ws/public"
SYMBOL = "R_100"
CANDLE_COUNT = 150
TIMEFRAME_SECONDS = 60


def get_closed_candles():
    connection = None

    try:
        connection = create_connection(WS_URL, timeout=20)

        request = {
            "ticks_history": SYMBOL,
            "adjust_start_time": 1,
            "count": CANDLE_COUNT,
            "end": "latest",
            "granularity": TIMEFRAME_SECONDS,
            "style": "candles",
            "req_id": 1,
        }

        connection.send(json.dumps(request))

        while True:
            response = json.loads(connection.recv())

            if response.get("req_id") == 1:
                break

        if "error" in response:
            message = response["error"].get(
                "message", str(response["error"])
            )
            raise RuntimeError(message)

        candles = response.get("candles", [])
        now = int(datetime.now(timezone.utc).timestamp())

        candles = [
            candle for candle in candles
            if int(candle["epoch"]) + TIMEFRAME_SECONDS <= now
        ]

        candles.sort(key=lambda candle: int(candle["epoch"]))

        if len(candles) < 40:
            raise RuntimeError(
                f"Not enough closed candles: {len(candles)}"
            )

        return candles

    finally:
        if connection is not None:
            connection.close()


def main():
    print("=" * 55)
    print("          BINARY ENGINE - INDICATOR CHECK")
    print("=" * 55)
    print("Mode: TEST ONLY")
    print("Market:", SYMBOL)
    print("Timeframe: M1")
    print("Real trades: DISABLED")

    try:
        print("\nConnecting to Deriv public market data...")
        candles = get_closed_candles()
        prices = [float(candle["close"]) for candle in candles]

        opens = [float(candle["open"]) for candle in candles]
        signal = generate_signal(prices, opens)

        candle_time = datetime.fromtimestamp(
            int(candles[-1]["epoch"]),
            timezone.utc,
        ).strftime("%Y-%m-%d %H:%M:%S UTC")

        risk_manager = DailyRiskManager(
            max_trades=6,
            max_losses=2,
        )

        allowed, risk_message = risk_manager.can_trade()

        print("\n=== MARKET DATA ===")
        print("Symbol:", SYMBOL)
        print("Closed candles:", len(candles))
        print("Last closed candle:", candle_time)
        print(f"Close price: {prices[-1]:.8f}")

        print("\n=== MACD (13, 29, 8) ===")
        if "macd" in signal:
            print(f"Previous MACD: {signal['macd_previous']:.8f}")
            print(f"Current MACD:  {signal['macd']:.8f}")
            print(f"Previous Signal: {signal['signal_previous']:.8f}")
            print(f"Current Signal:  {signal['signal']:.8f}")
            print(f"Histogram: {signal['histogram']:.8f}")
            print("Bullish crossover:", signal["bullish_cross"])
            print("Bearish crossover:", signal["bearish_cross"])
        else:
            print("MACD values are not available yet.")

        print("\n=== BOLLINGER BANDS (22, 2) ===")
        if "bb_upper" in signal:
            print(f"Upper band:  {signal['bb_upper']:.8f}")
            print(f"Middle band: {signal['bb_middle']:.8f}")
            print(f"Lower band:  {signal['bb_lower']:.8f}")
            print("Price inside bands:", signal["inside_bands"])
        else:
            print("Bollinger Band values are not available yet.")

        print("\n=== STRATEGY RESULT ===")
        print("Signal:", signal.get("direction"))
        print("Status:", signal.get("status"))
        print("Planned entry:", signal.get("entry") or "NONE")

        print("\n=== DAILY RISK STATUS ===")
        print("Can trade:", allowed)
        print("Risk message:", risk_message)
        risk_manager.show_status()

        print("\nTEST ONLY: No trades were placed.")
        print("No trade result was recorded.")

    except Exception as error:
        print("\nDecision engine failed:")
        print(type(error).__name__ + ":", error)
        print("No trades were placed.")


if __name__ == "__main__":
    main()

