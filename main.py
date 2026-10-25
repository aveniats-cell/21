import asyncio
import logging
import os
import threading
import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from collections import defaultdict

from telethon import TelegramClient
from telethon.sessions import StringSession

API_ID = int(os.environ.get("API_ID", 0))
API_HASH = os.environ.get("API_HASH", "")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
STRING_SESSION = os.environ.get("STRING_SESSION", "")

HOLY_TRINITY_USERNAMES = {"youwarm", "ilyshadep", "naranjortiz"}

MAX_REQUESTS_PER_DAY = 2
VOTE_TIMEOUT = 300
MUTE_DURATION = 60 * 60 * 24

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# === ВРЕМЕННАЯ ПАМЯТЬ RENDER ===
daily_requests = defaultdict(lambda: {"date": datetime.date.today(), "count": 0})
active_votes = defaultdict(dict)
pending_admin_votes = {}

# === КЛИЕНТ ===
if STRING_SESSION:
    client = TelegramClient(StringSession(STRING_SESSION), API_ID, API_HASH)
else:
    client = TelegramClient(StringSession(), API_ID, API_HASH)


class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")

    def log_message(self, format, *args):
        pass


def run_health_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
    server.serve_forever()


async def main():
    if not API_ID or not API_HASH:
        logging.error("❌ ОШИБКА: Не заданы API_ID или API_HASH!")
        return

    threading.Thread(target=run_health_server, daemon=True).start()
    logging.info("Фоновый веб-сервер для Render успешно запущен.")

    if STRING_SESSION:
        await client.start()
        logging.info("Бот запущен по готовой сессии (STRING_SESSION).")
    else:
        if not BOT_TOKEN:
            logging.error("❌ ОШИБКА: Нет ни STRING_SESSION, ни BOT_TOKEN!")
            return
        logging.warning("⚠️ STRING_SESSION не задан. Вход по bot_token (риск FloodWait).")
        await client.start(bot_token=BOT_TOKEN)

    me = await client.get_me()
    logging.info(f"Бот: @{me.username} (bot={me.bot}). Готов к работе.")

    import moderation
    import cubic
    import ship
    import curse
    import profile

    moderation.register(
        client=client,
        active_votes=active_votes,
        pending_admin_votes=pending_admin_votes,
        daily_requests=daily_requests,
        holy_trinity=HOLY_TRINITY_USERNAMES,
        max_requests=MAX_REQUESTS_PER_DAY,
        vote_timeout=VOTE_TIMEOUT,
        mute_duration=MUTE_DURATION,
    )

    cubic.register(client=client)
    ship.register(client=client)
    curse.register(client=client)
    profile.register(client=client, holy_trinity=HOLY_TRINITY_USERNAMES)

    logging.info("✅ Модули moderation, cubic, ship, curse, profile подключены.")

    await client.run_until_disconnected()


if __name__ == "__main__":
    asyncio.run(main())
