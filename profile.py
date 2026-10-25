import logging
import re
from html import escape as esc

from telegram import ChatMemberAdministrator, ChatMemberOwner, Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes, MessageHandler, filters

import db

logger = logging.getLogger(__name__)

PROFILE_RE = re.compile(r"^/?профиль(?:\s+@?(\w+))?$", re.IGNORECASE)


def register(app, holy_trinity: set[str]) -> None:
    async def track_activity(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        msg = update.effective_message
        user = update.effective_user
        if not msg or not msg.text or msg.text.startswith("/"):
            return
        if not user or user.is_bot:
            return
        try:
            db.ensure_profile(user.id, user.username, user.first_name)
            db.inc_message_count(user.id)
        except Exception as e:
            logger.error("Profile track error: %s", e)

    async def profile_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        msg = update.effective_message
        sender = update.effective_user
        chat = update.effective_chat

        m = PROFILE_RE.match(msg.text or "")
        if not m:
            return
        target_name = m.group(1)

        # Выбор цели: аргумент → реплай → сам отправитель
        if target_name:
            try:
                target = await context.bot.get_chat(f"@{target_name}")
            except Exception:
                await msg.reply_text("❌ Пользователь не найден.")
                return
        elif msg.reply_to_message and msg.reply_to_message.from_user:
            target = msg.reply_to_message.from_user
        else:
            target = sender

        try:
            db.ensure_profile(
                target.id,
                getattr(target, "username", None),
                getattr(target, "first_name", None),
            )
            data = db.get_profile(target.id)
        except Exception as e:
            await msg.reply_text(f"❌ Ошибка базы: {esc(str(e))}", parse_mode=ParseMode.HTML)
            return

        # Должность
        role = "Участник"
        try:
            member = await context.bot.get_chat_member(chat.id, target.id)
            if isinstance(member, ChatMemberOwner):
                role = "Создатель"
            elif isinstance(member, ChatMemberAdministrator):
                role = "Админ"
        except Exception:
            pass

        username = getattr(target, "username", None)
        is_sss = "Да" if username and username.lower() in holy_trinity else "Нет"

        first_seen = data["first_seen"] if data else "—"
        msg_count = data["message_count"] if data else 0
        criminal = "Да" if data and data["is_criminal"] else "Нет"
        awards = data["awards"] if data and data["awards"] else "—"

        first = getattr(target, "first_name", None) or ""
        last = getattr(target, "last_name", None) or ""
        name = f"{first} {last}".strip() or username or str(target.id)

        await msg.reply_text(
            f"👤 <b>Имя:</b> {esc(name)}\n"
            f"📅 <b>Первое появление:</b> {esc(str(first_seen))}\n"
            f"💼 <b>Должность:</b> {esc(role)}\n"
            f"🕵️ <b>Член совета ССС:</b> {is_sss}\n"
            f"🏆 <b>Награды:</b> {esc(str(awards))}\n"
            f"💬 <b>Кол-во сообщений:</b> {msg_count}\n"
            f"⚖️ <b>Судимость:</b> {criminal}",
            parse_mode=ParseMode.HTML,
        )

    # Трекер активности — в группе 1, чтобы не мешать другим хэндлерам
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, track_activity),
        group=1,
    )
    app.add_handler(MessageHandler(filters.Regex(PROFILE_RE), profile_cmd))

    logger.info("Profile module: 'профиль' и трекер активности зарегистрированы.")
