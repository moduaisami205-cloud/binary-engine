"""
BINARY ENGINE - STRATEGY FILTER COMPARISON
Strategy A: Current strategy.
Strategy B: Current strategy + Bollinger middle-band direction filter.
Timeframe: M1
TEST ONLY: No real trades are placed.
"""

from datetime import datetime, timezone

from engine.signals import generate_signal
from engine.compare_markets import (
    SYMBOLS,
    TIMEFRAME_SECONDS,
    SEGMENT_COUNT,
    get_historical_candles,
    empty_result,
    score_signal,
    hit_rate,
    print_result,
)


def calculate_filter_results(candles, start_index, end_index, filtered):
    result = empty_result()
    closes = [c["close"] for c in candles]
    opens = [c["open"] for c in candles]

    for i in range(
        max(39, start_index),
        min(end_index, len(candles) - 1),
    ):
        if (
            candles[i + 1]["epoch"] - candles[i]["epoch"]
            != TIMEFRAME_SECONDS
        ):
            result["skipped_gaps"] += 1
            continue

        signal = generate_signal(closes[:i + 1], opens[:i + 1])
        direction = signal.get("direction")

        if direction not in ("CALL", "PUT"):
            continue

        if filtered:
            middle = signal.get("bb_middle")
            if middle is None:
                continue

            price = closes[i]

            # CALL only above the Bollinger middle band.
            if direction == "CALL" and price <= middle:
                continue

            # PUT only below the Bollinger middle band.
            if direction == "PUT" and price >= middle:
                continue

        score_signal(
            result,
            direction,
            candles[i + 1]["open"],
            candles[i + 1]["close"],
        )

    return result


def main():
    try:
        print("Downloading historical candles for both markets...")
        now = int(datetime.now(timezone.utc).timestamp())
        histories = {}

        for symbol in SYMBOLS:
            histories[symbol] = get_historical_candles(symbol, now)

        common_epochs = sorted(
            {c["epoch"] for c in histories["R_50"]}
            & {c["epoch"] for c in histories["R_100"]}
        )

        if len(common_epochs) < 100:
            print("Not enough matching timestamps.")
            print("Common timestamps:", len(common_epochs))
            return

        aligned = {}
        for symbol in SYMBOLS:
            by_epoch = {
                c["epoch"]: c for c in histories[symbol]
            }
            aligned[symbol] = [
                by_epoch[epoch] for epoch in common_epochs
            ]

        count = len(common_epochs)
        print()
        print("=" * 60)
        print("STRATEGY FILTER COMPARISON - TEST ONLY")
        print("Matching candles:", count)
        print(
            "History begins:",
            datetime.fromtimestamp(
                common_epochs[0], timezone.utc
            ).strftime("%Y-%m-%d %H:%M UTC"),
        )
        print(
            "History ends:",
            datetime.fromtimestamp(
                common_epochs[-1], timezone.utc
            ).strftime("%Y-%m-%d %H:%M UTC"),
        )
        print("=" * 60)

        eligible_start = 39
        eligible_end = count - 1
        eligible_count = eligible_end - eligible_start

        boundaries = []
        for segment in range(SEGMENT_COUNT):
            start = (
                eligible_start
                + eligible_count * segment // SEGMENT_COUNT
            )
            end = (
                eligible_start
                + eligible_count * (segment + 1) // SEGMENT_COUNT
            )
            boundaries.append((start, end))

        for symbol in SYMBOLS:
            candles = aligned[symbol]
            print()
            print("#" * 60)
            print("MARKET:", symbol)

            for filtered, label in (
                (False, "STRATEGY A - CURRENT"),
                (True, "STRATEGY B - MIDDLE-BAND FILTER"),
            ):
                overall = calculate_filter_results(
                    candles, eligible_start, eligible_end, filtered
                )
                print_result(label, overall)

                for number, (start, end) in enumerate(
                    boundaries, 1
                ):
                    segment_result = calculate_filter_results(
                        candles, start, end, filtered
                    )
                    segment_start = datetime.fromtimestamp(
                        candles[start]["epoch"], timezone.utc
                    )
                    segment_end = datetime.fromtimestamp(
                        candles[min(end, count - 1)]["epoch"],
                        timezone.utc,
                    )
                    segment_label = (
                        f"{label} - SEGMENT {number}: "
                        f"{segment_start.strftime('%Y-%m-%d %H:%M')} to "
                        f"{segment_end.strftime('%Y-%m-%d %H:%M')} UTC"
                    )
                    print_result(segment_label, segment_result)

        print()
        print("=" * 60)
        print("TEST ONLY - NO TRADES WERE PLACED.")
        print("Hit rate measures next-candle direction, not option profit.")
        print("Historical results do not guarantee future performance.")
        print("The extra filter may reduce the number of signals.")
        print("=" * 60)

    except Exception as error:
        print("Filter comparison failed:")
        print(type(error).__name__ + ":", error)


if __name__ == "__main__":
    main()
