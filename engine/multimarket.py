
def update_signal_history(symbol, candles):
    """
    Estimate outcomes using closed M1 candles.
    Price-direction estimate only; not an official Deriv payout.
    """

    candles_by_epoch = {
        int(candle["epoch"]): candle
        for candle in candles
    }

    rows = read_history()
    changed = False

    for row in rows:
        if row.get("market") != symbol:
            continue

        if row.get("outcome") != "PENDING":
            continue

        direction = row.get("direction")
        if direction not in ("CALL", "PUT"):
            continue

        try:
            signal_epoch = int(row["signal_epoch"])
        except (ValueError, TypeError, KeyError):
            print("[HISTORY WARNING] Invalid signal timestamp; skipped.")
            continue

        # Entry is the next M1 candle after the signal candle.
        entry_epoch = signal_epoch + M1_SECONDS

        # A 3-minute expiry ends at entry + 180 seconds.
        # The final expiry candle opens 60 seconds before expiry.
        expiry_candle_epoch = entry_epoch + EXPIRY_SECONDS - M1_SECONDS

        # Require the entry candle and the two following M1 candles.
        required_epochs = [
            entry_epoch,
            entry_epoch + M1_SECONDS,
            expiry_candle_epoch,
        ]

        if not all(epoch in candles_by_epoch for epoch in required_epochs):
            continue

        # Ensure the candles are consecutive.
        if any(
            required_epochs[i + 1] - required_epochs[i] != M1_SECONDS
            for i in range(len(required_epochs) - 1)
        ):
            continue

        # Do not score until the expiry candle has fully closed.
        now = int(time.time())
        if expiry_candle_epoch + M1_SECONDS > now:
            continue

        entry_candle = candles_by_epoch[entry_epoch]
        expiry_candle = candles_by_epoch[expiry_candle_epoch]

        try:
            entry_price = float(entry_candle["open"])
            expiry_price = float(expiry_candle["close"])
        except (ValueError, TypeError, KeyError):
            print("[HISTORY WARNING] Invalid candle prices; skipped.")
            continue

        if expiry_price == entry_price:
            outcome = "DRAW"
        elif direction == "CALL":
            outcome = "WIN" if expiry_price > entry_price else "LOSS"
        else:
            outcome = "WIN" if expiry_price < entry_price else "LOSS"

        row["entry_price"] = entry_price
        row["expiry_price"] = expiry_price
        row["outcome"] = outcome
        changed = True

        print(
            f"[RESULT] {symbol} {direction} | "
            f"Entry={entry_price} | "
            f"Expiry={expiry_price} | {outcome}"
        )

    if changed:
        write_history(rows)
