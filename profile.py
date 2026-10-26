"""Профиль пользователя."""
from datetime import datetime, timezone
from telegram import Update
from telegram.ext import ContextTypes, MessageHandler

import db
import config
from helpers import (
    is_admin_user, is_council_member, get_roles, RX, ensure_user,
)


def _marriage_level(days: int) -> int:
    return 1 + days // 7


def _fmt_marriage(mar, target_id, divorced) -> str:
    if not mar:
        if divorced > 0:
            return f"💔 разведён(а) ({divorced} раз)"
        return "—"
    u1, u2, forced, started_at = mar
    other = u2 if u1 == target_id else u1
    days = 0
    try:
        d = datetime.fromisoformat(started_at)
        days = max(0, (datetime.now(timezone.utc) - d).days)
    except Exception:
        pass
    level = _marriage_level(days)
    tag = " 💠принуд." if forced else ""
    return f"💍 id <code>{other}</code> · {days} дн. · ур.{level}{tag}"


async def profile_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    target = msg.from_user
    if msg.reply_to_message and msg.reply_to_message.from_user:
        target = msg.reply_to_message.from_user

    await ensure_user(target)
    chat_id = msg.chat_id

    row = await db.fetchone(
        "SELECT coins, credit, mutes_issued, reports, courts, "
        "ttt_wins, ttt_losses, ttt_played, divorced_count "
        "FROM users WHERE user_id=?",
        (target.id,),
    )
    coins, credit, mutes, reports, courts, wins, loses, played, divorced = (
        row if row else (100, 0, 0, 0, 0, 0, 0, 0, 0)
    )

    cnt = await db.fetchone(
        "SELECT msg_total FROM chat_users WHERE chat_id=? AND user_id=?",
        (chat_id, target.id),
    )
    msg_total = cnt[0] if cnt else 0

    mar = await db.fetchone(
        "SELECT user1_id, user2_id, forced, started_at FROM marriages "
        "WHERE chat_id=? AND active=1 AND (user1_id=? OR user2_id=?)",
        (chat_id, target.id, target.id),
    )
    marriage_text = _fmt_marriage(mar, target.id, divorced)

    if is_admin_user(target):
        role = "👑 Создатель"
        council = "👑 главный"
    else:
        roles = await get_roles(chat_id, target.id)
        if "commissar" in roles:
            role = "🎖 Комиссар"
        elif "sheriff" in roles:
            role = "⭐ Шериф"
        else:
            role = "👤 Участник"
        council = "✅ да" if await is_council_member(chat_id, target) else "—"

    name = "@" + target.username if target.username else target.first_name
    text = (
        f"👤 <b>Профиль:</b> {name}\n"
        f"💬 Сообщений: <b>{msg_total}</b>\n"
        f"💰 Монеты: <b>{coins}</b>\n"
        f"💳 Кредит: <b>{credit}/{config.CREDIT_MAX}</b>\n"
        f"{marriage_text}\n"
        f"🏛 Совет ССС: {council}\n"
        f"🎖 Роль: {role}\n"
        f"🎮 Крестики-нолики: ✅ {wins} · ❌ {loses} · 🎯 {played}\n"
        f"🔇 Выдано мутов: {mutes}\n"
        f"🚨 Жалоб подано: {reports}\n"
        f"⚖️ Инициировано судов: {courts}"
    )
    await msg.reply_text(text, parse_mode="HTML")


def register(app):
    app.add_handler(MessageHandler(RX(r"^профиль$"), profile_cmd))
