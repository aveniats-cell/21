import asyncio
import logging
import os
import threading
import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from collections import defaultdict

from telethon import TelegramClient
from telethon.sessions import StringSession

# === НАСТРОЙКИ ИЗ ПЕРЕМЕННЫХ ОКРУЖЕНИЯ ===
API_ID = int(os.environ.get("API_ID", 0))
API_HASH = os.environ.get("API_HASH", "")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")

# === СОВЕТ ГОЛОСУЮЩИХ ===
HOLY_TRINITY_USERNAMES = {"youwarm", "ilyshadep", "naranjortiz"}

MAX_REQUESTS_PER_DAY = 2
VOTE_TIMEOUT = 300
MUTE_DURATION = 60 * 60 * 24

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# === ХРАНИЛИЩА (общие для всех модулей) ===
daily_requests = defaultdict(lambda: {"date": datetime.date.today(), "count": 0})
active_votes = defaultdict(dict)
muted_users = {}
pending_admin_votes = {}

# === КЛИЕНТ ===
client = TelegramClient(StringSession(), API_ID, API_HASH)


# === ФИКТИВНЫЙ ВЕБ-СЕРВЕР ДЛЯ RENDER ===
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


# === ЗАПУСК ===
async def main():
    if not API_ID or not API_HASH or not BOT_TOKEN:
        logging.error("❌ ОШИБКА: Не заданы переменные окружения (API_ID, API_HASH или BOT_TOKEN)!")
        return

    threading.Thread(target=run_health_server, daemon=True).start()
    logging.info("Фоновый веб-сервер для Render успешно запущен.")

    await client.start(bot_token=BOT_TOKEN)
    logging.info("Бот запущен через MTProto (Telethon)! Готов к работе.")

    # === РЕГИСТРАЦИЯ МОДУЛЕЙ ===
    # Импортируем после старта клиента, чтобы не было циклических импортов
    import moderation
    import fun

    moderation.register(client)
    fun.register(client)

    logging.info("✅ Модули moderation и fun подключены.")

    await client.run_until_disconnected()


if __name__ == "__main__":
    asyncio.run(main())
