"""SAH — one-off helper to find your Telegram chat_id.

Usage:
  1. Message your new bot anything on Telegram first (e.g. "hi").
  2. Run: venv\\Scripts\\python.exe get_chat_id.py <bot_token>
  3. It prints the chat_id(s) of anyone who has messaged the bot.
"""
import sys
import requests


def main():
    if len(sys.argv) != 2:
        print("Usage: python get_chat_id.py <bot_token>")
        sys.exit(1)
    token = sys.argv[1]
    resp = requests.get(f"https://api.telegram.org/bot{token}/getUpdates", timeout=10)
    resp.raise_for_status()
    updates = resp.json().get("result", [])
    if not updates:
        print("No messages yet. Send any message to your bot on Telegram, then re-run this.")
        return
    seen = set()
    for u in updates:
        msg = u.get("message") or {}
        chat = msg.get("chat") or {}
        chat_id = chat.get("id")
        name = chat.get("first_name") or chat.get("username") or "?"
        if chat_id and chat_id not in seen:
            seen.add(chat_id)
            print(f"chat_id={chat_id}  ({name})")


if __name__ == "__main__":
    main()
