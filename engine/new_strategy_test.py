
import json
import time
from datetime import datetime, timezone

from websocket import create_connection
from engine.strategy import generate_strategy_signal

WS_URL = "wss://api.derivws.com/trading/v1/options/ws/public"

MARKETS = ["R_10", "R_25", "R_50", "R_75", "R_100"]

TIMEFRAME_SECONDS = 60
CANDLE_COUNT = 120


def fetch_closed_candles(symbol):
    connection = None

    try:
        connection = create_connection(WS_URL, timeout=15)

        request = {
            "ticks_history": symbol,
            "end": "latest",
            "count": CANDLE_COUNT,
            "style": "candles",
            "granularity": TIMEFRAME_SECONDS,
        }

        connection.send(json.dumps(request))
        response = json.loads(connection.recv())

        if response.get("error"):
            raise RuntimeError(
                response["error"].get("message", "Deriv API error")
            )

        candles = []
        now = int(time.time())

        for candle in response.get("candles", []):
            epoch = int(candle["epoch"])

            if epoch + TIMEFRAME_SECONDS <= now:
                candles.append({
                    "epoch": epoch,
                    "open": float(candle["open"]),
                    "high": float(candle["high"]),
                    "low": float(candle["low"]),
                    "close": float(candle["close"]),
                })

        candles.sort(key=lambda candle: candle["epoch"])
        return candles

    finally:
        if connection is not None:
            connection.close()


def main():
    print("=" * 50)
    print("BINARY ENGINE - NEW STRATEGY TEST")
    print("EMA 20/50 + RSI 14 + Stochastic 14,3,3")
    print("M1 timeframe | Intended expiry: 3 minutes")
    print("TEST ONLY - NO REAL TRADES")
    print("=" * 50)

    for symbol in MARKETS:
        try:
            candles = fetch_closed_candles(symbol)

            if not candles:
                print(f"\n{symbol}: No candles received.")
                continue

            result = generate_strategy_signal(candles)
            last_candle = candles[-1]

            candle_time = datetime.fromtimestamp(
                last_candle["epoch"],
                timezone.utc,
            ).strftime("%Y-%m-%d %H:%M:%S UTC")

            print(f"\nMarket: {symbol}")
            print(f"Closed candles: {len(candles)}")
            print(f"Last closed candle: {candle_time}")
            print(f"Signal: {result['signal']}")
            print(f"Reason: {result['reason']}")

            for key, value in result.get("details", {}).items():
                print(f"{key}: {value}")

        except Exception as error:
            print(f"\n{symbol}: TEST ERROR: {error}")

    print("\nTest finished. No trades were placed.")


if __name__ == "__main__":
    main()
