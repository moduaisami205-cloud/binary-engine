import os
import sys
import requests
from dotenv import load_dotenv

load_dotenv()

token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()

if not token:
    print("ERROR: TELEGRAM_BOT_TOKEN bai cikin .env ba.")
    sys.exit(1)

if ":" not in token:
    print("ERROR: Duba token ɗin da ke cikin .env.")
    sys.exit(1)

url = f"https://api.telegram.org/bot{token}/getUpdates"

try:
    response = requests.get(url, timeout=20)
    data = response.json()

    if not response.ok or not data.get("ok"):
        print("Telegram API ta ƙi buƙatar. Ka duba token ɗin a .env.")
        sys.exit(1)

    chats = {}

    for update in data.get("result", []):
        message = update.get("message") or update.get("edited_message")
        if not message:
            continue

        chat = message.get("chat", {})
        chat_id = chat.get("id")

        if chat_id is not None:
            chats[chat_id] = {
                "name": chat.get("first_name", "Telegram user"),
                "username": chat.get("username", ""),
                "text": message.get("text", ""),
            }

    if not chats:
        print("Ba a sami saƙo ba tukuna.")
        print("Buɗe @BinaryEngineSignalsBot ka aika /start.")
    else:
        print("An gano waɗannan chats:")
        for chat_id, details in chats.items():
            print(f"Chat ID: {chat_id}")
            print(f"Suna: {details['name']}")
            if details["username"]:
                print(f"Username: @{details['username']}")
            print(f"Saƙon ƙarshe da aka gani: {details['text']}")
            print("-" * 30)

except requests.RequestException as error:
    print("An samu matsalar haɗin intanet:", error)
except ValueError:
    print("Telegram ta dawo da amsar da ba a iya karantawa ba.")
