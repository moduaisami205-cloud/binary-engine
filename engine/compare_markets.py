"""
BINARY ENGINE - SAME-PERIOD MARKET COMPARISON
Markets: R_50 and R_100
Strategy: Bollinger Bands (22, 2) + MACD (13, 29, 8)
Timeframe: M1
TEST ONLY: No trades are placed.
"""

import json
import time
from datetime import datetime, timezone

from websocket import create_connection
from engine.signals import generate_signal


WS_URL = "wss://api.derivws.com/trading/v1/options/ws/public"
SYMBOLS = ("R_50", "R_100")
CANDLES_PER_CHUNK = 1000
MAX_CHUNKS = 5
TIMEFRAME_SECONDS = 60
SEGMENT_COUNT = 3


def request_candle_chunk(symbol, end_epoch, req_id):
    start_epoch = end_epoch - (
        (CANDLES_PER_CHUNK - 1) * TIMEFRAME_SECONDS
    )
    connection = None

    try:
        connection = create_connection(WS_URL, timeout=30)
        request = {
            "ticks_history": symbol,
            "start": start_epoch,
            "end": end_epoch,
            "granularity": TIMEFRAME_SECONDS,
            "style": "candles",
            "req_id": req_id,
        }
        connection.send(json.dumps(request))

        while True:
            response = json.loads(connection.recv())
            if response.get("req_id") == req_id:
                break

        if "error" in response:
            message = response["error"].get(
                "message", str(response["error"])
            )
            raise RuntimeError(f"{symbol}: {message}")

        return response.get("candles", [])

    finally:
        if connection is not None:
            connection.close()


def get_historical_candles(symbol, now):
    end_epoch = now - TIMEFRAME_SECONDS
    all_candles = {}
    chunks_received = 0

    for chunk_number in range(1, MAX_CHUNKS + 1):
        print(
            f"{symbol}: downloading chunk "
            f"{chunk_number}/{MAX_CHUNKS}..."
        )

        raw_candles = request_candle_chunk(
            symbol, end_epoch, 1000 + chunk_number
        )

        if not raw_candles:
            print(f"{symbol}: no more candles returned.")
            break

        chunks_received += 1

        for candle in raw_candles:
            epoch = int(candle["epoch"])
            if (
                epoch % TIMEFRAME_SECONDS == 0
                and epoch + TIMEFRAME_SECONDS <= now
            ):
                all_candles[epoch] = {
                    "epoch": epoch,
                    "open": float(candle["open"]),
                    "close": float(candle["close"]),
                }

        oldest_epoch = min(
            int(candle["epoch"]) for candle in raw_candles
        )

        if oldest_epoch >= end_epoch or len(raw_candles) < 2:
            break

        end_epoch = oldest_epoch - 1
        print(f"{symbol}: unique aligned candles: {len(all_candles)}")

    candles = [all_candles[e] for e in sorted(all_candles)]
    print(f"{symbol}: chunks={chunks_received}, candles={len(candles)}")
    return candles


def empty_result():
    result = {
        "calls": 0,
        "puts": 0,
        "wins": 0,
        "losses": 0,
        "ties": 0,
        "skipped_gaps": 0,
    }
    for prefix in ("call", "put"):
        for outcome in ("wins", "losses", "ties"):
            result[f"{prefix}_{outcome}"] = 0
    return result


def score_signal(result, direction, entry, expiry):
    prefix = "call" if direction == "CALL" else "put"
    result["calls" if direction == "CALL" else "puts"] += 1

    if expiry == entry:
        outcome = "ties"
    elif direction == "CALL":
        outcome = "wins" if expiry > entry else "losses"
    else:
        outcome = "wins" if expiry < entry else "losses"

    result[outcome] += 1
    result[f"{prefix}_{outcome}"] += 1


def calculate_results(candles, start_index, end_index):
    result = empty_result()
    closes = [c["close"] for c in candles]
    opens = [c["open"] for c in candles]

    for i in range(max(39, start_index), min(end_index, len(candles) - 1)):
        if candles[i + 1]["epoch"] - candles[i]["epoch"] != TIMEFRAME_SECONDS:
            result["skipped_gaps"] += 1
            continue

        signal = generate_signal(closes[:i + 1], opens[:i + 1])
        direction = signal.get("direction")
        if direction not in ("CALL", "PUT"):
            continue

        score_signal(
            result,
            direction,
            candles[i + 1]["open"],
            candles[i + 1]["close"],
        )

    return result


def hit_rate(wins, losses):
    total = wins + losses
    return round(wins / total * 100, 2) if total else None


def print_result(label, result):
    print()
    print("-" * 55)
    print(label)
    print("CALL signals:", result["calls"])
    print("PUT signals:", result["puts"])
    print("Total signals:", result["calls"] + result["puts"])
    print("Directional wins:", result["wins"])
    print("Directional losses:", result["losses"])
    print("Ties:", result["ties"])
    print("Skipped candle gaps:", result["skipped_gaps"])
    print("Overall directional hit rate:", hit_rate(
        result["wins"], result["losses"]
    ), "%")

    for name, prefix in (("CALL", "call"), ("PUT", "put")):
        wins = result[f"{prefix}_wins"]
        losses = result[f"{prefix}_losses"]
        ties = result[f"{prefix}_ties"]
        print(
            f"{name}: wins={wins}, losses={losses}, ties={ties}, "
            f"hit rate={hit_rate(wins, losses)}%"
        )


def main():
    try:
        print("Downloading the two markets using the same reference time...")
        now = int(time.time())
        histories = {}

        for symbol in SYMBOLS:
            histories[symbol] = get_historical_candles(symbol, now)

        # Compare only timestamps present in both markets.
        common_epochs = sorted(
            set(c["epoch"] for c in histories["R_50"])
            & set(c["epoch"] for c in histories["R_100"])
        )

        if len(common_epochs) < 100:
            print("Not enough matching timestamps for comparison.")
            print("Common timestamps:", len(common_epochs))
            return

        aligned = {}
        for symbol in SYMBOLS:
            by_epoch = {c["epoch"]: c for c in histories[symbol]}
            aligned[symbol] = [by_epoch[e] for e in common_epochs]

        count = len(common_epochs)
        start_time = datetime.fromtimestamp(
            common_epochs[0], timezone.utc
        )
        end_time = datetime.fromtimestamp(
            common_epochs[-1], timezone.utc
        )

        print()
        print("=" * 55)
        print("SAME-PERIOD MARKET COMPARISON - TEST ONLY")
        print("Matching candles:", count)
        print("History begins:", start_time.strftime("%Y-%m-%d %H:%M UTC"))
        print("History ends:", end_time.strftime("%Y-%m-%d %H:%M UTC"))
        print("=" * 55)

        # Split common timestamps into three chronological segments.
        eligible_start = 39
        eligible_end = count - 1
        eligible_count = eligible_end - eligible_start
        boundaries = []

        for segment in range(SEGMENT_COUNT):
            start = eligible_start + eligible_count * segment // SEGMENT_COUNT
            end = eligible_start + eligible_count * (segment + 1) // SEGMENT_COUNT
            boundaries.append((start, end))

        for symbol in SYMBOLS:
            candles = aligned[symbol]
            print()
            print("#" * 55)
            print("MARKET:", symbol)
            overall = calculate_results(candles, eligible_start, eligible_end)
            print_result("OVERALL RESULTS", overall)

            for number, (start, end) in enumerate(boundaries, 1):
                segment_result = calculate_results(candles, start, end)
                segment_start = datetime.fromtimestamp(
                    candles[start]["epoch"], timezone.utc
                )
                segment_end = datetime.fromtimestamp(
                    candles[min(end, count - 1)]["epoch"], timezone.utc
                )
                label = (
                    f"SEGMENT {number}: "
                    f"{segment_start.strftime('%Y-%m-%d %H:%M')} to "
                    f"{segment_end.strftime('%Y-%m-%d %H:%M')} UTC"
                )
                print_result(label, segment_result)

        print()
        print("=" * 55)
        print("TEST ONLY - NO TRADES WERE PLACED.")
        print("Directional results are not actual binary-option profits.")
        print("Historical results do not guarantee future performance.")
        print("Small samples can be misleading.")
        print("=" * 55)

    except Exception as error:
        print("Market comparison failed:")
        print(type(error).__name__ + ":", error)


if __name__ == "__main__":
    main()
