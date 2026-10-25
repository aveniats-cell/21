import hashlib
import logging

from telethon import events


# === РЕГИСТРАЦИЯ ВСЕХ ХЭНДЛЕРОВ МОДУЛЯ ===
def register(client):
    """Вызывается из main.py после старта клиента."""

    @client.on(events.NewMessage(pattern=r'^/шип'))
    async def ship_cmd(event):
        args = event.message.text.split()
        if len(args) < 3:
            await event.reply("❌ Использование: `/шип @user1 @user2`", parse_mode='md')
            return

        try:
            u1 = await client.get_entity(args[1].lstrip('@'))
            u2 = await client.get_entity(args[2].lstrip('@'))
        except Exception:
            await event.reply("❌ Пользователи не найдены.")
            return

        # Стабильный результат: хеш от отсортированных ID
        seed = "-".join(sorted([str(u1.id), str(u2.id)]))
        pct = int(hashlib.md5(seed.encode()).hexdigest(), 16) % 101
        bar = "❤️" * (pct // 10) + "🖤" * (10 - pct // 10)

        # Забавные комментарии по диапазонам
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

        await event.reply(
            f"💘 **{u1.first_name}** + **{u2.first_name}**\n"
            f"{bar}\n"
            f"Совместимость: **{pct}%**\n"
            f"{comment}",
            parse_mode='md'
        )

    logging.info("Ship module: зарегистрирован /шип.")
