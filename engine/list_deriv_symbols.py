
import asyncio
import json
from pathlib import Path

import websockets

APP_ID = 1089
URL = (
    "wss://api.derivws.com/trading/v1/options/ws/public"
    f"?app_id={APP_ID}"
)

OUTPUT_FILE = Path(__file__).with_name("active_symbols_full.json")

KEYWORDS = (
    "volatility",
    "synthetic",
    "random",
    "crash",
    "boom",
    "range break",
)


async def main():
    print("BINARY ENGINE - DERIV SYMBOL DISCOVERY")
    print("Connecting to Deriv public API...")

    async with websockets.connect(URL, open_timeout=25) as ws:
        await ws.send(json.dumps({"active_symbols": "full"}))

        while True:
            response = json.loads(await asyncio.wait_for(ws.recv(), 30))

            if response.get("error"):
                print("API ERROR:", response["error"].get("message"))
                return

            if response.get("msg_type") == "active_symbols":
                break

        symbols = response.get("active_symbols", [])

        OUTPUT_FILE.write_text(
            json.dumps(response, indent=2),
            encoding="utf-8",
        )

        print(f"\nTotal active symbols returned: {len(symbols)}")

        matches = []

        for item in symbols:
            name = str(
                item.get("underlying_symbol_name")
                or item.get("display_name")
                or ""
            )
            symbol = str(
                item.get("underlying_symbol")
                or item.get("symbol")
                or ""
            )
            details = " ".join(
                str(item.get(key, ""))
                for key in (
                    "market",
                    "submarket",
                    "subgroup",
                    "underlying_symbol_type",
                    "symbol_type",
                )
            )

            searchable = f"{name} {symbol} {details}".lower()

            if any(word in searchable for word in KEYWORDS):
                matches.append((symbol, name, details))

        print("\n--- POSSIBLE SYNTHETIC / VOLATILITY SYMBOLS ---")

        if not matches:
            print("No matching symbols found. Check the saved JSON file.")
        else:
            for symbol, name, details in matches:
                print(f"{symbol} | {name} | {details}")

        print(f"\nMatching symbols: {len(matches)}")
        print(f"Full API response saved to: {OUTPUT_FILE}")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as exc:
        print(f"ERROR: {exc}")
