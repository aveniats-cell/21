import logging
import os
import threading
from collections import defaultdict
from datetime import date
from http.server import BaseHTTPRequestHandler, HTTPServer

from telegram.ext import Application, ApplicationBuilder

import cubic
import curse
import moderation
import profile
import ship

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
HOLY_TRINITY_USERNAMES = {"youwarm", "ilyshadep", "naranjortiz"}

MAX_REQUESTS_PER_DAY = 2
VOTE_TIMEOUT = 300
MUTE_DURATION = 60 * 60 * 24  # 24 часа

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")

    def log_message(self, fmt, *args):
        pass


def _run_health_server() -> None:
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
    server.serve_forever()


async def _on_startup(app: Application) -> None:
    me = await app.bot.get_me()
    logger.info("Бот запущен: @%s (id=%s)", me.username, me.id)


async def _start_cmd(update, context):
    await update.message.reply_text(
        "👋 Привет! Я бот этого чата.\n\n"
        "📋 <b>Команды:</b>\n"
        "/профиль [@user] — профиль участника\n"
        "/суд @user — голосование за бан\n"
        "/ожидание — отложенные голосования\n"
        "/удача &lt;варианты&gt; — рулетка\n"
        "/монетка — орёл/решка\n"
        "/кубик [NdM] — бросить кубики\n"
        "/рандом A B — случайное число\n"
        "/шар &lt;вопрос&gt; — магический шар\n"
        "/курс &lt;монета&gt; — курс криптовалюты\n"
        "/шип @u1 @u2 — совместимость\n"
        "/пинг — проверка отклика",
        parse_mode="HTML",
    )


def main() -> None:
    if not BOT_TOKEN:
        logger.error("❌ BOT_TOKEN не задан в переменных окружения!")
        return

    threading.Thread(target=_run_health_server, daemon=True).start()
    logger.info("Фоновый веб-сервер для Render запущен (порт %s).",
                os.environ.get("PORT", 10000))

    app: Application = (
        ApplicationBuilder()
        .token(BOT_TOKEN)
        .post_init(_on_startup)
        .build()
    )

    # Общее состояние между модулями
    state = {
        "active_votes": defaultdict(dict),
        "pending_admin_votes": {},
        "daily_requests": defaultdict(lambda: {"date": date.today(), "count": 0}),
        "muted_users": {},
        "holy_trinity": HOLY_TRINITY_USERNAMES,
        "max_requests": MAX_REQUESTS_PER_DAY,
        "vote_timeout": VOTE_TIMEOUT,
        "mute_duration": MUTE_DURATION,
    }

    from telegram.ext import CommandHandler
    app.add_handler(CommandHandler(["start", "help"], _start_cmd))

    moderation.register(app, state)
    cubic.register(app)
    curse.register(app)
    ship.register(app)
    profile.register(app, HOLY_TRINITY_USERNAMES)

    logger.info("Все модули подключены. Запуск polling…")
    app.run_polling(allowed_updates=["message", "callback_query"])


if __name__ == "__main__":
    main()
