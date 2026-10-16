
def generate_signal():
    signal = {
        "symbol": "R_100",
        "direction": "CALL",
        "status": "TEST ONLY"
    }

    return signal


if __name__ == "__main__":
    result = generate_signal()

    print("=== BINARY ENGINE SIGNAL TEST ===")
    print("Market:", result["symbol"])
    print("Direction:", result["direction"])
    print("Status:", result["status"])
