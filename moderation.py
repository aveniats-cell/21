"""Мут, бан, размут, разбан, «Поймать» (шериф → админ в ЛС)."""
from datetime import datetime, timezone, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ChatPermissions
from telegram.ext import ContextTypes, MessageHandler, CallbackQueryHandler

import config
import db
from helpers import (
    is_admin_user, can_moderate, is_sheriff,
    resolve_target, parse_duration, fmt_duration, RX, ensure_user, MENTION_RE,
)

MUTED_PERMS = ChatPermissions(
    can_send_messages=False,
    can_send_audios=False,
    can_send_documents=False,
    can_send_photos=False,
    can_send_videos=False,
    can_send_video_notes=False,
    can_send_voice_notes=False,
    can_send_polls=False,
    can_send_other_messages=False,
    can_add_web_page_previews=False,
)

FULL_PERMS = ChatPermissions(
    can_send_messages=True,
    can_send_audios=True,
    can_send_documents=True,
    can_send_photos=True,
    can_send_videos=True,
    can_send_video_notes=True,
    can_send_voice_notes=True,
    can_send_polls=True,
    can_send_other_messages=True,
    can_add_web_page_previews=True,
    can_invite_users=False,
)


async def _target_name(context, tid, uname):
    if uname:
        return "@" + uname
    try:
        c = await context.bot.get_chat(tid)
        return c.first_name or str(tid)
    except Exception:
        return str(tid)


async def mute_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    if not await can_moderate(msg.chat_id, msg.from_user):
        await msg.reply_text("⛔ Только <b>админ</b> или <b>комиссар</b> может выдавать мут.", parse_mode="HTML")
        return
    tid, uname, _ = await resolve_target(update, context, msg.text)
    if not tid:
        await msg.reply_text("Пример: <code>+Мут @user 1ч 30м</code> (или реплай)", parse_mode="HTML")
        return
    clean = MENTION_RE.sub(" ", msg.text or "")
    dur = parse_duration(clean)
    if dur <= 0:
        await msg.reply_text("⚠️ Укажи время: <code>1ч 30м 15с</code>", parse_mode="HTML")
        return
    if dur > config.MAX_MUTE_SEC:
        dur = config.MAX_MUTE_SEC
    until = datetime.now(timezone.utc) + timedelta(seconds=dur)
    try:
        await context.bot.restrict_chat_member(
            msg.chat_id, tid,
            permissions=MUTED_PERMS,
            until_date=until,
        )
    except Exception as e:
        await msg.reply_text(f"⚠️ Не удалось замутить: <code>{e}</code>", parse_mode="HTML")
        return
    await ensure_user(msg.from_user)
    await db.execute(
        "UPDATE users SET mutes_issued = mutes_issued + 1 WHERE user_id=?",
        (msg.from_user.id,),
    )
    await msg.reply_text(
        f"🔇 <b>{await _target_name(context, tid, uname)}</b> замучен на <b>{fmt_duration(dur)}</b>.",
        parse_mode="HTML",
    )


async def unmute_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    if not await can_moderate(msg.chat_id, msg.from_user):
        await msg.reply_text("⛔ Только админ или комиссар.")
        return
    tid, uname, _ = await resolve_target(update, context, msg.text)
    if not tid:
        return
    try:
        await context.bot.restrict_chat_member(msg.chat_id, tid, permissions=FULL_PERMS)
        await msg.reply_text(
            f"🔊 <b>{await _target_name(context, tid, uname)}</b> размучен.",
            parse_mode="HTML",
        )
    except Exception as e:
        await msg.reply_text(f"⚠️ Ошибка: <code>{e}</code>", parse_mode="HTML")


async def ban_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    if not await can_moderate(msg.chat_id, msg.from_user):
        await msg.reply_text("⛔ Только админ или комиссар.")
        return
    tid, uname, _ = await resolve_target(update, context, msg.text)
    if not tid:
        return
    try:
        await context.bot.ban_chat_member(msg.chat_id, tid)
        await msg.reply_text(
            f"🚫 <b>{await _target_name(context, tid, uname)}</b> забанен.",
            parse_mode="HTML",
        )
    except Exception as e:
        await msg.reply_text(f"⚠️ Ошибка бана: <code>{e}</code>", parse_mode="HTML")


async def unban_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    if not await can_moderate(msg.chat_id, msg.from_user):
        await msg.reply_text("⛔ Только админ или комиссар.")
        return
    tid, uname, _ = await resolve_target(update, context, msg.text)
    if not tid:
        return
    try:
        await context.bot.unban_chat_member(msg.chat_id, tid)
        await msg.reply_text(
            f"✅ <b>{await _target_name(context, tid, uname)}</b> разбанен.",
            parse_mode="HTML",
        )
    except Exception as e:
        await msg.reply_text(f"⚠️ Ошибка: <code>{e}</code>", parse_mode="HTML")


async def catch_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    chat_id = msg.chat_id
    if not await is_sheriff(chat_id, msg.from_user):
        await msg.reply_text("⛔ Только <b>шериф</b> (или админ) может ловить.", parse_mode="HTML")
        return
    tid, uname, _ = await resolve_target(update, context, msg.text)
    if not tid:
        await msg.reply_text("Укажи пользователя реплаем или @username.")
        return
    admin_id = context.application.bot_data.get("admin_id")
    if not admin_id:
        await msg.reply_text("⚠️ Бот не знает id админа. Пусть админ напишет боту /start в ЛС.")
        return

    await ensure_user(msg.from_user)
    await db.execute(
        "UPDATE users SET reports = reports + 1 WHERE user_id=?", (msg.from_user.id,)
    )
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Принять (бан)", callback_data=f"ctch:y:{chat_id}:{tid}"),
        InlineKeyboardButton("❌ Отклонить",     callback_data=f"ctch:n:{chat_id}:{tid}"),
    ]])
    title = msg.chat.title or str(chat_id)
    try:
        await context.bot.send_message(
            admin_id,
            f"🚨 <b>Подозрение</b>\n"
            f"Шериф: {await _target_name(context, msg.from_user.id, msg.from_user.username)}\n"
            f"Чат: <b>{title}</b>\n"
            f"Нарушитель: <b>{await _target_name(context, tid, uname)}</b>",
            parse_mode="HTML",
            reply_markup=kb,
        )
        await msg.reply_text("📨 Заявка отправлена админу на рассмотрение.")
    except Exception as e:
        await msg.reply_text(f"⚠️ Не смог отправить админу: <code>{e}</code>", parse_mode="HTML")


async def catch_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not is_admin_user(q.from_user):
        await q.answer("Только админ может решать.", show_alert=True)
        return
    await q.answer()
    try:
        _, decision, chat_id_s, tid_s = q.data.split(":")
        chat_id, tid = int(chat_id_s), int(tid_s)
        if decision == "y":
            await context.bot.ban_chat_member(chat_id, tid)
            await q.edit_message_text(q.message.text + "\n\n🚫 <b>Решение: БАН</b>", parse_mode="HTML")
        else:
            await q.edit_message_text(q.message.text + "\n\n✅ <b>Отклонено.</b>", parse_mode="HTML")
    except Exception as e:
        await q.edit_message_text(q.message.text + f"\n\n⚠️ Ошибка: <code>{e}</code>", parse_mode="HTML")


def register(app):
    app.add_handler(MessageHandler(RX(r"^[+]мут\b"),   mute_cmd))
    app.add_handler(MessageHandler(RX(r"^[-]мут\b"),   unmute_cmd))
    app.add_handler(MessageHandler(RX(r"^[+]бан\b"),   ban_cmd))
    app.add_handler(MessageHandler(RX(r"^[-]бан\b"),   unban_cmd))
    app.add_handler(MessageHandler(RX(r"^поймать\b"), catch_cmd))
    app.add_handler(CallbackQueryHandler(catch_cb, pattern=r"^ctch:"))
