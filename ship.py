import hashlib
import logging

from telethon import events


def register(client):
    @client.on(events.NewMessage(pattern=r'(?i)^/?шип\s+@?(\w+)\s+@?(\w+)$'))
    async def ship_cmd(event):
        u1_name = event.pattern_match.group(1)
        u2_name = event.pattern_match.group(2)

        try:
            u1 = await client.get_entity(u1_name)
            u2 = await client.get_entity(u2_name)
        except Exception:
            await event.reply("❌ Пользователи не найдены.")
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

        await event.reply(
            f"💘 **{u1.first_name}** + **{u2.first_name}**\n"
            f"Совместимость: **{pct}%**\n"
            f"{comment}",
            parse_mode='md'
        )

    logging.info("Ship module: зарегистрирован 'шип @user1 @user2'.")
