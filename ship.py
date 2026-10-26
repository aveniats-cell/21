"""Шип @u1 @u2 — шутливые фразочки про пару."""
import random
from telegram import Update
from telegram.ext import ContextTypes, MessageHandler

from helpers import MENTION_RE, RX

PHRASES = [
    "💘 {a} и {b} — уже тайно встречаются по ночам!",
    "💍 {a} давно копит на кольцо для {b}…",
    "🔥 Между {a} и {b} сегодня было минимум 3 страстных взгляда.",
    "🥀 {a}, похоже, уже год влюблён(а) в {b}, но молчит.",
    "🍿 Свадьба {a} и {b} — уже запланирована на следующее лето.",
    "💐 {b} снится {a} каждую ночь.",
    "🌈 {a} и {b} — идеальная пара, доказано ботом.",
    "🎻 Романтик-уровень {a} и {b}: 9.9/10.",
    "🌹 {a} поставил(а) на заставку фото {b}, но бот всё видит.",
    "💌 Анонимные валентинки от {a} в этом чате идут только {b}.",
]


async def ship(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    mentions = MENTION_RE.findall(msg.text or "")
    if len(mentions) < 2:
        await msg.reply_text("Пример: <code>Шип @user1 @user2</code>", parse_mode="HTML")
        return
    a, b = "@" + mentions[0], "@" + mentions[1]
    if a == b:
        await msg.reply_text("Себя с собой шипить — это уже нарциссизм 😄")
        return
    await msg.reply_text(random.choice(PHRASES).format(a=a, b=b))


def register(app):
    app.add_handler(MessageHandler(RX(r"^шип\b"), ship))
