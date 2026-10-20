import concurrent.futures
import csv
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
from dotenv import load_dotenv
from websocket import create_connection

from engine.signals import generate_signal


# ============================================================
# BINARY ENGINE - VOLATILITY FORWARD TEST
# ============================================================
#
# Strategy:
#   Bollinger Bands: 22, 2
#   MACD: 13, 29, 8
#   Timeframe: M1
#   Entry: NEXT M1 CANDLE
#   Expiry: 3 MINUTES
#
# TEST ONLY - NO REAL TRADES
# ============================================================


BASE_DIR = Path(__file__).resolve().parent.parent
ENGINE_DIR = BASE_DIR / "engine"

load_dotenv(BASE_DIR / ".env")


# Modern Deriv public market-data endpoint
WS_URL = "wss://api.derivws.com/trading/v1/options/ws/public"

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()


# ============================================================
# SETTINGS
# ============================================================

TIMEFRAME_SECONDS = 60
EXPIRY_MINUTES = 3
CANDLE_COUNT = 120

SCAN_INTERVAL = 60
MARKET_REFRESH_SECONDS = 1800

# Keep this low to reduce Deriv 429 rate-limit errors.
MAX_WORKERS = 2

WS_RETRIES = 3
WS_RETRY_DELAYS = (2, 5, 10)


# ============================================================
# VOLATILITY MARKETS
# ============================================================

VOLATILITY_MARKETS = {
    "R_10",
    "R_25",
    "R_50",
    "R_75",
    "R_100",
}


# ============================================================
# FILES
# ============================================================

RESULTS_FILE = ENGINE_DIR / "forward_volatility_3m_results.csv"
STATE_FILE = ENGINE_DIR / "forward_volatility_3m_state.json"

STRATEGY_NAME = "MACD_BB_ZERO_CROSS_3M"


FIELDS = [
    "signal_id",
    "market",
    "strategy",
    "direction",
    "signal_epoch",
    "signal_time_utc",
    "signal_price",
    "bb_middle",
    "entry_epoch",
    "entry_time_utc",
    "expiry_epoch",
    "expiry_time_utc",
    "entry_price",
    "expiry_price",
    "outcome",
]


# ============================================================
# TIME
# ============================================================

def utc_time(epoch):
    return datetime.fromtimestamp(
        int(epoch),
        timezone.utc,
    ).strftime("%Y-%m-%d %H:%M:%S UTC")


# ============================================================
# DERIV WEBSOCKET REQUEST
# ============================================================

def ws_request(request, timeout=15):
    last_error = None

    for attempt in range(WS_RETRIES):
        connection = None

        try:
            connection = create_connection(
                WS_URL,
                timeout=timeout,
                suppress_origin=True,
            )

            connection.send(json.dumps(request))

            response = json.loads(connection.recv())

            if response.get("error"):
                error = response["error"]
                message = error.get(
                    "message",
                    "Unknown Deriv API error",
                )

                raise RuntimeError(message)

            return response

        except Exception as error:
            last_error = error

            error_text = str(error)

            print(
                f"Deriv request failed "
                f"(attempt {attempt + 1}/{WS_RETRIES}): "
                f"{error_text}"
            )

            if attempt < WS_RETRIES - 1:
                delay = WS_RETRY_DELAYS[attempt]

                print(
                    f"Waiting {delay}s before retry..."
                )

                time.sleep(delay)

        finally:
            if connection is not None:
                try:
                    connection.close()
                except Exception:
                    pass

    raise RuntimeError(
        f"Deriv request failed after {WS_RETRIES} attempts: "
        f"{last_error}"
    )


# ============================================================
# MARKET DISCOVERY
# ============================================================

def discover_markets():
    """
    Discover Deriv active symbols, but keep only the
    requested Volatility Index markets.
    """

    response = ws_request(
        {"active_symbols": "brief"},
        timeout=20,
    )

    symbols = response.get("active_symbols")

    if not isinstance(symbols, list):
        symbols = response.get("data")

    if not isinstance(symbols, list):
        raise RuntimeError(
            "Deriv response did not contain an active_symbols list."
        )

    found = []
    seen = set()

    for item in symbols:
        if not isinstance(item, dict):
            continue

        symbol = str(
            item.get("underlying_symbol")
            or item.get("symbol")
            or ""
        ).strip()

        if not symbol:
            continue

        if symbol not in VOLATILITY_MARKETS:
            continue

        if symbol in seen:
            continue

        suspended = item.get(
            "is_trading_suspended",
            0,
        )

        if suspended is True:
            continue

        if str(suspended).lower() in (
            "1",
            "true",
            "yes",
        ):
            continue

        seen.add(symbol)
        found.append(symbol)

    if not found:
        raise RuntimeError(
            "None of the requested Volatility markets "
            "are currently active."
        )

    return sorted(found)


# ============================================================
# FETCH M1 CANDLES
# ============================================================

def fetch_candles(symbol):
    response = ws_request(
        {
            "ticks_history": symbol,
            "end": "latest",
            "count": CANDLE_COUNT,
            "style": "candles",
            "granularity": TIMEFRAME_SECONDS,
        },
        timeout=20,
    )

    raw_candles = response.get(
        "candles",
        [],
    )

    now_epoch = int(time.time())

    candles_by_epoch = {}

    for candle in raw_candles:
        epoch = int(candle["epoch"])

        # Only fully closed candles.
        if (
            epoch % TIMEFRAME_SECONDS != 0
            or epoch + TIMEFRAME_SECONDS > now_epoch
        ):
            continue

        candles_by_epoch[epoch] = {
            "epoch": epoch,
            "open": float(candle["open"]),
            "high": float(candle["high"]),
            "low": float(candle["low"]),
            "close": float(candle["close"]),
        }

    return sorted(
        candles_by_epoch.values(),
        key=lambda item: item["epoch"],
    )


# ============================================================
# STATE
# ============================================================

def load_state():
    if not STATE_FILE.exists():
        return {}

    try:
        with STATE_FILE.open(
            "r",
            encoding="utf-8",
        ) as file:
            data = json.load(file)

        return data if isinstance(data, dict) else {}

    except (
        OSError,
        json.JSONDecodeError,
    ):
        print(
            "WARNING: Could not read state file. "
            "Starting with fresh state."
        )

        return {}


def save_state(state):
    temp = STATE_FILE.with_suffix(".tmp")

    with temp.open(
        "w",
        encoding="utf-8",
    ) as file:
        json.dump(
            state,
            file,
            indent=2,
        )

    temp.replace(STATE_FILE)


# ============================================================
# RESULTS
# ============================================================

def load_results():
    if not RESULTS_FILE.exists():
        return []

    with RESULTS_FILE.open(
        "r",
        newline="",
        encoding="utf-8-sig",
    ) as file:
        return list(csv.DictReader(file))


def save_results(rows):
    temp = RESULTS_FILE.with_suffix(".tmp")

    with temp.open(
        "w",
        newline="",
        encoding="utf-8",
    ) as file:
        writer = csv.DictWriter(
            file,
            fieldnames=FIELDS,
        )

        writer.writeheader()
        writer.writerows(rows)

    temp.replace(RESULTS_FILE)


# ============================================================
# SIGNAL ROW
# ============================================================

def make_row(
    symbol,
    direction,
    candle,
    signal,
):
    signal_epoch = int(candle["epoch"])

    # Entry = NEXT M1 candle
    entry_epoch = (
        signal_epoch
        + TIMEFRAME_SECONDS
    )

    # Expiry = 3 minutes after entry
    expiry_epoch = (
        entry_epoch
        + EXPIRY_MINUTES * TIMEFRAME_SECONDS
    )

    return {
        "signal_id": (
            f"{symbol}_"
            f"{STRATEGY_NAME}_"
            f"{signal_epoch}_"
            f"{direction}"
        ),

        "market": symbol,
        "strategy": STRATEGY_NAME,
        "direction": direction,

        "signal_epoch": signal_epoch,
        "signal_time_utc": utc_time(
            signal_epoch
        ),

        "signal_price": candle["close"],

        "bb_middle": signal.get(
            "bb_middle",
            "",
        ),

        "entry_epoch": entry_epoch,
        "entry_time_utc": utc_time(
            entry_epoch
        ),

        "expiry_epoch": expiry_epoch,
        "expiry_time_utc": utc_time(
            expiry_epoch
        ),

        "entry_price": "",
        "expiry_price": "",
        "outcome": "",
    }


# ============================================================
# TELEGRAM
# ============================================================

def send_telegram_alert(
    symbol,
    candle,
    row,
):
    if (
        not TELEGRAM_BOT_TOKEN
        or not TELEGRAM_CHAT_ID
    ):
        print(
            "TELEGRAM WARNING: "
            "TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID "
            "is not configured."
        )

        return

    message = (
        "🔔 WELCOME TO MR AI BINARY ENGINE SIGNAL\n\n"

        f"📊 Market: {symbol}\n"
        "⏱ Timeframe: M1\n"
        f"📈 Signal: {row['direction']}\n"
        f"💰 Signal Price: {candle['close']}\n"

        f"🕯 Closed Candle: "
        f"{utc_time(candle['epoch'])}\n"

        f"🚀 Entry: NEXT M1 CANDLE\n"
        f"⏳ Expiry: {EXPIRY_MINUTES} MINUTES\n"
        f"🎯 Expiry Time: {row['expiry_time_utc']}\n\n"

        "📌 Strategy:\n"
        "Bollinger Bands (22, 2)\n"
        "MACD (13, 29, 8)\n"
        "MACD Cross + Histogram Zero Cross\n"
        "Price strictly inside Bollinger Bands\n\n"

        "⚠️ GARGADI / DISCLAIMER:\n"
        "Wannan signal TEST ne kawai kuma ba garanti bane "
        "na samun riba.\n"
        "Trading yana da hadari kuma sakamakon baya tabbata.\n"
        "This signal is for testing/educational purposes only "
        "and does not guarantee profit.\n"
        "No real trade is placed by this tester."
    )

    url = (
        f"https://api.telegram.org/"
        f"bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    )

    try:
        response = requests.post(
            url,
            json={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": message,
            },
            timeout=15,
        )

        try:
            result = response.json()
        except ValueError:
            result = {}

        if (
            response.ok
            and result.get("ok") is True
        ):
            print(
                f"TELEGRAM SENT: "
                f"{symbol} {row['direction']}"
            )
        else:
            print(
                "TELEGRAM ERROR: "
                f"HTTP {response.status_code}: "
                f"{result.get('description', response.text[:200])}"
            )

    except requests.RequestException as error:
        print(
            f"TELEGRAM ERROR: {error}"
        )


# ============================================================
# RESOLVE PENDING RESULTS
# ============================================================

def update_pending_results(
    rows,
    symbol,
    candles,
):
    by_epoch = {
        int(candle["epoch"]): candle
        for candle in candles
    }

    changed = False

    for row in rows:
        if row["market"] != symbol:
            continue

        if row["outcome"]:
            continue

        entry_epoch = int(
            row["entry_epoch"]
        )

        expiry_epoch = int(
            row["expiry_epoch"]
        )

        entry_candle = by_epoch.get(
            entry_epoch
        )

        # Candle ending at expiry time.
        expiry_candle = by_epoch.get(
            expiry_epoch - TIMEFRAME_SECONDS
        )

        if (
            entry_candle is None
            or expiry_candle is None
        ):
            continue

        # Entry = opening price of next candle.
        entry_price = float(
            entry_candle["open"]
        )

        # Expiry = close price at expiry.
        expiry_price = float(
            expiry_candle["close"]
        )

        if expiry_price == entry_price:
            outcome = "DRAW"

        elif row["direction"] == "CALL":
            outcome = (
                "WIN"
                if expiry_price > entry_price
                else "LOSS"
            )

        else:
            outcome = (
                "WIN"
                if expiry_price < entry_price
                else "LOSS"
            )

        row["entry_price"] = entry_price
        row["expiry_price"] = expiry_price
        row["outcome"] = outcome

        changed = True

        print(
            f"RESOLVED: "
            f"{symbol} | "
            f"{row['direction']} | "
            f"{EXPIRY_MINUTES}m | "
            f"{outcome}"
        )

    return changed


# ============================================================
# PROCESS NEW CANDLES
# ============================================================

def process_new_candles(
    symbol,
    candles,
    state,
    rows,
):
    if not candles:
        print(
            f"{symbol}: "
            "no closed candles available."
        )

        return

    latest_epoch = int(
        candles[-1]["epoch"]
    )

    state_key = (
        f"{STRATEGY_NAME}_"
        f"{symbol}_"
        "last_processed_epoch"
    )

    print(
        f"{symbol}: "
        f"latest closed candle "
        f"{utc_time(latest_epoch)}"
    )

    if state_key not in state:
        # Start forward test from the current
        # latest closed candle.
        state[state_key] = (
            latest_epoch
            - TIMEFRAME_SECONDS
        )

        print(
            f"{symbol}: "
            f"initialized at "
            f"{utc_time(latest_epoch)}"
        )

    last_processed = int(
        state[state_key]
    )

    new_candles = [
        candle
        for candle in candles
        if int(candle["epoch"])
        > last_processed
    ]

    known_ids = {
        row["signal_id"]
        for row in rows
    }

    for candle in new_candles:
        epoch = int(
            candle["epoch"]
        )

        history = [
            item
            for item in candles
            if int(item["epoch"]) <= epoch
        ]

        closes = [
            item["close"]
            for item in history
        ]

        opens = [
            item["open"]
            for item in history
        ]

        if len(closes) < 40:
            state[state_key] = epoch
            continue

        signal = generate_signal(
            closes,
            opens,
        )

        direction = (
            signal.get("direction")
            if isinstance(signal, dict)
            else None
        )

        if direction in (
            "CALL",
            "PUT",
        ):
            row = make_row(
                symbol,
                direction,
                candle,
                signal,
            )

            if row["signal_id"] not in known_ids:
                rows.append(row)
                known_ids.add(
                    row["signal_id"]
                )

                print(
                    "🔥 NEW SIGNAL: "
                    f"{symbol} | "
                    f"{direction} | "
                    f"{utc_time(epoch)} | "
                    "Entry NEXT M1 | "
                    "Expiry 3m"
                )

                send_telegram_alert(
                    symbol,
                    candle,
                    row,
                )

        state[state_key] = epoch


# ============================================================
# SUMMARY
# ============================================================

def print_summary(
    rows,
    markets,
):
    print(
        "\n"
        + "=" * 72
    )

    print(
        "BINARY ENGINE — "
        "VOLATILITY 3-MINUTE FORWARD TEST"
    )

    print(
        "=" * 72
    )

    selected = [
        row
        for row in rows
        if row.get("strategy")
        == STRATEGY_NAME
    ]

    total_signals = 0
    total_wins = 0
    total_losses = 0
    total_draws = 0
    total_pending = 0

    for symbol in markets:
        items = [
            row
            for row in selected
            if row["market"] == symbol
        ]

        if not items:
            continue

        wins = sum(
            row["outcome"] == "WIN"
            for row in items
        )

        losses = sum(
            row["outcome"] == "LOSS"
            for row in items
        )

        draws = sum(
            row["outcome"] == "DRAW"
            for row in items
        )

        pending = sum(
            not row["outcome"]
            for row in items
        )

        resolved = (
            wins
            + losses
        )

        rate = (
            f"{wins / resolved * 100:.2f}%"
            if resolved
            else "N/A"
        )

        total_signals += len(items)
        total_wins += wins
        total_losses += losses
        total_draws += draws
        total_pending += pending

        print(
            f"{symbol}: "
            f"signals={len(items)}, "
            f"wins={wins}, "
            f"losses={losses}, "
            f"draws={draws}, "
            f"pending={pending}, "
            f"hit_rate={rate}"
        )

    total_resolved = (
        total_wins
        + total_losses
    )

    total_rate = (
        f"{total_wins / total_resolved * 100:.2f}%"
        if total_resolved
        else "N/A"
    )

    print("-" * 72)

    print(
        f"TOTAL: "
        f"signals={total_signals}, "
        f"wins={total_wins}, "
        f"losses={total_losses}, "
        f"draws={total_draws}, "
        f"pending={total_pending}, "
        f"hit_rate={total_rate}"
    )

    print(
        f"Volatility markets scanned: "
        f"{len(markets)}"
    )

    print(
        "TEST ONLY — NO REAL TRADES."
    )

    print(
        "Directional hit rate is NOT a guarantee "
        "of binary-options profitability."
    )

    print(
        "=" * 72
        + "\n"
    )


# ============================================================
# MAIN
# ============================================================

def main():
    ENGINE_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    if not RESULTS_FILE.exists():
        save_results([])

    print(
        "================================================"
    )

    print(
        "BINARY ENGINE — VOLATILITY FORWARD TEST"
    )

    print(
        "Strategy: MACD + Bollinger"
    )

    print(
        "MACD: 13, 29, 8"
    )

    print(
        "Bollinger: 22, 2"
    )

    print(
        "Timeframe: M1"
    )

    print(
        "Entry: NEXT M1 CANDLE"
    )

    print(
        "Expiry: 3 MINUTES"
    )

    print(
        "Mode: TEST ONLY — NO REAL TRADES"
    )

    print(
        "================================================"
    )

    print(
        "Telegram: "
        + (
            "CONFIGURED"
            if (
                TELEGRAM_BOT_TOKEN
                and TELEGRAM_CHAT_ID
            )
            else "NOT CONFIGURED"
        )
    )

    print(
        f"Markets: {', '.join(sorted(VOLATILITY_MARKETS))}"
    )

    print(
        f"Deriv endpoint: {WS_URL}"
    )

    print(
        f"Results: {RESULTS_FILE}"
    )

    print(
        f"State: {STATE_FILE}"
    )

    print(
        "Press Ctrl+C to stop.\n"
    )

    state = load_state()
    rows = load_results()

    markets = []
    last_refresh = 0

    while True:
        cycle_start = time.time()

        # ----------------------------------------------------
        # MARKET REFRESH
        # ----------------------------------------------------

        if (
            not markets
            or cycle_start - last_refresh
            >= MARKET_REFRESH_SECONDS
        ):
            try:
                markets = discover_markets()

                last_refresh = cycle_start

                print(
                    "Active Volatility markets: "
                    + ", ".join(markets)
                )

            except Exception as error:
                print(
                    "MARKET DISCOVERY ERROR: "
                    f"{error}"
                )

                print(
                    "Retrying discovery next cycle..."
                )

                time.sleep(15)
                continue

        # ----------------------------------------------------
        # FETCH CANDLES
        # ----------------------------------------------------

        with concurrent.futures.ThreadPoolExecutor(
            max_workers=MAX_WORKERS
        ) as pool:

            futures = {
                pool.submit(
                    fetch_candles,
                    symbol,
                ): symbol
                for symbol in markets
            }

            for future in concurrent.futures.as_completed(
                futures
            ):
                symbol = futures[future]

                try:
                    candles = future.result()

                    if not candles:
                        print(
                            f"{symbol}: "
                            "no closed candles."
                        )

                        continue

                    process_new_candles(
                        symbol,
                        candles,
                        state,
                        rows,
                    )

                    update_pending_results(
                        rows,
                        symbol,
                        candles,
                    )

                except Exception as error:
                    print(
                        f"{symbol}: "
                        f"scan failed — {error}"
                    )

        # ----------------------------------------------------
        # SAVE
        # ----------------------------------------------------

        save_results(rows)
        save_state(state)

        # ----------------------------------------------------
        # SUMMARY
        # ----------------------------------------------------

        print_summary(
            rows,
            markets,
        )

        elapsed = (
            time.time()
            - cycle_start
        )

        wait_seconds = max(
            5,
            SCAN_INTERVAL
            - int(elapsed),
        )

        print(
            f"Next scan in about "
            f"{wait_seconds} seconds.\n"
        )

        time.sleep(
            wait_seconds
        )


# ============================================================
# START
# ============================================================

if __name__ == "__main__":
    try:
        main()

    except KeyboardInterrupt:
        print(
            "\nForward test stopped by user."
        )