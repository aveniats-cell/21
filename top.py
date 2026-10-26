"""Топ чата: день, всё время, моё место."""
from telegram import Update
from telegram.ext import ContextTypes, MessageHandler

import db
from helpers import today_str, RX


def _name_from_row(uid: int, username, first_name) -> str:
    if username:
        return "@" + username
    if first_name:
        return first_name
    return str(uid)


async def top_day(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    rows = await db.fetchall(
        "SELECT cu.user_id, cu.msg_day, u.username, u.first_name "
        "FROM chat_users cu LEFT JOIN users u ON u.user_id = cu.user_id "
        "WHERE cu.chat_id=? AND cu.day_date=? "
        "ORDER BY cu.msg_day DESC LIMIT 50",
        (msg.chat_id, today_str()),
    )
    if not rows:
        await msg.reply_text("📊 Сегодня ещё никто не писал.")
        return
    lines = [f"<b>{i}.</b> {_name_from_row(uid, un, fn)} — <b>{cnt}</b>"
             for i, (uid, cnt, un, fn) in enumerate(rows, 1)]
    await msg.reply_text("📊 <b>Топ дня:</b>\n" + "\n".join(lines), parse_mode="HTML")


async def top_all(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    rows = await db.fetchall(
        "SELECT cu.user_id, cu.msg_total, u.username, u.first_name "
        "FROM chat_users cu LEFT JOIN users u ON u.user_id = cu.user_id "
        "WHERE cu.chat_id=? "
        "ORDER BY cu.msg_total DESC LIMIT 50",
        (msg.chat_id,),
    )
    if not rows:
        await msg.reply_text("📊 Пока никто не писал.")
        return
    lines = [f"<b>{i}.</b> {_name_from_row(uid, un, fn)} — <b>{cnt}</b>"
             for i, (uid, cnt, un, fn) in enumerate(rows, 1)]
    await msg.reply_text("🏆 <b>Топ за всё время:</b>\n" + "\n".join(lines), parse_mode="HTML")


async def my_place(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    uid = msg.from_user.id
    row = await db.fetchone(
        "SELECT msg_total FROM chat_users WHERE chat_id=? AND user_id=?",
        (msg.chat_id, uid),
    )
    if not row:
        await msg.reply_text("Ты ещё не писал в этом чате.")
        return
    my = row[0]
    higher = await db.fetchone(
        "SELECT COUNT(*) FROM chat_users WHERE chat_id=? AND msg_total > ?",
        (msg.chat_id, my),
    )
    total = await db.fetchone(
        "SELECT COUNT(*) FROM chat_users WHERE chat_id=?", (msg.chat_id,)
    )
    await msg.reply_text(
        f"📍 <b>Твоё место: {higher[0] + 1}/{total[0]}</b> (сообщений: {my})",
        parse_mode="HTML",
    )


def register(app):
    app.add_handler(MessageHandler(RX(r"^топ\s+день$"),   top_day))
    app.add_handler(MessageHandler(RX(r"^топ\s+все$"),    top_all))
    app.add_handler(MessageHandler(RX(r"^мое\s+место$"),  my_place))
