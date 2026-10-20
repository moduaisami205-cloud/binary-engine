
"""
BINARY ENGINE - FORWARD TEST REPORT
Reads forward_test_history.csv and displays test statistics.
REPORT ONLY: Does not place trades or modify the history file.
"""

import csv
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
HISTORY_FILE = BASE_DIR / "forward_test_history.csv"

MARKETS = ("R_10", "R_25", "R_50", "R_75", "R_100")

VALID_OUTCOMES = ("WIN", "LOSS", "DRAW", "PENDING")


def load_history():
    if not HISTORY_FILE.exists():
        print(f"[ERROR] History file not found: {HISTORY_FILE}")
        print("Run the scanner first to create the forward-test history.")
        return None

    try:
        with HISTORY_FILE.open("r", newline="", encoding="utf-8-sig") as file:
            reader = csv.DictReader(file)

            required = {"market", "direction", "outcome"}
            if not reader.fieldnames or not required.issubset(reader.fieldnames):
                print("[ERROR] History CSV is missing required columns.")
                return None

            rows = list(reader)

    except (OSError, csv.Error) as exc:
        print(f"[ERROR] Could not read history: {exc}")
        return None

    return rows


def summarize(rows):
    stats = {
        market: {
            "WIN": 0,
            "LOSS": 0,
            "DRAW": 0,
            "PENDING": 0,
            "UNKNOWN": 0,
        }
        for market in MARKETS
    }

    for row in rows:
        market = (row.get("market") or "").strip()
        outcome = (row.get("outcome") or "").strip().upper()

        if market not in stats:
            stats[market] = {
                "WIN": 0,
                "LOSS": 0,
                "DRAW": 0,
                "PENDING": 0,
                "UNKNOWN": 0,
            }

        if outcome in VALID_OUTCOMES:
            stats[market][outcome] += 1
        else:
            stats[market]["UNKNOWN"] += 1

    return stats


def win_rate(wins, losses):
    # Draws and pending signals are excluded.
    decided = wins + losses
    if decided == 0:
        return "N/A"

    return f"{wins / decided * 100:.2f}%"


def print_report(rows, stats):
    total = {
        "WIN": 0,
        "LOSS": 0,
        "DRAW": 0,
        "PENDING": 0,
        "UNKNOWN": 0,
    }

    print("\n" + "=" * 76)
    print("             BINARY ENGINE - FORWARD TEST REPORT")
    print("=" * 76)
    print(f"History file: {HISTORY_FILE.name}")
    print(f"Total recorded signals: {len(rows)}")
    print("-" * 76)

    header = (
        f"{'MARKET':<10}"
        f"{'WIN':>7}"
        f"{'LOSS':>7}"
        f"{'DRAW':>7}"
        f"{'PENDING':>10}"
        f"{'WIN RATE':>12}"
    )
    print(header)
    print("-" * 76)

    for market, values in stats.items():
        for outcome in total:
            total[outcome] += values[outcome]

        print(
            f"{market:<10}"
            f"{values['WIN']:>7}"
            f"{values['LOSS']:>7}"
            f"{values['DRAW']:>7}"
            f"{values['PENDING']:>10}"
            f"{win_rate(values['WIN'], values['LOSS']):>12}"
        )

    print("-" * 76)
    print(
        f"{'TOTAL':<10}"
        f"{total['WIN']:>7}"
        f"{total['LOSS']:>7}"
        f"{total['DRAW']:>7}"
        f"{total['PENDING']:>10}"
        f"{win_rate(total['WIN'], total['LOSS']):>12}"
    )

    print("-" * 76)
    print(f"Unknown/malformed outcomes: {total['UNKNOWN']}")
    print(
        "Completed signals (WIN + LOSS + DRAW): "
        f"{total['WIN'] + total['LOSS'] + total['DRAW']}"
    )
    print(
        "Decided signals (WIN + LOSS): "
        f"{total['WIN'] + total['LOSS']}"
    )
    print(
        "Pending signals: "
        f"{total['PENDING']}"
    )

    print("\nIMPORTANT:")
    print("- Win rate excludes DRAW and PENDING signals.")
    print("- This is historical price-direction testing, not profit.")
    print("- It does not include actual Deriv payouts, fees, or slippage.")
    print("- No trades are placed and the history file is not modified.")
    print("=" * 76)


def main():
    rows = load_history()

    if rows is None:
        return

    stats = summarize(rows)
    print_report(rows, stats)


if __name__ == "__main__":
    main()
