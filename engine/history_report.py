import csv
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HISTORY_FILE = ROOT / "signal_history.csv"
OUTCOMES = ("WIN", "LOSS", "DRAW", "PENDING")
DIRECTIONS = ("CALL", "PUT")
TARGET_COMPLETED = 100


def new_stats():
    return {outcome: 0 for outcome in OUTCOMES}


def win_rate(stats):
    decisive = stats["WIN"] + stats["LOSS"]
    if decisive == 0:
        return "N/A"
    return f'{stats["WIN"] / decisive * 100:.2f}%'


def main():
    if not HISTORY_FILE.exists():
        print("ERROR: signal_history.csv bai samu ba.")
        return

    by_market_direction = defaultdict(new_stats)
    totals = new_stats()
    total_rows = 0

    with HISTORY_FILE.open("r", newline="", encoding="utf-8-sig") as file:
        reader = csv.DictReader(file)

        required = {"market", "direction", "outcome"}
        if not reader.fieldnames or not required.issubset(reader.fieldnames):
            print("ERROR: CSV bai da ginshikan market, direction, outcome.")
            return

        for row in reader:
            market = (row.get("market") or "UNKNOWN").strip() or "UNKNOWN"
            direction = (row.get("direction") or "").strip().upper()
            outcome = (row.get("outcome") or "PENDING").strip().upper()

            if direction not in DIRECTIONS or outcome not in OUTCOMES:
                continue

            by_market_direction[(market, direction)][outcome] += 1
            totals[outcome] += 1
            total_rows += 1

    completed = totals["WIN"] + totals["LOSS"] + totals["DRAW"]
    remaining = max(0, TARGET_COMPLETED - completed)
    progress = min(100, completed / TARGET_COMPLETED * 100)

    print("\n" + "=" * 86)
    print("BINARY ENGINE - CALL / PUT HISTORY REPORT")
    print("=" * 86)
    print(f"Valid signal records: {total_rows}")
    print(f"Completed: {completed} | Pending: {totals['PENDING']}")
    print(
        f"WIN: {totals['WIN']} | LOSS: {totals['LOSS']} | "
        f"DRAW: {totals['DRAW']}"
    )
    print(f"Overall decisive win rate: {win_rate(totals)}")
    print()
    print(f"Progress toward {TARGET_COMPLETED} completed signals:")
    print(f"{completed}/{TARGET_COMPLETED} ({progress:.1f}%)")
    if remaining:
        print(f"Remaining to target: {remaining}")
    else:
        print("Target reached. Continue collecting data for further testing.")

    print("-" * 86)
    print(
        f"{'MARKET':<12} {'DIRECTION':<10} {'DONE':>5} "
        f"{'WIN':>4} {'LOSS':>5} {'DRAW':>5} "
        f"{'PENDING':>8} {'WIN RATE':>10}"
    )
    print("-" * 86)

    for market, direction in sorted(by_market_direction):
        stats = by_market_direction[(market, direction)]
        direction_completed = (
            stats["WIN"] + stats["LOSS"] + stats["DRAW"]
        )
        print(
            f"{market:<12} {direction:<10} {direction_completed:>5} "
            f"{stats['WIN']:>4} {stats['LOSS']:>5} "
            f"{stats['DRAW']:>5} {stats['PENDING']:>8} "
            f"{win_rate(stats):>10}"
        )

    print("-" * 86)
    print("DONE = completed signals for that market and direction.")
    print("DRAW is excluded from win-rate calculation.")
    print("This is candle-direction testing, not actual binary-contract profit.")
    print("Small samples do not establish a reliable strategy.")
    print("=" * 86 + "\n")


if __name__ == "__main__":
    main()
