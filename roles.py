"""Роли: Шериф, Комиссар, Совет ССС."""
from telegram import Update
from telegram.ext import ContextTypes, MessageHandler

import db
from helpers import is_admin_user, resolve_target, RX


async def _name_of(context, uid: int) -> str:
    try:
        c = await context.bot.get_chat(uid)
        if c.username:
            return "@" + c.username
        return c.first_name or str(uid)
    except Exception:
        return str(uid)


async def _add_role(update, context, role: str, label: str):
    msg = update.effective_message
    if not is_admin_user(msg.from_user):
        await msg.reply_text("⛔ Только главный администратор может выдавать роли.")
        return
    tid, uname, _ = await resolve_target(update, context, msg.text)
    if not tid:
        await msg.reply_text(
            f"Укажи пользователя реплаем или @username.\nПример: <code>+{label} @user</code>",
            parse_mode="HTML",
        )
        return
    await db.execute(
        "INSERT OR IGNORE INTO roles (chat_id, user_id, role) VALUES (?,?,?)",
        (msg.chat_id, tid, role),
    )
    await msg.reply_text(f"✅ <b>{await _name_of(context, tid)}</b> теперь <b>{label}</b>.", parse_mode="HTML")


async def _del_role(update, context, role: str, label: str):
    msg = update.effective_message
    if not is_admin_user(msg.from_user):
        await msg.reply_text("⛔ Только главный администратор может снимать роли.")
        return
    tid, uname, _ = await resolve_target(update, context, msg.text)
    if not tid:
        await msg.reply_text(f"Укажи пользователя.\nПример: <code>-{label} @user</code>", parse_mode="HTML")
        return
    await db.execute(
        "DELETE FROM roles WHERE chat_id=? AND user_id=? AND role=?",
        (msg.chat_id, tid, role),
    )
    await msg.reply_text(f"❌ <b>{await _name_of(context, tid)}</b> больше не <b>{label}</b>.", parse_mode="HTML")


async def _list_role(update, context, role: str, label: str):
    msg = update.effective_message
    rows = await db.fetchall(
        "SELECT user_id FROM roles WHERE chat_id=? AND role=?", (msg.chat_id, role)
    )
    if not rows:
        await msg.reply_text(f"Список пуст: <b>{label}ов</b> нет.", parse_mode="HTML")
        return
    lines = [f"• {await _name_of(context, uid)}" for (uid,) in rows]
    await msg.reply_text(f"👥 <b>{label}ы:</b>\n" + "\n".join(lines), parse_mode="HTML")


async def add_sheriff(u, c):     await _add_role(u, c, "sheriff", "Шериф")
async def del_sheriff(u, c):     await _del_role(u, c, "sheriff", "Шериф")
async def list_sheriffs(u, c):   await _list_role(u, c, "sheriff", "Шериф")

async def add_commissar(u, c):   await _add_role(u, c, "commissar", "Комиссар")
async def del_commissar(u, c):   await _del_role(u, c, "commissar", "Комиссар")
async def list_commissars(u, c): await _list_role(u, c, "commissar", "Комиссар")


async def add_ccc(update, context):
    msg = update.effective_message
    if not is_admin_user(msg.from_user):
        await msg.reply_text("⛔ Только главный администратор добавляет в ССС.")
        return
    tid, uname, _ = await resolve_target(update, context, msg.text)
    if not tid:
        await msg.reply_text("Пример: <code>+ССС @user</code>", parse_mode="HTML")
        return
    already = await db.fetchone(
        "SELECT 1 FROM council WHERE chat_id=? AND user_id=?", (msg.chat_id, tid)
    )
    if already:
        await msg.reply_text("Этот пользователь уже в ССС.")
        return
    cnt = await db.fetchone("SELECT COUNT(*) FROM council WHERE chat_id=?", (msg.chat_id,))
    if cnt[0] >= 3:
        await msg.reply_text("⚠️ Состав ССС уже полон (макс. 4 человека с админом).")
        return
    await db.execute(
        "INSERT OR IGNORE INTO council (chat_id, user_id) VALUES (?,?)",
        (msg.chat_id, tid),
    )
    await msg.reply_text(f"🏛 <b>{await _name_of(context, tid)}</b> вошёл в Совет ССС.", parse_mode="HTML")


async def del_ccc(update, context):
    msg = update.effective_message
    if not is_admin_user(msg.from_user):
        await msg.reply_text("⛔ Только админ.")
        return
    tid, uname, _ = await resolve_target(update, context, msg.text)
    if not tid:
        return
    await db.execute(
        "DELETE FROM council WHERE chat_id=? AND user_id=?", (msg.chat_id, tid)
    )
    await msg.reply_text(f"🗑 <b>{await _name_of(context, tid)}</b> исключён из ССС.", parse_mode="HTML")


async def list_ccc(update, context):
    msg = update.effective_message
    rows = await db.fetchall("SELECT user_id FROM council WHERE chat_id=?", (msg.chat_id,))
    admin_m = f"👑 @{context.bot_data.get('admin_username', 'admin')} (главный)"
    lines = [admin_m] + [f"• {await _name_of(context, uid)}" for (uid,) in rows]
    await msg.reply_text("🏛 <b>Совет ССС:</b>\n" + "\n".join(lines), parse_mode="HTML")


def register(app):
    app.add_handler(MessageHandler(RX(r"^[+]шериф\b"),     add_sheriff))
    app.add_handler(MessageHandler(RX(r"^[-]шериф\b"),     del_sheriff))
    app.add_handler(MessageHandler(RX(r"^шерифы$"),        list_sheriffs))
    app.add_handler(MessageHandler(RX(r"^[+]комиссар\b"),  add_commissar))
    app.add_handler(MessageHandler(RX(r"^[-]комиссар\b"),  del_commissar))
    app.add_handler(MessageHandler(RX(r"^комиссары$"),     list_commissars))
    app.add_handler(MessageHandler(RX(r"^[+]ссс\b"),       add_ccc))
    app.add_handler(MessageHandler(RX(r"^[-]ссс\b"),       del_ccc))
    app.add_handler(MessageHandler(RX(r"^ссс$"),           list_ccc))
