import hashlib
import logging
import re
from html import escape as esc

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes, MessageHandler, filters

logger = logging.getLogger(__name__)

SHIP_RE = re.compile(r"^/?шип\s+@?(\w+)\s+@?(\w+)$", re.IGNORECASE)


def register(app, resolver) -> None:
    async def ship_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        msg = update.effective_message
        m = SHIP_RE.match(msg.text or "")
        if not m:
            return
        u1_name, u2_name = m.group(1), m.group(2)

        async def resolve(name):
            if resolver and resolver.enabled:
                ent = await resolver.resolve(name)
                if ent is not None:
                    return ent
            try:
                return await context.bot.get_chat(f"@{name}")
            except Exception:
                return None

        u1 = await resolve(u1_name)
        u2 = await resolve(u2_name)
        if not u1 or not u2:
            await msg.reply_text("❌ Пользователи не найдены.")
            return

        seed = "-".join(sorted([str(u1.id), str(u2.id)]))
        pct = int(hashlib.md5(seed.encode()).hexdigest(), 16) % 101

        if pct >= 90:
            comment = "💍 Да это судьба! Свадьбу когда?"
        elif pct >= 70:
            comment = "🔥 Отличная пара, вам точно стоит попробовать."
        elif pct >= 50:
            comment = "😏 Есть шанс, но придётся постараться."
        elif pct >= 30:
            comment = "🤔 Ну... как друзья сойдёт."
        elif pct >= 10:
            comment = "😬 Скорее нет, чем да."
        else:
            comment = "💀 Бегите друг от друга."

        def name_of(u):
            return (
                getattr(u, "first_name", None)
                or getattr(u, "title", None)
                or getattr(u, "username", None)
                or str(u.id)
            )

        await msg.reply_text(
            f"💘 <b>{esc(name_of(u1))}</b> + <b>{esc(name_of(u2))}</b>\n"
            f"Совместимость: <b>{pct}%</b>\n"
            f"{comment}",
            parse_mode=ParseMode.HTML,
        )

    app.add_handler(MessageHandler(filters.Regex(SHIP_RE), ship_cmd))

    logger.info("Ship module: 'шип @user1 @user2' зарегистрирован.")
