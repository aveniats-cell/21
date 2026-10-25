import asyncio
import logging
import random
import re
import time
from html import escape as esc

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes, MessageHandler, filters

logger = logging.getLogger(__name__)

ROLL_RE = re.compile(r"^/?удача\s+(.+)$", re.IGNORECASE)
COIN_RE = re.compile(r"^/?монетка$", re.IGNORECASE)
DICE_RE = re.compile(r"^/?кубик(?:\s+(\S+))?$", re.IGNORECASE)
RANDOM_RE = re.compile(r"^/?рандом(?:\s+(\d+)\s+(\d+))?$", re.IGNORECASE)
BALL_RE = re.compile(r"^/?шар\s+(.+)$", re.IGNORECASE)
PING_RE = re.compile(r"^/?пинг$", re.IGNORECASE)


def register(app) -> None:
    async def cubic_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        msg = update.effective_message
        m = ROLL_RE.match(msg.text or "")
        if not m:
            return
        text = m.group(1).strip()

        options = [o.strip() for o in re.split(r"[,;]|\s+или\s+", text) if o.strip()]
        if len(options) < 2:
            await msg.reply_text("❌ Нужно минимум 2 варианта, разделённых запятой.")
            return
        if len(options) > 30:
            await msg.reply_text("❌ Слишком много вариантов (максимум 30).")
            return

        spin_msg = await msg.reply_text("🎰 Крутим рулетку...")
        for delay in (0.08, 0.10, 0.13, 0.16, 0.20, 0.25, 0.32, 0.40, 0.50):
            frame = random.choice(options)
            try:
                await spin_msg.edit_text(f"🎰 Крутим... <b>{esc(frame)}</b>", parse_mode=ParseMode.HTML)
            except Exception:
                pass
            await asyncio.sleep(delay)

        winner = random.choice(options)
        opts_display = (
            ", ".join(esc(o) for o in options)
            if len(options) <= 10
            else ", ".join(esc(o) for o in options[:10]) + f" и ещё {len(options) - 10}..."
        )

        try:
            await spin_msg.edit_text(
                f"🎰 <b>Рулетка завершена!</b>\n\n"
                f"📋 Варианты: {opts_display}\n\n"
                f"🎯 Выпало: <b>{esc(winner)}</b>",
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            await msg.reply_text(f"🎰 Выпало: <b>{esc(winner)}</b>", parse_mode=ParseMode.HTML)

    async def coin_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await update.effective_message.reply_text(
            random.choice(["🪙 <b>Орёл!</b>", "🪙 <b>Решка!</b>"]),
            parse_mode=ParseMode.HTML,
        )

    async def roll_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        msg = update.effective_message
        m = DICE_RE.match(msg.text or "")
        dice = (m.group(1) if m and m.group(1) else "1d6")
        mm = re.fullmatch(r"(\d*)d(\d+)", dice.lower())
        if not mm:
            await msg.reply_text("❌ Формат: <code>кубик 2d6</code> или <code>кубик d20</code>",
                                 parse_mode=ParseMode.HTML)
            return
        count = int(mm.group(1)) if mm.group(1) else 1
        sides = int(mm.group(2))
        if count < 1 or count > 20 or sides < 2 or sides > 1000:
            await msg.reply_text("❌ Слишком много кубиков или граней.")
            return
        rolls = [random.randint(1, sides) for _ in range(count)]
        total = sum(rolls)
        detail = " + ".join(map(str, rolls)) if count > 1 else str(rolls[0])
        suffix = f" = <b>{total}</b>" if count > 1 else ""
        await msg.reply_text(f"🎲 <b>{esc(dice)}</b> → {detail}{suffix}", parse_mode=ParseMode.HTML)

    async def random_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        msg = update.effective_message
        m = RANDOM_RE.match(msg.text or "")
        if not m or not m.group(1) or not m.group(2):
            await msg.reply_text("❌ Использование: <code>рандом 1 100</code>", parse_mode=ParseMode.HTML)
            return
        a, b = int(m.group(1)), int(m.group(2))
        if a > b:
            a, b = b, a
        await msg.reply_text(f"🎯 Случайное число: <b>{random.randint(a, b)}</b>",
                             parse_mode=ParseMode.HTML)

    async def ball_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        msg = update.effective_message
        if not BALL_RE.match(msg.text or ""):
            return
        answers = [
            "✅ Да, определённо.", "✅ Безусловно.", "✅ Скорее да.",
            "🤔 Возможно.", "🤔 Не уверен.", "🤔 Спроси позже.",
            "❌ Скорее нет.", "❌ Не рассчитывай.", "❌ Нет.",
        ]
        await msg.reply_text(f"🎱 {random.choice(answers)}", parse_mode=ParseMode.HTML)

    async def ping_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        msg = update.effective_message
        start = time.time()
        sent = await msg.reply_text("🏓 Pong...")
        ms = (time.time() - start) * 1000
        await sent.edit_text(f"🏓 <b>Pong!</b> <code>{ms:.0f}ms</code>", parse_mode=ParseMode.HTML)

    app.add_handler(MessageHandler(filters.Regex(ROLL_RE), cubic_cmd))
    app.add_handler(MessageHandler(filters.Regex(COIN_RE), coin_cmd))
    app.add_handler(MessageHandler(filters.Regex(DICE_RE), roll_cmd))
    app.add_handler(MessageHandler(filters.Regex(RANDOM_RE), random_cmd))
    app.add_handler(MessageHandler(filters.Regex(BALL_RE), ball_cmd))
    app.add_handler(MessageHandler(filters.Regex(PING_RE), ping_cmd))

    logger.info("Cubic module: 'удача', 'монетка', 'кубик', 'рандом', 'шар', 'пинг' зарегистрированы.")
