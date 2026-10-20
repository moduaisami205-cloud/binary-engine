
import json
from datetime import datetime, timezone

from websocket import create_connection

from engine.signals import (
    generate_signal,
    calculate_bollinger_bands,
    calculate_macd,
)

APP_ID = 1089
SYMBOL = "R_100"
CANDLE_COUNT = 100

WS_URL = (
    "wss://api.derivws.com/trading/v1/options/ws/public"
)


def main():
    connection = None

    try:
        print("=" * 50)
        print("          BINARY ENGINE")
        print("      DERIV INDICATOR TEST")
        print("=" * 50)
        print("Connecting to Deriv...")

        connection = create_connection(
            WS_URL,
            timeout=15,
        )

        request = {
            "ticks_history": SYMBOL,
            "adjust_start_time": 1,
            "count": CANDLE_COUNT,
            "end": "latest",
            "granularity": 60,
            "style": "candles",
            "req_id": 1,
        }

        connection.send(json.dumps(request))
        response = json.loads(connection.recv())

        if "error" in response:
            print("Deriv error:", response["error"])
            return

        candles = response.get("candles", [])

        if len(candles) < 40:
            print("Not enough candles received.")
            print("Candles:", len(candles))
            return

        # Remove the latest candle if it is still forming.
        now = int(datetime.now(timezone.utc).timestamp())

        if int(candles[-1]["epoch"]) + 60 > now:
            candles = candles[:-1]

        if len(candles) < 40:
            print("Not enough closed candles.")
            return

        closed_prices = [
            float(candle["close"])
            for candle in candles
        ]

        bands = calculate_bollinger_bands(
            closed_prices,
            period=22,
            deviation=2,
        )

        macd_data = calculate_macd(
            closed_prices,
            fast=13,
            slow=29,
            signal_period=8,
        )

        result = generate_signal(closed_prices)

        if bands is None or macd_data is None:
            print("Not enough data to calculate indicators.")
            return

        latest_candle = candles[-1]

        candle_time = datetime.fromtimestamp(
            int(latest_candle["epoch"]),
            timezone.utc,
        ).strftime("%Y-%m-%d %H:%M:%S UTC")

        print()
        print("=== MARKET DATA ===")
        print("Symbol:", SYMBOL)
        print("Timeframe: M1")
        print("Closed candles:", len(closed_prices))
        print("Last closed candle:", candle_time)
        print("Last close:", closed_prices[-1])

        print()
        print("=== BOLLINGER BANDS (22, 2) ===")
        print("Upper:", round(bands["upper"], 5))
        print("Middle:", round(bands["middle"], 5))
        print("Lower:", round(bands["lower"], 5))

        print()
        print("=== MACD (13, 29, 8) ===")
        print("Previous MACD:", round(macd_data["macd"][-2], 7))
        print("Current MACD:", round(macd_data["macd"][-1], 7))
        print("Previous Signal:", round(macd_data["signal"][-2], 7))
        print("Current Signal:", round(macd_data["signal"][-1], 7))
        print("Current Histogram:", round(macd_data["histogram"][-1], 7))

        print()
        print("=== STRATEGY RESULT ===")
        print("Direction:", result["direction"])
        print("Status:", result["status"])
        print("Mode: TEST ONLY")
        print("No trades placed.")

    except Exception as error:
        print("Test failed:")
        print(type(error).__name__ + ":", error)

    finally:
        if connection is not None:
            connection.close()
            print("\nConnection closed.")


if __name__ == "__main__":
    main()
