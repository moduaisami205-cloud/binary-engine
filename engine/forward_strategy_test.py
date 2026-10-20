
import csv
import json
import os
import time
from datetime import datetime, timezone

from websocket import create_connection
from engine.strategy import generate_strategy_signal


WS_URL = "wss://api.derivws.com/trading/v1/options/ws/public"

MARKETS = ["R_10", "R_25", "R_50", "R_75", "R_100"]

GRANULARITY = 60
CANDLE_COUNT = 120
EXPIRY_MINUTES = 3
SCAN_SECONDS = 60

RESULTS_FILE = "engine/forward_strategy_results_v2.csv"
STATE_FILE = "engine/forward_strategy_state_v2.json"


def get_closed_candles(symbol):
    connection = create_connection(WS_URL, timeout=20)

    try:
        request = {
            "ticks_history": symbol,
            "end": "latest",
            "count": CANDLE_COUNT,
            "style": "candles",
            "granularity": GRANULARITY,
        }

        connection.send(json.dumps(request))
        response = json.loads(connection.recv())

        if response.get("error"):
            raise RuntimeError(
                response["error"].get("message", "Deriv API error")
            )

        now = int(time.time())
        candles = []

        for candle in response.get("candles", []):
            epoch = int(candle["epoch"])

            if epoch + GRANULARITY <= now:
                candles.append({
                    "epoch": epoch,
                    "open": float(candle["open"]),
                    "high": float(candle["high"]),
                    "low": float(candle["low"]),
                    "close": float(candle["close"]),
                })

        candles.sort(key=lambda item: item["epoch"])
        return candles

    finally:
        connection.close()


def load_state():
    if not os.path.exists(STATE_FILE):
        return {"pending": [], "completed": []}

    with open(STATE_FILE, "r", encoding="utf-8") as file:
        state = json.load(file)

    if not isinstance(state, dict):
        raise ValueError("Invalid state file")

    state.setdefault("pending", [])
    state.setdefault("completed", [])
    return state


def save_state(state):
    temporary = STATE_FILE + ".tmp"

    with open(temporary, "w", encoding="utf-8") as file:
        json.dump(state, file, indent=2)

    os.replace(temporary, STATE_FILE)


def ensure_csv():
    if not os.path.exists(RESULTS_FILE):
        with open(
            RESULTS_FILE, "w", newline="", encoding="utf-8"
        ) as file:
            writer = csv.writer(file)
            writer.writerow([
                "signal_id",
                "market",
                "signal",
                "signal_candle_utc",
                "entry_candle_epoch",
                "exit_candle_epoch",
                "expiry_minutes",
                "result",
                "entry_price",
                "exit_price",
            ])


def append_result(item, result, entry_price="", exit_price=""):
    with open(
        RESULTS_FILE, "a", newline="", encoding="utf-8"
    ) as file:
        writer = csv.writer(file)
        writer.writerow([
            item["signal_id"],
            item["market"],
            item["signal"],
            item["signal_time_utc"],
            item["entry_epoch"],
            item["exit_epoch"],
            EXPIRY_MINUTES,
            result,
            entry_price,
            exit_price,
        ])


def settle_pending(state):
    remaining = []

    for item in state["pending"]:
        try:
            candles = get_closed_candles(item["market"])
            by_epoch = {c["epoch"]: c for c in candles}

            entry = by_epoch.get(item["entry_epoch"])
            exit_candle = by_epoch.get(item["exit_epoch"])

            if entry is None or exit_candle is None:
                # Wait until the expected expiry candle should be closed.
                deadline = item["exit_epoch"] + GRANULARITY

                if int(time.time()) <= deadline + 30:
                    remaining.append(item)
                    continue

                append_result(item, "UNAVAILABLE")
                state["completed"].append({
                    "signal_id": item["signal_id"],
                    "market": item["market"],
                    "signal": item["signal"],
                    "result": "UNAVAILABLE",
                })

                print(
                    f"RESULT | {item['market']} | "
                    "UNAVAILABLE: required candle missing"
                )
                continue

            entry_price = entry["open"]
            exit_price = exit_candle["close"]

            if exit_price == entry_price:
                result = "DRAW"
            elif item["signal"] == "CALL":
                result = "WIN" if exit_price > entry_price else "LOSS"
            else:
                result = "WIN" if exit_price < entry_price else "LOSS"

            append_result(item, result, entry_price, exit_price)

            state["completed"].append({
                "signal_id": item["signal_id"],
                "market": item["market"],
                "signal": item["signal"],
                "result": result,
            })

            print(
                f"RESULT | {item['market']} | {item['signal']} | "
                f"{result} | entry={entry_price} | exit={exit_price}"
            )

        except Exception as error:
            print(f"Settlement error {item['market']}: {error}")
            remaining.append(item)

    state["pending"] = remaining
    save_state(state)


def print_summary(state):
    completed = state["completed"]

    wins = sum(x["result"] == "WIN" for x in completed)
    losses = sum(x["result"] == "LOSS" for x in completed)
    draws = sum(x["result"] == "DRAW" for x in completed)
    unavailable = sum(
        x["result"] == "UNAVAILABLE" for x in completed
    )

    decisive = wins + losses
    rate = wins / decisive * 100 if decisive else 0.0

    print("\n--- FORWARD TEST SUMMARY V2 ---")
    print(f"Completed: {len(completed)}")
    print(f"Wins: {wins} | Losses: {losses} | Draws: {draws}")
    print(f"Unavailable: {unavailable}")
    print(f"Win rate excluding draws: {rate:.2f}%")
    print(f"Pending signals: {len(state['pending'])}")
    print("Directional estimates only; not actual trade profits.")


def main():
    os.makedirs("engine", exist_ok=True)
    ensure_csv()
    state = load_state()

    print("=" * 55)
    print("BINARY ENGINE - FORWARD STRATEGY TEST V2")
    print("EMA 20/50 + RSI 14 + Stochastic 14,3,3")
    print("M1 signals | 3-minute directional evaluation")
    print("TEST ONLY - NO REAL TRADES")
    print("Press Ctrl+C to stop.")
    print("=" * 55)

    try:
        while True:
            started = time.time()

            settle_pending(state)

            known_ids = {
                x["signal_id"] for x in state["pending"]
            }
            known_ids.update(
                x["signal_id"] for x in state["completed"]
            )

            for market in MARKETS:
                try:
                    candles = get_closed_candles(market)

                    if len(candles) < 70:
                        print(f"{market}: insufficient candles")
                        continue

                    latest = candles[-1]
                    signal_epoch = latest["epoch"]
                    signal_id = f"{market}_{signal_epoch}"

                    if signal_id in known_ids:
                        continue

                    result = generate_strategy_signal(candles)
                    signal = result.get("signal", "NO SIGNAL")

                    candle_time = datetime.fromtimestamp(
                        signal_epoch, timezone.utc
                    ).strftime("%Y-%m-%d %H:%M:%S UTC")

                    print(f"\n{market} | {candle_time} | {signal}")
                    print(result.get("reason", ""))

                    if signal not in ("CALL", "PUT"):
                        continue

                    # Signal candle has closed.
                    # Entry is the next M1 candle open.
                    entry_epoch = signal_epoch + GRANULARITY

                    # For 3-minute expiry, use the close of the
                    # candle starting 2 minutes after entry.
                    exit_epoch = entry_epoch + (
                        EXPIRY_MINUTES - 1
                    ) * GRANULARITY

                    item = {
                        "signal_id": signal_id,
                        "market": market,
                        "signal": signal,
                        "signal_time_utc": candle_time,
                        "entry_epoch": entry_epoch,
                        "exit_epoch": exit_epoch,
                    }

                    state["pending"].append(item)
                    known_ids.add(signal_id)
                    save_state(state)

                    print(
                        f"Recorded {signal}; entry epoch={entry_epoch}; "
                        f"exit candle epoch={exit_epoch}"
                    )

                except Exception as error:
                    print(f"{market}: ERROR: {error}")

            save_state(state)
            print_summary(state)

            elapsed = time.time() - started
            time.sleep(max(5, SCAN_SECONDS - elapsed))

    except KeyboardInterrupt:
        print("\nForward test stopped.")
        print_summary(state)
        save_state(state)


if __name__ == "__main__":
    main()
