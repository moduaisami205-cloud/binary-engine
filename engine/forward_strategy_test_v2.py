
import asyncio
import csv
import json
import os
from datetime import datetime, timezone

import websockets
from engine.strategy_v2 import generate_strategy_v2


APP_ID = 1089
WS_URL = (
    "wss://api.derivws.com/trading/v1/options/ws/public"
    f"?app_id={APP_ID}"
)

MARKETS = ["R_10", "R_25", "R_50", "R_75", "R_100"]
EXPIRIES = [2, 3, 5]

M1_SECONDS = 60
M5_SECONDS = 300
CANDLE_COUNT = 120
POLL_SECONDS = 60

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
RESULTS_FILE = os.path.join(
    BASE_DIR, "forward_strategy_results_v2.csv"
)
STATE_FILE = os.path.join(
    BASE_DIR, "forward_strategy_state_v2.json"
)

CSV_COLUMNS = [
    "signal_id",
    "market",
    "direction",
    "expiry_minutes",
    "signal_epoch",
    "entry_epoch",
    "exit_epoch",
    "entry_price_estimate",
    "exit_price_estimate",
    "result",
    "recorded_at_utc",
]


def utc_now():
    return int(datetime.now(timezone.utc).timestamp())


def load_state():
    if not os.path.exists(STATE_FILE):
        return {"pending": [], "completed": []}

    try:
        with open(STATE_FILE, "r", encoding="utf-8") as file:
            state = json.load(file)

        state.setdefault("pending", [])
        state.setdefault("completed", [])

        # Ignore malformed legacy records rather than crashing.
        state["pending"] = [
            item for item in state["pending"]
            if isinstance(item, dict)
            and "market" in item
            and "signal_id" in item
            and "expiry_minutes" in item
            and "entry_epoch" in item
            and "exit_epoch" in item
        ]

        state["completed"] = [
            item for item in state["completed"]
            if isinstance(item, dict)
            and "signal_id" in item
            and "expiry_minutes" in item
            and "result" in item
        ]

        return state

    except (OSError, json.JSONDecodeError) as exc:
        print(f"State file error: {exc}")
        print("The existing state file has not been deleted.")
        return {"pending": [], "completed": []}


def save_state(state):
    temp_file = STATE_FILE + ".tmp"

    with open(temp_file, "w", encoding="utf-8") as file:
        json.dump(state, file, indent=2)

    os.replace(temp_file, STATE_FILE)


def ensure_csv():
    if not os.path.exists(RESULTS_FILE):
        with open(
            RESULTS_FILE, "w", newline="", encoding="utf-8"
        ) as file:
            csv.writer(file).writerow(CSV_COLUMNS)


async def request_candles(ws, market, granularity):
    request = {
        "ticks_history": market,
        "count": CANDLE_COUNT,
        "end": "latest",
        "style": "candles",
        "granularity": granularity,
    }

    await ws.send(json.dumps(request))

    while True:
        raw = await asyncio.wait_for(ws.recv(), timeout=30)
        response = json.loads(raw)

        if response.get("error"):
            message = response["error"].get(
                "message", "Unknown Deriv API error"
            )
            raise RuntimeError(message)

        if response.get("msg_type") == "candles":
            return response.get("candles", [])


def closed_candles(candles, seconds, cutoff=None):
    if cutoff is None:
        cutoff = utc_now()

    result = []

    for candle in candles:
        try:
            epoch = int(candle["epoch"])
            if epoch + seconds <= cutoff:
                result.append(candle)
        except (KeyError, TypeError, ValueError):
            continue

    return sorted(result, key=lambda candle: int(candle["epoch"]))


def already_recorded(state, signal_id):
    all_items = state["pending"] + state["completed"]
    return any(item.get("signal_id") == signal_id for item in all_items)


def print_summary(state):
    print("\n--- BINARY ENGINE STRATEGY V2 SUMMARY ---")
    print("Markets:", len(MARKETS))
    print("Expiry tests:", EXPIRIES)

    for expiry in EXPIRIES:
        completed = [
            item for item in state["completed"]
            if item.get("expiry_minutes") == expiry
        ]

        wins = sum(item.get("result") == "WIN" for item in completed)
        losses = sum(item.get("result") == "LOSS" for item in completed)
        draws = sum(item.get("result") == "DRAW" for item in completed)
        unavailable = sum(
            item.get("result") == "UNAVAILABLE"
            for item in completed
        )

        decided = wins + losses
        win_rate = wins / decided * 100 if decided else 0.0

        pending = sum(
            item.get("expiry_minutes") == expiry
            for item in state["pending"]
        )

        print(
            f"\nExpiry {expiry} minutes | Completed: {len(completed)} | "
            f"Wins: {wins} | Losses: {losses} | Draws: {draws} | "
            f"Unavailable: {unavailable}"
        )
        print(f"Win rate excluding draws: {win_rate:.2f}%")
        print(f"Pending: {pending}")

    print("\nTest only: directional estimates, not actual trade profits.")


async def settle_pending(ws, state):
    market_cache = {}

    for item in state["pending"][:]:
        if utc_now() < item["exit_epoch"] + M1_SECONDS:
            continue

        market = item["market"]

        try:
            if market not in market_cache:
                raw = await request_candles(
                    ws, market, M1_SECONDS
                )
                market_cache[market] = closed_candles(
                    raw, M1_SECONDS
                )

            candles = market_cache[market]

            entry_candle = next(
                (
                    candle for candle in candles
                    if int(candle["epoch"]) == item["entry_epoch"]
                ),
                None,
            )

            exit_candle = next(
                (
                    candle for candle in candles
                    if int(candle["epoch"]) == item["exit_epoch"]
                ),
                None,
            )

            if entry_candle is None or exit_candle is None:
                print(
                    f"{market} expiry {item['expiry_minutes']}m: "
                    "required candles not available yet; retrying."
                )
                continue

            entry_price = float(entry_candle["open"])
            exit_price = float(exit_candle["close"])

            if exit_price == entry_price:
                result = "DRAW"
            elif item["direction"] == "CALL":
                result = "WIN" if exit_price > entry_price else "LOSS"
            else:
                result = "WIN" if exit_price < entry_price else "LOSS"

            completed = {
                **item,
                "entry_price_estimate": entry_price,
                "exit_price_estimate": exit_price,
                "result": result,
            }

            with open(
                RESULTS_FILE, "a", newline="", encoding="utf-8"
            ) as file:
                writer = csv.writer(file)
                writer.writerow([
                    completed["signal_id"],
                    completed["market"],
                    completed["direction"],
                    completed["expiry_minutes"],
                    completed["signal_epoch"],
                    completed["entry_epoch"],
                    completed["exit_epoch"],
                    entry_price,
                    exit_price,
                    result,
                    datetime.now(timezone.utc).isoformat(),
                ])

            state["completed"].append(completed)
            state["pending"].remove(item)
            save_state(state)

            print(
                f"RESULT | {market} | {item['direction']} | "
                f"{item['expiry_minutes']}m | {result} | "
                f"Entry estimate={entry_price} | Exit estimate={exit_price}"
            )

        except Exception as exc:
            print(
                f"Settlement error | {market} | "
                f"{item['expiry_minutes']}m: {exc}"
            )


async def scan_market(ws, market, state):
    raw_m1 = await request_candles(ws, market, M1_SECONDS)
    raw_m5 = await request_candles(ws, market, M5_SECONDS)

    m1 = closed_candles(raw_m1, M1_SECONDS)

    if len(m1) < 70:
        print(f"{market}: not enough closed M1 candles.")
        return

    signal_candle = m1[-1]
    signal_epoch = int(signal_candle["epoch"])
    signal_close_time = signal_epoch + M1_SECONDS

    m5 = closed_candles(
        raw_m5, M5_SECONDS, cutoff=signal_close_time
    )

    if len(m5) < 70:
        print(f"{market}: not enough synchronized closed M5 candles.")
        return

    signal_prefix = f"{market}_{signal_epoch}"

    if any(
        item.get("signal_id", "").startswith(signal_prefix + "_")
        for item in state["pending"] + state["completed"]
    ):
        return

    result = generate_strategy_v2(m1, m5)
    direction = result.get("signal", "NO SIGNAL")

    stamp = datetime.fromtimestamp(
        signal_epoch, timezone.utc
    ).strftime("%Y-%m-%d %H:%M:%S UTC")

    print(f"\n{market} | {stamp} | {direction}")
    print(result.get("reason", ""))

    if direction not in ("CALL", "PUT"):
        return

    entry_epoch = signal_epoch + M1_SECONDS

    for expiry in EXPIRIES:
        test_id = f"{signal_prefix}_{expiry}m"

        if already_recorded(state, test_id):
            continue

        # Entry is approximated by the next M1 candle's open.
        # Exit is the close of the candle ending N minutes later.
        exit_epoch = entry_epoch + expiry * M1_SECONDS - M1_SECONDS

        state["pending"].append({
            "signal_id": test_id,
            "market": market,
            "direction": direction,
            "signal_epoch": signal_epoch,
            "entry_epoch": entry_epoch,
            "exit_epoch": exit_epoch,
            "expiry_minutes": expiry,
        })

        print(f"Recorded test | {direction} | Expiry {expiry}m")

    save_state(state)


async def main():
    ensure_csv()
    state = load_state()

    print("BINARY ENGINE - STRATEGY V2 FORWARD TEST")
    print("Markets:", ", ".join(MARKETS))
    print("Timeframes: M5 trend + M1 entry")
    print("Expiry tests:", EXPIRIES)
    print("No real trades will be placed.")
    print("Press Ctrl+C to stop.\n")

    while True:
        try:
            async with websockets.connect(
                WS_URL,
                open_timeout=20,
                close_timeout=5,
            ) as ws:
                await settle_pending(ws, state)

                for market in MARKETS:
                    try:
                        await scan_market(ws, market, state)
                    except Exception as exc:
                        print(f"{market}: scan error: {exc}")

                print_summary(state)

        except Exception as exc:
            print(f"Connection error: {exc}")

        await asyncio.sleep(POLL_SECONDS)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nStrategy V2 tester stopped.")
        print_summary(load_state())
