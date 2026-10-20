
import asyncio
import csv
import json
import os
from datetime import datetime, timezone

import websockets

from engine.strategy import generate_strategy_signal

APP_ID = 1089
WS_URL = (
    "wss://api.derivws.com/trading/v1/options/ws/public"
    f"?app_id={APP_ID}"
)

MARKETS = ["R_10", "R_25", "R_50", "R_75", "R_100"]
TIMEFRAME_SECONDS = 60
EXPIRY_MINUTES = 2
CANDLE_COUNT = 120
POLL_SECONDS = 60

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
RESULTS_FILE = os.path.join(BASE_DIR, "forward_strategy_results_v3.csv")
STATE_FILE = os.path.join(BASE_DIR, "forward_strategy_state_v3.json")


def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r", encoding="utf-8") as file:
            return json.load(file)
    return {"pending": [], "completed": []}


def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as file:
        json.dump(state, file, indent=2)


def ensure_csv():
    if not os.path.exists(RESULTS_FILE):
        with open(RESULTS_FILE, "w", newline="", encoding="utf-8") as file:
            writer = csv.writer(file)
            writer.writerow([
                "signal_id", "market", "signal", "signal_epoch",
                "entry_epoch", "exit_epoch", "entry_close",
                "exit_close", "result", "recorded_at_utc"
            ])


async def request_candles(ws, market):
    request = {
        "ticks_history": market,
        "count": CANDLE_COUNT,
        "end": "latest",
        "style": "candles",
        "granularity": TIMEFRAME_SECONDS,
    }

    await ws.send(json.dumps(request))

    while True:
        response = json.loads(await ws.recv())

        if response.get("error"):
            raise RuntimeError(response["error"].get("message", "API error"))

        if response.get("msg_type") == "candles":
            return response.get("candles", [])


def get_closed_candles(candles):
    now = int(datetime.now(timezone.utc).timestamp())
    return [
        candle for candle in candles
        if int(candle["epoch"]) + TIMEFRAME_SECONDS <= now
    ]


def summarize(state):
    completed = state["completed"]
    wins = sum(item["result"] == "WIN" for item in completed)
    losses = sum(item["result"] == "LOSS" for item in completed)
    draws = sum(item["result"] == "DRAW" for item in completed)
    unavailable = sum(item["result"] == "UNAVAILABLE" for item in completed)
    decided = wins + losses

    print("\n--- FORWARD TEST SUMMARY V3 ---")
    print(f"Completed: {len(completed)}")
    print(f"Wins: {wins} | Losses: {losses} | Draws: {draws}")
    print(f"Unavailable: {unavailable}")
    rate = (wins / decided * 100) if decided else 0
    print(f"Win rate excluding draws: {rate:.2f}%")
    print(f"Pending signals: {len(state['pending'])}")
    print("Test only: directional estimates, not actual trade profits.")


async def settle_pending(ws, state):
    now = int(datetime.now(timezone.utc).timestamp())

    for item in state["pending"][:]:
        if now < item["exit_epoch"] + TIMEFRAME_SECONDS:
            continue

        try:
            candles = await request_candles(ws, item["market"])
            closed = get_closed_candles(candles)

            entry = next(
                (c for c in closed if int(c["epoch"]) == item["entry_epoch"]),
                None,
            )
            exit_candle = next(
                (c for c in closed if int(c["epoch"]) == item["exit_epoch"]),
                None,
            )

            if entry is None or exit_candle is None:
                print(f"{item['market']}: candles not available yet; will retry.")
                continue

            entry_close = float(entry["close"])
            exit_close = float(exit_candle["close"])

            if exit_close == entry_close:
                result = "DRAW"
            elif item["signal"] == "CALL":
                result = "WIN" if exit_close > entry_close else "LOSS"
            else:
                result = "WIN" if exit_close < entry_close else "LOSS"

            completed = {
                **item,
                "entry_close": entry_close,
                "exit_close": exit_close,
                "result": result,
            }

            with open(RESULTS_FILE, "a", newline="", encoding="utf-8") as file:
                writer = csv.writer(file)
                writer.writerow([
                    item["signal_id"], item["market"], item["signal"],
                    item["signal_epoch"], item["entry_epoch"],
                    item["exit_epoch"], entry_close, exit_close, result,
                    datetime.now(timezone.utc).isoformat(),
                ])

            state["completed"].append(completed)
            state["pending"].remove(item)
            save_state(state)

            print(
                f"\nRESULT | {item['market']} | {item['signal']} | "
                f"{result} | Entry={entry_close} | Exit={exit_close}"
            )

        except Exception as exc:
            print(f"{item['market']}: settlement error: {exc}")


async def main():
    ensure_csv()
    state = load_state()

    print("BINARY ENGINE - FORWARD STRATEGY TEST V3")
    print("Timeframe: M1 | Expiry: 2 minutes")
    print("Markets:", ", ".join(MARKETS))
    print("No real trades will be placed.")
    print("Press Ctrl+C to stop.\n")

    while True:
        try:
            async with websockets.connect(
                WS_URL, open_timeout=20, close_timeout=5
            ) as ws:
                await settle_pending(ws, state)

                for market in MARKETS:
                    try:
                        candles = await request_candles(ws, market)
                        closed = get_closed_candles(candles)

                        if len(closed) < 70:
                            print(f"{market}: Not enough closed candles.")
                            continue

                        latest = closed[-1]
                        signal_epoch = int(latest["epoch"])

                        # Avoid recording the same market/candle more than once.
                        signal_id = f"{market}_{signal_epoch}"
                        already_seen = (
                            any(p["signal_id"] == signal_id for p in state["pending"])
                            or any(c["signal_id"] == signal_id for c in state["completed"])
                        )
                        if already_seen:
                            continue

                        result = generate_strategy_signal(closed)
                        signal = result.get("signal", "NO SIGNAL")
                        stamp = datetime.fromtimestamp(
                            signal_epoch, timezone.utc
                        ).strftime("%Y-%m-%d %H:%M:%S UTC")

                        print(f"\n{market} | {stamp} | {signal}")

                        if signal not in ("CALL", "PUT"):
                            print(result.get("reason", "Conditions are not fully aligned."))
                            continue

                        entry_epoch = signal_epoch + TIMEFRAME_SECONDS
                        exit_epoch = entry_epoch + (
                            EXPIRY_MINUTES - 1
                        ) * TIMEFRAME_SECONDS

                        item = {
                            "signal_id": signal_id,
                            "market": market,
                            "signal": signal,
                            "signal_epoch": signal_epoch,
                            "entry_epoch": entry_epoch,
                            "exit_epoch": exit_epoch,
                        }

                        state["pending"].append(item)
                        save_state(state)
                        print(
                            f"Recorded {signal}; entry candle={entry_epoch}; "
                            f"exit candle={exit_epoch}"
                        )

                    except Exception as exc:
                        print(f"{market}: ERROR: {exc}")

                summarize(state)

        except Exception as exc:
            print(f"Connection error: {exc}")

        await asyncio.sleep(POLL_SECONDS)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nForward test stopped.")
        summarize(load_state())

