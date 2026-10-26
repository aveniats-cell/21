"""PR-функция: обязательная подписка на каналы. Кэш на 5 минут + фоновая чистка."""
import logging
import re
import time
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ContextTypes, MessageHandler, ApplicationHandlerStop, filters,
)

import db
from helpers import is_admin_user, chat_admin_ids, RX

log = logging.getLogger(__name__)
CACHE_TTL = 300
ADMIN_CACHE_TTL = 180


async def _chat_admins_cached(context, chat_id: int) -> set:
    cache = context.application.bot_data.setdefault("admins_cache", {})
    now = time.time()
    if chat_id in cache:
        ids, ts = cache[chat_id]
        if now - ts < ADMIN_CACHE_TTL:
            return ids
    ids = await chat_admin_ids(context, chat_id)
    cache[chat_id] = (ids, now)
    return ids


def cleanup_caches(application):
    """Удаляет просроченные записи pr_cache / admins_cache. Синхронно."""
    now = time.time()
    pr_cache = application.bot_data.get("pr_cache", {})
    for k in list(pr_cache.keys()):
        try:
            _, ts = pr_cache[k]
        except Exception:
            pr_cache.pop(k, None)
            continue
        if now - ts > CACHE_TTL:
            pr_cache.pop(k, None)

    admins = application.bot_data.get("admins_cache", {})
    for cid in list(admins.keys()):
        try:
            _, ts = admins[cid]
        except Exception:
            admins.pop(cid, None)
            continue
        if now - ts > ADMIN_CACHE_TTL:
            admins.pop(cid, None)


async def add_pr(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    if not is_admin_user(msg.from_user):
        await msg.reply_text("⛔ Только админ.")
        return
    m = re.search(r"@([A-Za-z0-9_]{4,32})", msg.text or "")
    if not m:
        await msg.reply_text("Пример: <code>+ПР @channel</code>", parse_mode="HTML")
        return
    ch = "@" + m.group(1)
    try:
        await context.bot.get_chat(ch)
    except Exception as e:
        await msg.reply_text(f"⚠️ Не могу получить канал {ch}: <code>{e}</code>", parse_mode="HTML")
        return
    await db.execute(
        "INSERT OR IGNORE INTO pr_channels (chat_id, channel) VALUES (?,?)",
        (msg.chat_id, ch),
    )
    await msg.reply_text(f"✅ Канал <b>{ch}</b> добавлен в PR.", parse_mode="HTML")


async def del_pr(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    if not is_admin_user(msg.from_user):
        await msg.reply_text("⛔ Только админ.")
        return
    m = re.search(r"@([A-Za-z0-9_]{4,32})", msg.text or "")
    if not m:
        return
    ch = "@" + m.group(1)
    await db.execute("DELETE FROM pr_channels WHERE chat_id=? AND channel=?", (msg.chat_id, ch))
    await msg.reply_text(f"🗑 <b>{ch}</b> убран из PR.", parse_mode="HTML")


async def list_pr(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    rows = await db.fetchall("SELECT channel FROM pr_channels WHERE chat_id=?", (msg.chat_id,))
    if not rows:
        await msg.reply_text("PR-каналов нет.")
        return
    await msg.reply_text(
        "📢 <b>Обязательные каналы:</b>\n" + "\n".join("• " + r[0] for r in rows),
        parse_mode="HTML",
    )


async def pr_guard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    if not msg:
        return
    if msg.chat.type not in ("group", "supergroup"):
        return
    if not msg.from_user or msg.from_user.is_bot:
        return
    content = msg.text or msg.caption or ""
    if not content:
        return
    if content.startswith("/"):
        return
    rows = await db.fetchall("SELECT channel FROM pr_channels WHERE chat_id=?", (msg.chat_id,))
    if not rows:
        return
    if is_admin_user(msg.from_user):
        return
    chat_admins = await _chat_admins_cached(context, msg.chat_id)
    if msg.from_user.id in chat_admins:
        return

    uid = msg.from_user.id
    cache = context.application.bot_data.setdefault("pr_cache", {})
    now = time.time()
    missing = None
    for (ch,) in rows:
        key = (msg.chat_id, uid, ch)
        cached = cache.get(key)
        if cached and now - cached[1] < CACHE_TTL:
            ok = cached[0]
        else:
            try:
                m = await context.bot.get_chat_member(ch, uid)
                ok = m.status in ("member", "administrator", "creator")
            except Exception as e:
                log.warning("PR check fail %s: %s", ch, e)
                ok = True
            cache[key] = (ok, now)
        if not ok:
            missing = ch
            break

    if not missing:
        return

    try:
        await msg.delete()
    except Exception:
        pass

    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("📢 Подписаться", url=f"https://t.me/{missing.lstrip('@')}")
    ]])
    name = "@" + msg.from_user.username if msg.from_user.username else msg.from_user.first_name
    try:
        await context.bot.send_message(
            msg.chat_id,
            f"👋 {name}, сначала подпишись на канал <b>{missing}</b>, затем напиши снова.",
            parse_mode="HTML",
            reply_markup=kb,
        )
    except Exception:
        pass

    raise ApplicationHandlerStop


def register(app):
    app.add_handler(MessageHandler(RX(r"^[+]пр\b"), add_pr))
    app.add_handler(MessageHandler(RX(r"^[-]пр\b"), del_pr))
    app.add_handler(MessageHandler(RX(r"^пр$"),     list_pr))
    app.add_handler(
        MessageHandler(filters.ALL & ~filters.COMMAND & ~filters.StatusUpdate.ALL, pr_guard),
        group=-1,
    )
