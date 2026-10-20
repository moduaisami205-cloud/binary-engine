
import json
from websocket import create_connection, WebSocketTimeoutException
from websocket import WebSocketConnectionClosedException


import json
from websocket import create_connection, WebSocketTimeoutException
from websocket import WebSocketConnectionClosedException

APP_ID = 1089

WS_URL = f"wss://ws.derivws.com/websockets/v3?app_id={APP_ID}"



def main():
    connection = None

    try:
        print("=" * 45)
        print("          BINARY ENGINE")
        print("        DERIV CONNECTION TEST")
        print("=" * 45)
        print("Connecting to Deriv...")

        connection = create_connection(
            WS_URL,
            timeout=20,
            origin="https://app.deriv.com",
        )

        print("Connection: SUCCESS")
        print("Requesting available markets...")

        request = {
            "active_symbols": "brief",
            "product_type": "basic",
            "req_id": 1,
        }

        connection.send(json.dumps(request))

        while True:
            raw_response = connection.recv()
            response = json.loads(raw_response)

            if response.get("req_id") != 1:
                continue

            if "error" in response:
                error = response["error"]
                print("Deriv API error:")
                print(error.get("message", error))
                break

            markets = response.get("active_symbols", [])

            if not markets:
                print("No markets returned.")
                print(response)
                break

            print()
            print("Connection and market request successful!")
            print("Number of markets:", len(markets))
            print()
            print("First 20 markets:")
            print("-" * 45)

            for market in markets[:20]:
                name = market.get(
                    "display_name",
                    "Unknown market",
                )
                symbol = market.get("symbol", "Unknown")

                print(f"{name} | Symbol: {symbol}")

            print("-" * 45)
            print("Mode: READ ONLY - NO TRADES")
            break

    except WebSocketTimeoutException:
        print("ERROR: Connection timed out.")
        print("Check your internet connection and try again.")

    except WebSocketConnectionClosedException:
        print("ERROR: Deriv closed the connection.")

    except Exception as error:
        print("Connection test failed:")
        print(type(error).__name__ + ":", error)

    finally:
        if connection is not None:
            connection.close()
            print("Connection closed.")


if __name__ == "__main__":
    main()
