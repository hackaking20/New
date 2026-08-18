#!/usr/bin/env python3
"""
Broadcast script for the WZML-X Telegram bot.

Reads BOT_TOKEN, DATABASE_URL, and OWNER_ID from the environment,
queries MongoDB for all PM (private-message) users, and sends the
provided message to each of them via the Telegram Bot API.

Usage:
    python broadcast.py "Your message text here"
"""

import os
import sys
import time
import logging
from urllib.parse import urlparse

import requests
from pymongo import MongoClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("broadcast")

BOT_TOKEN = os.environ.get("BOT_TOKEN", "").strip()
DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
OWNER_ID = os.environ.get("OWNER_ID", "").strip()

TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"


def get_users():
    """Connect to MongoDB and return the list of PM user chat IDs."""
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL is not set")

    client = MongoClient(DATABASE_URL)
    # Try common WZML-X collection names for PM users.
    db_name = urlparse(DATABASE_URL).path.lstrip("/") or "WZML-X"
    db = client[db_name]

    user_ids = []
    # WZML-X typically stores PM users in the 'users' collection.
    for collection_name in ("users", "pmusers", "main"):
        try:
            col = db[collection_name]
            for doc in col.find({}, {"_id": 1, "user_id": 1, "chat_id": 1, "id": 1}):
                uid = doc.get("user_id") or doc.get("chat_id") or doc.get("id") or doc.get("_id")
                if uid is not None:
                    try:
                        user_ids.append(int(uid))
                    except (TypeError, ValueError):
                        continue
            if user_ids:
                log.info("Loaded %d users from collection '%s'", len(user_ids), collection_name)
                break
        except Exception as e:
            log.debug("Collection '%s' not usable: %s", collection_name, e)

    client.close()
    # De-duplicate while preserving order.
    seen = set()
    unique = []
    for u in user_ids:
        if u not in seen:
            seen.add(u)
            unique.append(u)
    return unique


def send_message(chat_id, text):
    """Send a single message via the Telegram Bot API."""
    try:
        resp = requests.post(
            TELEGRAM_API,
            json={
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
            timeout=30,
        )
        if resp.status_code != 200:
            log.warning("Failed for %s: %s %s", chat_id, resp.status_code, resp.text[:200])
            return False
        return True
    except Exception as e:
        log.warning("Error sending to %s: %s", chat_id, e)
        return False


def main():
    if not BOT_TOKEN:
        log.error("BOT_TOKEN is not set")
        sys.exit(1)
    if not OWNER_ID:
        log.error("OWNER_ID is not set")
        sys.exit(1)

    message = "📢 Broadcast from bot" if len(sys.argv) < 2 else sys.argv[1]
    log.info("Broadcasting to all PM users: %s", message)

    users = get_users()
    if not users:
        log.warning("No PM users found in database.")
        sys.exit(0)

    # Always include the owner.
    try:
        owner = int(OWNER_ID)
    except ValueError:
        owner = None
    if owner and owner not in users:
        users.append(owner)

    sent = 0
    failed = 0
    for uid in users:
        ok = send_message(uid, message)
        if ok:
            sent += 1
        else:
            failed += 1
        # Respect Telegram rate limits (~30 msg/sec global, but be gentle).
        time.sleep(0.05)

    log.info("Done. Sent: %d, Failed: %d, Total: %d", sent, failed, len(users))


if __name__ == "__main__":
    main()
