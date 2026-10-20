from datetime import datetime, timezone
import json
import time

from websocket import create_connection
from engine.signals import generate_signal, SUPPORTED_MARKETS


WS_URL = "wss://api.derivws.com/trading/v1/options/ws/public"
M1_SECONDS = 60
M3_SECONDS = 180
M5_SECONDS = 300
CANDLES_PER_MARKET = 5000
MACD_WARMUP = 40


def utc_text(epoch):
    return datetime.fromtimestamp(
        int(epoch), timezone.utc
    ).strftime("%Y-%m-%d %H:%M UTC")


def get_candles(symbol, count=CANDLES_PER_MARKET):
    """Download recent CLOSED M1 candles from Deriv."""
    connection = None

    try:
        connection = create_connection(WS_URL, timeout=30)

        request = {
            "ticks_history": symbol,
            "count": count,
            "end": "latest",
            "granularity": M1_SECONDS,
            "style": "candles",
            "req_id": 1,
        }
        connection.send(json.dumps(request))

        while True:
            response = json.loads(connection.recv())
            if response.get("req_id") == 1:
                break

        if "error" in response:
            raise RuntimeError(
                response["error"].get("message", str(response["error"]))
            )

        now = int(time.time())
        candles = response.get("candles", [])
        unique = {}

        for candle in candles:
            epoch = int(candle["epoch"])
            if (
                epoch % M1_SECONDS == 0
                and epoch + M1_SECONDS <= now
            ):
                unique[epoch] = {
                    "epoch": epoch,
                    "open": float(candle["open"]),
                    "high": float(candle["high"]),
                    "low": float(candle["low"]),
                    "close": float(candle["close"]),
                }

        return [unique[e] for e in sorted(unique)]

    finally:
        if connection is not None:
            connection.close()


def aggregate_candles(m1_candles, timeframe_seconds):
    """Build aligned M3/M5 candles using completed M1 candles only."""
    buckets = {}

    for candle in m1_candles:
        epoch = candle["epoch"]
        bucket_epoch = epoch - epoch % timeframe_seconds
        bucket = buckets.setdefault(
            bucket_epoch,
            {
                "epoch": bucket_epoch,
                "open": candle["open"],
                "high": candle["high"],
                "low": candle["low"],
                "close": candle["close"],
                "count": 0,
            },
        )
        bucket["high"] = max(bucket["high"], candle["high"])
        bucket["low"] = min(bucket["low"], candle["low"])
        bucket["close"] = candle["close"]
        bucket["count"] += 1

    # Require every M1 candle in the bucket to be present.
    expected = timeframe_seconds // M1_SECONDS
    result = []

    for bucket_epoch in sorted(buckets):
        bucket = buckets[bucket_epoch]
        if bucket["count"] == expected:
            result.append({
                key: bucket[key]
                for key in ("epoch", "open", "high", "low", "close")
            })

    return result


def empty_stats():
    return {
        "signals": 0,
        "wins": 0,
        "losses": 0,
        "ties": 0,
        "gaps": 0,
    }


def score(stats, direction, entry_price, expiry_price):
    stats["signals"] += 1

    if expiry_price == entry_price:
        stats["ties"] += 1
    elif (
        direction == "CALL" and expiry_price > entry_price
    ) or (
        direction == "PUT" and expiry_price < entry_price
    ):
        stats["wins"] += 1
    else:
        stats["losses"] += 1


def print_stats(symbol, stats):
    decided = stats["wins"] + stats["losses"]
    hit_rate = (
        f"{stats['wins'] / decided * 100:.2f}%"
        if decided else "N/A"
    )

    print(f"\nMarket: {symbol}")
    print("Signals:", stats["signals"])
    print("Wins:", stats["wins"])
    print("Losses:", stats["losses"])
    print("Ties:", stats["ties"])
    print("Skipped candle gaps:", stats["gaps"])
    print("Directional hit rate:", hit_rate)


def backtest_market(symbol, m1_candles):
    stats = empty_stats()

    if len(m1_candles) < 100:
        print(f"{symbol}: Not enough M1 candles.")
        return stats

    m3_candles = aggregate_candles(m1_candles, M3_SECONDS)
    m5_candles = aggregate_candles(m1_candles, M5_SECONDS)

    m3_by_epoch = {c["epoch"]: c for c in m3_candles}
    m5_by_epoch = {c["epoch"]: c for c in m5_candles}

    m1_epochs = [c["epoch"] for c in m1_candles]
    closes_m1 = [c["close"] for c in m1_candles]
    opens_m1 = [c["open"] for c in m1_candles]

    for i in range(MACD_WARMUP, len(m1_candles) - 3):
        signal_candle = m1_candles[i]
        signal_epoch = signal_candle["epoch"]
        entry_candle = m1_candles[i + 1]
        expiry_candle = m1_candles[i + 3]

        # Require consecutive M1 candles through the 3-minute expiry.
        expected_epochs = [
            signal_epoch + M1_SECONDS,
            signal_epoch + 2 * M1_SECONDS,
            signal_epoch + 3 * M1_SECONDS,
        ]
        actual_epochs = [
            m1_epochs[i + 1],
            m1_epochs[i + 2],
            m1_epochs[i + 3],
        ]

        if actual_epochs != expected_epochs:
            stats["gaps"] += 1
            continue

        # Use only completed M3/M5 buckets available at signal close.
        m3_end = signal_epoch - signal_epoch % M3_SECONDS
        m5_end = signal_epoch - signal_epoch % M5_SECONDS

        # If signal candle is the first candle of a new bucket,
        # the bucket itself is not complete until later.
        if signal_epoch % M3_SECONDS == 0:
            m3_end -= M3_SECONDS
        if signal_epoch % M5_SECONDS == 0:
            m5_end -= M5_SECONDS

        usable_m3 = [
            c for c in m3_candles
            if c["epoch"] + M3_SECONDS <= signal_epoch + M1_SECONDS
            and c["epoch"] + M3_SECONDS <= m3_end + M3_SECONDS
        ]
        usable_m5 = [
            c for c in m5_candles
            if c["epoch"] + M5_SECONDS <= signal_epoch + M1_SECONDS
            and c["epoch"] + M5_SECONDS <= m5_end + M5_SECONDS
        ]

        if len(usable_m3) < 40 or len(usable_m5) < 40:
            continue

        result = generate_signal(
            closed_prices=closes_m1[:i + 1],
            closed_opens=opens_m1[:i + 1],
            closed_prices_m3=[c["close"] for c in usable_m3],
            closed_prices_m5=[c["close"] for c in usable_m5],
            symbol=symbol,
        )

        direction = result.get("direction")
        if direction not in ("CALL", "PUT"):
            continue

        # Entry is the next M1 candle open; expiry price is
        # the close exactly three minutes after entry.
        entry_price = entry_candle["open"]
        expiry_price = expiry_candle["close"]
        score(stats, direction, entry_price, expiry_price)

    return stats


def main():
    print("=" * 60)
    print(" BINARY ENGINE - MULTI-MARKET HISTORICAL BACKTEST")
    print("=" * 60)
    print("Markets:", ", ".join(SUPPORTED_MARKETS))
    print("Strategy: M5 + M3 + M1 / BB(22,2) / MACD(13,29,8)")
    print("Entry: next M1 candle open")
    print("Expiry measurement: close after 3 minutes")
    print("TEST ONLY - NO TRADES WILL BE PLACED.")
    print("Downloading recent historical candles...\n")

    all_stats = {}

    for symbol in SUPPORTED_MARKETS:
        try:
            print(f"Downloading {symbol}...")
            candles = get_candles(symbol)
            print(
                f"{symbol}: {len(candles)} closed M1 candles, "
                f"{utc_text(candles[0]['epoch']) if candles else 'no data'} "
                f"to {utc_text(candles[-1]['epoch']) if candles else ''}"
            )
            stats = backtest_market(symbol, candles)
            all_stats[symbol] = stats
            print_stats(symbol, stats)

        except Exception as exc:
            print(f"{symbol}: FAILED - {type(exc).__name__}: {exc}")
            all_stats[symbol] = None

    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)

    for symbol, stats in all_stats.items():
        if stats is None:
            print(f"{symbol}: no result (download/test failed)")
        else:
            decided = stats["wins"] + stats["losses"]
            hit_rate = (
                f"{stats['wins'] / decided * 100:.2f}%"
                if decided else "N/A"
            )
            print(
                f"{symbol}: signals={stats['signals']}, "
                f"wins={stats['wins']}, losses={stats['losses']}, "
                f"ties={stats['ties']}, hit_rate={hit_rate}"
            )

    print("\nNOTE:")
    print("- This is a historical directional test, not actual payout P/L.")
    print("- Historical results do not guarantee future performance.")
    print("- Verify the results before using any live account.")


if __name__ == "__main__":
    main()
