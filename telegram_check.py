import os
import requests
from dotenv import load_dotenv

load_dotenv()
token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()

if not token:
    print("Ba a sami token a .env ba.")
    raise SystemExit(1)

try:
    r = requests.get(
        f"https://api.telegram.org/bot{token}/getMe",
        timeout=20,
    )
    data = r.json()

    if data.get("ok"):
        bot = data["result"]
        print("An haɗu da Telegram bot cikin nasara.")
        print("Bot name:", bot.get("first_name"))
        print("Bot username:", bot.get("username"))
        print("Bot yana aiki:", bot.get("is_bot"))
    else:
        print("Telegram bai karɓi token ɗin ba.")
        print("Dalili:", data.get("description", "Ba a sani ba"))

except requests.RequestException:
    print("An samu matsalar haɗin intanet.")
