
import os
import sys
import requests
from dotenv import load_dotenv

load_dotenv()

token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
chat_id = "8873525830"

if not token:
    print("KUSKURE: Ba a sami TELEGRAM_BOT_TOKEN a .env ba.")
    sys.exit(1)

message = (
    "🚀 WELCOME TO MR AI BINARY ENGINE SIGNAL 🚀\n"
    "━━━━━━━━━━━━━━━━━━\n"
    "📊 BINARY ENGINE SIGNAL\n"
    "━━━━━━━━━━━━━━━━━━\n\n"
    "📍 Market: R_100\n"
    "⏱️ Timeframe: M1\n"
    "🎯 Direction: NO SIGNAL\n"
    "⌛ Expiry: 3 Minutes\n"
    "📌 Status: TEST ONLY\n\n"
    "━━━━━━━━━━━━━━━━━━\n"
    "⚠️ GARGADI — HAUSA 🇳🇬\n\n"
    "Wannan saƙo na gwaji ne, ba shawarar shiga kasuwa ba. "
    "Babu tabbacin samun riba a trading. Za ka iya rasa kuɗinka. "
    "Ka fara da demo account, ka kiyaye jarinka, "
    "kuma kada ka saka kuɗin da ba za ka iya rasa ba.\n\n"
    "━━━━━━━━━━━━━━━━━━\n"
    "⚠️ RISK WARNING — ENGLISH 🇬🇧\n\n"
    "This is a test message, not a trading recommendation. "
    "Profit is never guaranteed, and you may lose money. "
    "Use a demo account first, manage your risk, "
    "and never trade with money you cannot afford to lose.\n\n"
    "🤖 MR AI BINARY ENGINE\n"
    "Trade carefully. Protect your capital."
)

url = f"https://api.telegram.org/bot{token}/sendMessage"

try:
    response = requests.post(
        url,
        json={
            "chat_id": chat_id,
            "text": message,
        },
        timeout=20,
    )

    result = response.json()

    if result.get("ok"):
        print("NASARA: An aika sabon saƙon gwaji zuwa Telegram!")
    else:
        print("Ba a aika saƙon ba.")
        print("Dalili:", result.get("description", "Ba a sani ba"))

except requests.RequestException as error:
    print("Matsalar haɗin intanet:", error)
except ValueError:
    print("Ba a samu amsa mai inganci daga Telegram ba.")
