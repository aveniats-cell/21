import asyncio
import random
import re
import logging

from telethon import events


# === РЕГИСТРАЦИЯ ВСЕХ ХЭНДЛЕРОВ МОДУЛЯ ===
def register(client):
    """Вызывается из main.py после старта клиента."""

    @client.on(events.NewMessage(pattern=r'^/cubic'))
    async def cubic_cmd(event):
        text = event.message.text[len('/cubic'):].strip()
        if not text:
            await event.reply(
                "❌ Использование: `/cubic Орел, решка, Иван гай`\n"
                "Разделяй варианты запятой.",
                parse_mode='md'
            )
            return

        raw = re.split(r'[,;]|\s+или\s+', text)
        options = [o.strip() for o in raw if o.strip()]

        if len(options) < 2:
            await event.reply("❌ Нужно минимум 2 варианта, разделённых запятой.", parse_mode='md')
            return
        if len(options) > 30:
            await event.reply("❌ Слишком много вариантов (максимум 30).", parse_mode='md')
            return

        spin_msg = await event.reply("🎰 Крутим рулетку...")

        delays = [0.08, 0.10, 0.13, 0.16, 0.20, 0.25, 0.32, 0.40, 0.50]
        for delay in delays:
            frame = random.choice(options)
            try:
                await spin_msg.edit(f"🎰 Крутим... **{frame}**", parse_mode='md')
            except Exception:
                pass
            await asyncio.sleep(delay)

        winner = random.choice(options)

        if len(options) <= 10:
            opts_display = ", ".join(options)
        else:
            opts_display = ", ".join(options[:10]) + f" и ещё {len(options) - 10}..."

        try:
            await spin_msg.edit(
                f"🎰 **Рулетка завершена!**\n\n"
                f"📋 Варианты: {opts_display}\n\n"
                f"🎯 Выпало: **{winner}**",
                parse_mode='md'
            )
        except Exception:
            await event.reply(f"🎰 Выпало: **{winner}**", parse_mode='md')

    @client.on(events.NewMessage(pattern=r'^/coin'))
    async def coin_cmd(event):
        result = random.choice(["🪙 **Орёл!**", "🪙 **Решка!**"])
        await event.reply(result, parse_mode='md')

    @client.on(events.NewMessage(pattern=r'^/roll'))
    async def roll_cmd(event):
        args = event.message.text.split()
        dice = args[1] if len(args) > 1 else "1d6"
        m = re.fullmatch(r'(\d*)d(\d+)', dice.lower())
        if not m:
            await event.reply("❌ Формат: `/roll 2d6` или `/roll d20`", parse_mode='md')
            return
        count = int(m.group(1)) if m.group(1) else 1
        sides = int(m.group(2))
        if count < 1 or count > 20 or sides < 2 or sides > 1000:
            await event.reply("❌ Слишком много кубиков или граней.")
            return
        rolls = [random.randint(1, sides) for _ in range(count)]
        total = sum(rolls)
        detail = " + ".join(map(str, rolls)) if count > 1 else str(rolls[0])
        await event.reply(f"🎲 **{dice}** → {detail}" + (f" = **{total}**" if count > 1 else ""), parse_mode='md')

    @client.on(events.NewMessage(pattern=r'^/random'))
    async def random_cmd(event):
        args = event.message.text.split()
        try:
            a, b = int(args[1]), int(args[2])
            if a > b:
                a, b = b, a
        except (IndexError, ValueError):
            await event.reply("❌ Использование: `/random 1 100`", parse_mode='md')
            return
        await event.reply(f"🎯 Случайное число: **{random.randint(a, b)}**", parse_mode='md')

    @client.on(events.NewMessage(pattern=r'^/8ball'))
    async def ball_cmd(event):
        text = event.message.text[len('/8ball'):].strip()
        if not text:
            await event.reply("❌ Задайте вопрос: `/8ball Будет ли сегодня дождь?`", parse_mode='md')
            return
        answers = [
            "✅ Да, определённо.", "✅ Безусловно.", "✅ Скорее да.",
            "🤔 Возможно.", "🤔 Не уверен.", "🤔 Спроси позже.",
            "❌ Скорее нет.", "❌ Не рассчитывай.", "❌ Нет."
        ]
        await event.reply(f"🎱 {random.choice(answers)}", parse_mode='md')

    @client.on(events.NewMessage(pattern=r'^/ping'))
    async def ping_cmd(event):
        import time
        start = time.time()
        msg = await event.reply("🏓 Pong...")
        ms = (time.time() - start) * 1000
        await msg.edit(f"🏓 **Pong!** `{ms:.0f}ms`", parse_mode='md')

    logging.info("Cubic module: зарегистрированы /cubic, /coin, /roll, /random, /8ball, /ping.")
