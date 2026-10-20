import os
import requests
from dotenv import load_dotenv

load_dotenv()
token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()

if not token:
    print("MATSALA: Ba a sami token a .env ba.")
    raise SystemExit(1)

base = f"https://api.telegram.org/bot{token}"

try:
    r = requests.get(f"{base}/getWebhookInfo", timeout=20)
    data = r.json()

    if not data.get("ok"):
        print("Webhook check failed:", data.get("description", "Unknown error"))
        raise SystemExit(1)

    info = data["result"]
    print("Webhook yana aiki:", bool(info.get("url")))
    print("Pending updates:", info.get("pending_update_count", "unknown"))
    print("Webhook error:", info.get("last_error_message") or "Babu")

    r = requests.get(f"{base}/getUpdates", timeout=20)
    updates = r.json()

    if updates.get("ok"):
        print("Saƙonnin da ake jira:", len(updates.get("result", [])))
    else:
        print("getUpdates error:", updates.get("description", "Unknown error"))

except requests.RequestException as e:
    print("Matsalar intanet:", e)
