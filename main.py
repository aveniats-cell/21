"""Super-Bot Telegram — точка входа."""
import asyncio
import logging
import time

from telegram import Update
from telegram.ext import (
    Application, CommandHandler, MessageHandler, ContextTypes, filters,
)
from aiohttp import web

import config
import db
import helpers
import roles, moderation, council, top, ship, wedding, coins, tictactoe, pr, profile

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
log = logging.getLogger("SuperBot")

_started_at = None
GROUPS = filters.ChatType.GROUP | filters.ChatType.SUPERGROUP


# ---------- служебные ----------
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user and helpers.is_admin_user(user) and not context.application.bot_data.get("admin_id"):
        context.application.bot_data["admin_id"] = user.id
        helpers.ADMIN_ID = user.id
        log.info("Admin id установлен через /start: %s", user.id)
    await update.effective_message.reply_text(
        "👋 <b>Привет!</b> Я Super-Bot.\nСписок команд: /help",
        parse_mode="HTML",
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(
        "📚 <b>Команды бота</b>\n\n"
        "<b>👑 Роли (только админ):</b>\n"
        "<code>+Шериф @u</code> · <code>-Шериф @u</code> · <code>Шерифы</code>\n"
        "<code>+Комиссар @u</code> · <code>-Комиссар @u</code> · <code>Комиссары</code>\n"
        "<code>+ССС @u</code> · <code>-ССС @u</code> · <code>ССС</code>\n\n"
        "<b>🔨 Модерация (админ/комиссар):</b>\n"
        "<code>+Мут @u 1ч 30м</code> · <code>-Мут @u</code>\n"
        "<code>+Бан @u</code> · <code>-Бан @u</code>\n"
        "<b>Шериф:</b> <code>Поймать @u</code> → заявка админу в ЛС\n\n"
        "<b>⚖️ Суды:</b>\n"
        "<code>+Суд ССС @u</code> — только ССС, единогласно\n"
        "<code>+Суд @u</code> — общий, большинство\n\n"
        "<b>💬 Социалка:</b>\n"
        "<code>Профиль</code> · <code>Топ день</code> · <code>Топ все</code> · <code>Мое место</code>\n"
        "<code>Шип @u1 @u2</code>\n"
        "<code>Сделать предложение @u</code> · <code>-Брак</code>\n"
        "<code>+Брак @u1 @u2</code> — админ\n\n"
        "<b>💰 Экономика:</b>\n"
        "<code>+Кредит 50</code> · <code>-Кредит 50</code> · <code>+Монеты 500 @u</code> (админ)\n\n"
        "<b>🎮 Игры:</b>\n"
        "<code>хо @u 100</code> — вызов в крестики-нолики 5×5\n\n"
        "<b>📢 PR:</b>\n"
        "<code>+ПР @channel</code> · <code>-ПР @channel</code> · <code>ПР</code> (админ)",
        parse_mode="HTML",
    )


async def cmd_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    m = update.effective_message
    if m.reply_to_message and m.reply_to_message.from_user:
        u = m.reply_to_message.from_user
        await m.reply_text(
            f"id: <code>{u.id}</code>\nusername: @{u.username or '—'}",
            parse_mode="HTML",
        )
    else:
        await m.reply_text(
            f"chat_id: <code>{m.chat_id}</code>\nyour_id: <code>{m.from_user.id}</code>",
            parse_mode="HTML",
        )


# ---------- счётчик сообщений (атомарный UPSERT) ----------
async def counter(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    if not msg:
        return
    content = msg.text or msg.caption
    if not content:
        return
    user = msg.from_user
    if not user or user.is_bot:
        return
    if msg.chat.type not in ("group", "supergroup"):
        return

    await db.execute(
        "INSERT OR IGNORE INTO users (user_id, username, first_name) VALUES (?,?,?)",
        (user.id, user.username, user.first_name),
    )
    await db.execute(
        "UPDATE users SET username=?, first_name=? WHERE user_id=?",
        (user.username, user.first_name, user.id),
    )

    today = helpers.today_str()
    await db.execute(
        "INSERT INTO chat_users (chat_id, user_id, msg_day, msg_total, day_date) "
        "VALUES (?, ?, 1, 1, ?) "
        "ON CONFLICT(chat_id, user_id) DO UPDATE SET "
        "  msg_total = msg_total + 1, "
        "  msg_day = CASE WHEN day_date = excluded.day_date THEN msg_day + 1 ELSE 1 END, "
        "  day_date = excluded.day_date",
        (msg.chat_id, user.id, today),
    )


# ---------- фоновая чистка ----------
async def _background_cleanup(application: Application):
    """Периодически: чистит PR-кэши, rate-limit и завершает зависшие игры."""
    while True:
        await asyncio.sleep(60)
        try:
            pr.cleanup_caches(application)
        except Exception as e:
            log.warning("PR cleanup error: %s", e)
        try:
            helpers.cleanup_rate_limits(application)
        except Exception as e:
            log.warning("RL cleanup error: %s", e)
        try:
            await tictactoe.expire_stale(application)
        except Exception as e:
            log.warning("TTT cleanup error: %s", e)


# ---------- HTTP healthcheck ----------
async def _start_http():
    global _started_at
    _started_at = time.time()

    async def health(_):
        return web.json_response({"status": "ok"})

    async def root(_):
        return web.json_response({
            "status": "running",
            "uptime_sec": int(time.time() - _started_at),
        })

    app = web.Application()
    app.router.add_get("/health", health)
    app.router.add_get("/", root)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", config.PORT)
    await site.start()
    log.info("HTTP healthcheck on :%d", config.PORT)


# ---------- init ----------
async def post_init(application: Application):
    log.info("Инициализация БД...")
    try:
        await db.init()
        log.info("БД готова.")
    except Exception as e:
        log.exception("Критическая ошибка БД: %s", e)
        raise

    if config.ADMIN_ID:
        application.bot_data["admin_id"] = config.ADMIN_ID
        application.bot_data["admin_username"] = config.ADMIN_USERNAME
        helpers.ADMIN_ID = config.ADMIN_ID
        log.info("Admin id = %s (из ENV)", config.ADMIN_ID)
    else:
        try:
            chat = await application.bot.get_chat("@" + config.ADMIN_USERNAME)
            application.bot_data["admin_id"] = chat.id
            application.bot_data["admin_username"] = config.ADMIN_USERNAME
            helpers.ADMIN_ID = chat.id
            log.info("Admin id = %s (@%s)", chat.id, config.ADMIN_USERNAME)
        except Exception as e:
            log.warning("Не удалось получить admin_id (@%s): %s", config.ADMIN_USERNAME, e)
            application.bot_data["admin_id"] = None
            application.bot_data["admin_username"] = config.ADMIN_USERNAME

    if config.API_ID and config.API_HASH:
        try:
            from telethon import TelegramClient
            from telethon.sessions import StringSession
            tc = TelegramClient(StringSession(), config.API_ID, config.API_HASH)
            await tc.connect()
            if not await tc.is_user_authorized():
                await tc.sign_in(bot_token=config.BOT_TOKEN)
            application.bot_data["telethon"] = tc
            log.info("Telethon подключён (без update-loop)")
        except Exception as e:
            log.warning("Telethon не подключился: %s", e)

    asyncio.create_task(_start_http())
    asyncio.create_task(_background_cleanup(application))


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE):
    log.error("Ошибка при обработке апдейта", exc_info=context.error)


# ---------- main ----------
def main():
    config.validate()
    app = (
        Application.builder()
        .token(config.BOT_TOKEN)
        .post_init(post_init)
        .build()
    )

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help",  cmd_help))
    app.add_handler(CommandHandler("id",    cmd_id))

    roles.register(app)
    moderation.register(app)
    council.register(app)
    top.register(app)
    ship.register(app)
    wedding.register(app)
    coins.register(app)
    tictactoe.register(app)
    profile.register(app)
    pr.register(app)

    app.add_handler(
        MessageHandler((filters.TEXT | filters.CAPTION) & GROUPS, counter),
        group=1,
    )
    app.add_error_handler(on_error)

    log.info("Бот запущен (polling)...")
    app.run_polling(
        drop_pending_updates=True,
        allowed_updates=["message", "callback_query", "poll", "poll_answer"],
    )


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        # SystemExit — это наш validate(), текст уже в логе ERROR-строкой
        raise
    except Exception:
        logging.getLogger("SuperBot").exception("Фатальная ошибка при запуске")
        raise
