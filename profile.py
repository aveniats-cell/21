import logging
from telethon import events

import db


def register(client, holy_trinity):
    @client.on(events.NewMessage)
    async def track_activity(event):
        """Считает сообщения и создаёт профиль при первом сообщении."""
        if not event.text or event.text.startswith("/"):
            return
        sender = await event.get_sender()
        if not sender or getattr(sender, "bot", False):
            return
        try:
            db.ensure_profile(sender.id, sender.username, sender.first_name)
            db.inc_message_count(sender.id)
        except Exception as e:
            logging.error(f"Profile track error: {e}")

    @client.on(events.NewMessage(pattern=r'(?i)^/?профиль(?:\s+@?(\w+))?$'))
    async def profile_cmd(event):
        target_name = event.pattern_match.group(1)

        # Определяем цель: аргумент, реплай или сам отправитель
        if target_name:
            try:
                user = await client.get_entity(target_name)
            except Exception:
                await event.reply("❌ Пользователь не найден.")
                return
        elif event.is_reply:
            reply = await event.get_reply_message()
            user = await reply.get_sender()
        else:
            user = await event.get_sender()

        try:
            db.ensure_profile(user.id, user.username, user.first_name)
            data = db.get_profile(user.id)
        except Exception as e:
            await event.reply(f"❌ Ошибка базы: {e}")
            return

        # === Должность ===
        role = "Участник"
        try:
            perms = await client.get_permissions(event.chat_id, user.id)
            if perms.is_admin:
                role = "Админ"
            if getattr(perms, "is_creator", False):
                role = "Создатель"
        except Exception:
            pass

        # === Член совета ССС ===
        is_sss = "Да" if user.username and user.username.lower() in holy_trinity else "Нет"

        # === Остальные поля ===
        first_seen = data["first_seen"] if data else "—"
        msg_count = data["message_count"] if data else 0
        criminal = "Да" if data and data["is_criminal"] else "Нет"
        awards = data["awards"] if data and data["awards"] else "—"

        name = f"{user.first_name or ''} {user.last_name or ''}".strip() or user.username or str(user.id)

        await event.reply(
            f"👤 **Имя:** {name}\n"
            f"📅 **Первое появление:** {first_seen}\n"
            f"💼 **Должность:** {role}\n"
            f"🕵️ **Член совета ССС:** {is_sss}\n"
            f"🏆 **Награды:** {awards}\n"
            f"💬 **Кол-во сообщений:** {msg_count}\n"
            f"⚖️ **Судимость:** {criminal}",
            parse_mode='md'
        )

    logging.info("Profile module: зарегистрированы 'профиль' и трекер активности.")
