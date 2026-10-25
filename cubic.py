import asyncio
import random
import re
import logging

from telethon import events


def register(client):
    @client.on(events.NewMessage(pattern=r'(?i)^/?удача\s+(.+)$'))
    async def cubic_cmd(event):
        text = event.pattern_match.group(1).strip()

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

    @client.on(events.NewMessage(pattern=r'(?i)^/?монетка$'))
    async def coin_cmd(event):
        result = random.choice(["🪙 **Орёл!**", "🪙 **Решка!**"])
        await event.reply(result, parse_mode='md')

    @client.on(events.NewMessage(pattern=r'(?i)^/?кубик(?:\s+(\S+))?$'))
    async def roll_cmd(event):
        dice = event.pattern_match.group(1) or "1d6"
        m = re.fullmatch(r'(\d*)d(\d+)', dice.lower())
        if not m:
            await event.reply("❌ Формат: `кубик 2d6` или `кубик d20`", parse_mode='md')
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

    @client.on(events.NewMessage(pattern=r'(?i)^/?рандом(?:\s+(\d+)\s+(\d+))?$'))
    async def random_cmd(event):
        a_str = event.pattern_match.group(1)
        b_str = event.pattern_match.group(2)
        if not a_str or not b_str:
            await event.reply("❌ Использование: `рандом 1 100`", parse_mode='md')
            return
        a, b = int(a_str), int(b_str)
        if a > b:
            a, b = b, a
        await event.reply(f"🎯 Случайное число: **{random.randint(a, b)}**", parse_mode='md')

    @client.on(events.NewMessage(pattern=r'(?i)^/?шар\s+(.+)$'))
    async def ball_cmd(event):
        text = event.pattern_match.group(1).strip()
        answers = [
            "✅ Да, определённо.", "✅ Безусловно.", "✅ Скорее да.",
            "🤔 Возможно.", "🤔 Не уверен.", "🤔 Спроси позже.",
            "❌ Скорее нет.", "❌ Не рассчитывай.", "❌ Нет."
        ]
        await event.reply(f"🎱 {random.choice(answers)}", parse_mode='md')

    @client.on(events.NewMessage(pattern=r'(?i)^/?пинг$'))
    async def ping_cmd(event):
        import time
        start = time.time()
        msg = await event.reply("🏓 Pong...")
        ms = (time.time() - start) * 1000
        await msg.edit(f"🏓 **Pong!** `{ms:.0f}ms`", parse_mode='md')

    logging.info("Cubic module: зарегистрированы 'удача', 'монетка', 'кубик', 'рандом', 'шар', 'пинг'.")
