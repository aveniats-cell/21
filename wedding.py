"""Свадьбы: предложения, насильный брак, развод. Защита от дубликатов — триггеры в БД."""
import logging
from datetime import datetime, timezone
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, MessageHandler, CallbackQueryHandler

import db
from helpers import is_admin_user, MENTION_RE, RX, resolve_target

log = logging.getLogger(__name__)


async def _active_marriage(chat_id: int, uid: int):
    return await db.fetchone(
        "SELECT user1_id, user2_id, forced, started_at FROM marriages "
        "WHERE chat_id=? AND active=1 AND (user1_id=? OR user2_id=?)",
        (chat_id, uid, uid),
    )


async def _pair_in_marriage(chat_id: int, u1: int, u2: int):
    return await db.fetchone(
        "SELECT user1_id, user2_id FROM marriages "
        "WHERE chat_id=? AND active=1 AND (user1_id IN (?,?) OR user2_id IN (?,?))",
        (chat_id, u1, u2, u1, u2),
    )


async def _name_of(context, uid: int) -> str:
    try:
        c = await context.bot.get_chat(uid)
        return "@" + c.username if c.username else (c.first_name or str(uid))
    except Exception:
        return str(uid)


async def _insert_marriage(chat_id: int, a_id: int, b_id: int, forced: int) -> bool:
    """UPSERT с нормализованной парой. False — если БД отвергла (уже в браке)."""
    u1, u2 = sorted((a_id, b_id))
    now = datetime.now(timezone.utc).isoformat()
    try:
        await db.execute(
            "INSERT INTO marriages (chat_id, user1_id, user2_id, forced, started_at, active) "
            "VALUES (?,?,?,?,?,1) "
            "ON CONFLICT(chat_id, user1_id, user2_id) DO UPDATE SET "
            "  forced=excluded.forced, started_at=excluded.started_at, active=1",
            (chat_id, u1, u2, forced, now),
        )
        return True
    except Exception as e:
        log.warning("insert marriage rejected: %s", e)
        return False


async def propose(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    chat_id = msg.chat_id
    frm = msg.from_user
    tid, uname, _ = await resolve_target(update, context, msg.text)
    if not tid:
        await msg.reply_text("Пример: <code>Сделать предложение @user</code> (или реплай)", parse_mode="HTML")
        return
    if tid == frm.id:
        await msg.reply_text("Себе предложение делать нельзя 😅")
        return
    if await _active_marriage(chat_id, frm.id):
        await msg.reply_text("💍 Ты уже в браке в этом чате.")
        return
    if await _active_marriage(chat_id, tid):
        await msg.reply_text("💔 Этот человек уже в браке.")
        return

    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("💍 Согласиться", callback_data=f"wed:y:{chat_id}:{frm.id}:{tid}"),
        InlineKeyboardButton("💔 Отклонить",   callback_data=f"wed:n:{chat_id}:{frm.id}:{tid}"),
    ]])
    await msg.reply_text(
        f"💐 <b>Минуточку внимания!</b>\n\n"
        f"{await _name_of(context, frm.id)} делает предложение {await _name_of(context, tid)}!\n\n"
        f"<i>Что ответит вторая половинка?</i>",
        parse_mode="HTML",
        reply_markup=kb,
    )


async def wedding_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    try:
        _, decision, chat_id_s, frm_s, to_s = q.data.split(":")
        chat_id, frm_id, to_id = int(chat_id_s), int(frm_s), int(to_s)
    except Exception:
        await q.answer("Ошибка данных.", show_alert=True)
        return

    if q.from_user.id != to_id:
        await q.answer("Это предложение не тебе 💅", show_alert=True)
        return
    await q.answer()

    if decision == "n":
        await q.edit_message_text("💔 <b>Отказ.</b> Сердечко разбито, но жизнь продолжается.",
                                  parse_mode="HTML")
        return

    clash = await _pair_in_marriage(chat_id, frm_id, to_id)
    if clash:
        await q.edit_message_text("⚠️ Один из вас уже состоит в браке.")
        return

    ok = await _insert_marriage(chat_id, frm_id, to_id, forced=0)
    if not ok:
        await q.edit_message_text("⚠️ Не удалось создать брак — возможно, кто-то уже в браке.")
        return
    await q.edit_message_text("🎉 <b>Горько!</b> Молодожёны официально в браке 💒",
                              parse_mode="HTML")


async def force_marry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    if not is_admin_user(msg.from_user):
        await msg.reply_text("⛔ Только админ может женить насильно.")
        return
    mentions = MENTION_RE.findall(msg.text or "")
    if len(mentions) < 2:
        await msg.reply_text("Пример: <code>+Брак @u1 @u2</code>", parse_mode="HTML")
        return
    try:
        a = await context.bot.get_chat("@" + mentions[0])
        b = await context.bot.get_chat("@" + mentions[1])
    except Exception as e:
        await msg.reply_text(f"⚠️ Не нашёл пользователей: <code>{e}</code>", parse_mode="HTML")
        return
    if a.id == b.id:
        await msg.reply_text("Один и тот же человек 🤔")
        return
    clash = await _pair_in_marriage(msg.chat_id, a.id, b.id)
    if clash:
        await msg.reply_text("⚠️ Кто-то из них уже в браке в этом чате.")
        return
    ok = await _insert_marriage(msg.chat_id, a.id, b.id, forced=1)
    if not ok:
        await msg.reply_text("⚠️ Не удалось создать брак.")
        return
    await msg.reply_text(
        f"💒 <b>Принудительный брак!</b>\n@{mentions[0]} ❤️ @{mentions[1]} "
        f"(развести может только админ)",
        parse_mode="HTML",
    )


async def divorce(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    chat_id = msg.chat_id
    uid = msg.from_user.id
    row = await _active_marriage(chat_id, uid)
    if not row:
        if is_admin_user(msg.from_user):
            tid, uname, _ = await resolve_target(update, context, msg.text)
            if tid:
                row = await _active_marriage(chat_id, tid)
                if row:
                    u1, u2, _, _ = row
                    await db.execute(
                        "UPDATE marriages SET active=0 WHERE chat_id=? AND user1_id=? AND user2_id=?",
                        (chat_id, u1, u2),
                    )
                    await db.execute(
                        "UPDATE users SET divorced_count = divorced_count + 1 WHERE user_id IN (?,?)",
                        (u1, u2),
                    )
                    await msg.reply_text("💔 Брак расторгнут админом.")
                    return
        await msg.reply_text("Ты не в браке.")
        return
    u1, u2, forced, _ = row
    if forced and not is_admin_user(msg.from_user):
        await msg.reply_text("⚠️ Этот брак насильный — расторгнуть может только админ.")
        return
    await db.execute(
        "UPDATE marriages SET active=0 WHERE chat_id=? AND user1_id=? AND user2_id=?",
        (chat_id, u1, u2),
    )
    await db.execute(
        "UPDATE users SET divorced_count = divorced_count + 1 WHERE user_id IN (?,?)",
        (u1, u2),
    )
    await msg.reply_text("💔 Брак расторгнут.")


def register(app):
    app.add_handler(MessageHandler(RX(r"^сделать\s+предложение\b"), propose))
    app.add_handler(MessageHandler(RX(r"^[+]брак\b"), force_marry))
    app.add_handler(MessageHandler(RX(r"^[-]брак\b"), divorce))
    app.add_handler(CallbackQueryHandler(wedding_cb, pattern=r"^wed:"))
