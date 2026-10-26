"""Суды: ССС (единогласно) и обычный (большинство). +Суд под rate-limit."""
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, MessageHandler, PollAnswerHandler, PollHandler

import db
from helpers import (
    is_council_member, resolve_target, RX, ensure_user, rate_limit,
)

COURT_COOLDOWN = 30  # секунд между запусками суда одним пользователем


@rate_limit("court", COURT_COOLDOWN, "⏳ Суд можно запускать раз в {left}с.")
async def _start_court(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    chat_id = msg.chat_id
    text = (msg.text or "").strip()
    head = text.split(None, 1)
    rest = head[1] if len(head) > 1 else ""
    is_ccc = rest.lower().startswith("ссс")
    if is_ccc:
        rest = rest[3:].strip()
        if not await is_council_member(chat_id, msg.from_user):
            await msg.reply_text("⛔ Только Совет ССС может запускать <b>суд ССС</b>.", parse_mode="HTML")
            return

    tid, uname, _ = await resolve_target(update, context, rest or text)
    if not tid:
        await msg.reply_text("Укажи, над кем суд: реплай или @username.")
        return
    if tid == msg.from_user.id:
        await msg.reply_text("Себя судить нельзя 🙂")
        return

    await ensure_user(msg.from_user)
    await db.execute(
        "UPDATE users SET courts = courts + 1 WHERE user_id=?", (msg.from_user.id,)
    )

    if is_ccc:
        council = await db.fetchall("SELECT user_id FROM council WHERE chat_id=?", (chat_id,))
        voters = {u for (u,) in council}
        admin_id = context.application.bot_data.get("admin_id")
        if admin_id:
            voters.add(admin_id)
        kind = "ccc"
        question = f"🏛 Суд ССС: заблокировать @{uname or tid}? (все ССС должны быть ЗА)"
    else:
        voters = set()
        kind = "regular"
        question = f"⚖️ Суд: заблокировать @{uname or tid}? (большинство)"

    poll_msg = await context.bot.send_poll(
        chat_id=chat_id,
        question=question,
        options=["За (бан)", "Против"],
        is_anonymous=False,
        open_period=180,
    )
    context.application.bot_data.setdefault("courts", {})[poll_msg.poll.id] = {
        "chat_id": chat_id,
        "message_id": poll_msg.message_id,
        "target_id": tid,
        "target_name": uname or str(tid),
        "kind": kind,
        "voters": voters,
        "votes": {},
    }
    await msg.reply_text(
        "🗳 Голосование запущено на <b>3 минуты</b>."
        + (" <i>Только для ССС.</i>" if is_ccc else ""),
        parse_mode="HTML",
    )


async def poll_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ans = update.poll_answer
    cd = context.application.bot_data.get("courts", {}).get(ans.poll_id)
    if not cd:
        return
    if cd["voters"] and ans.user.id not in cd["voters"]:
        return
    if not ans.option_ids:
        return
    cd["votes"][ans.user.id] = ans.option_ids[0]

    need_all = cd["kind"] == "ccc" and cd["voters"]
    if need_all and set(cd["votes"]) >= cd["voters"]:
        try:
            await context.bot.stop_poll(cd["chat_id"], cd["message_id"])
        except Exception:
            pass
    elif cd["kind"] == "regular" and len(cd["votes"]) >= 5:
        try:
            await context.bot.stop_poll(cd["chat_id"], cd["message_id"])
        except Exception:
            pass


async def poll_closed(update: Update, context: ContextTypes.DEFAULT_TYPE):
    poll = update.poll
    if not poll.is_closed:
        return
    cd = context.application.bot_data.get("courts", {}).pop(poll.id, None)
    if not cd:
        return

    yes = sum(1 for v in cd["votes"].values() if v == 0)
    no  = sum(1 for v in cd["votes"].values() if v == 1)
    chat_id, tid = cd["chat_id"], cd["target_id"]

    if cd["kind"] == "ccc":
        if cd["voters"] and yes >= len(cd["voters"]) and no == 0:
            try:
                await context.bot.ban_chat_member(chat_id, tid)
                await context.bot.send_message(
                    chat_id,
                    f"🔨 <b>Совет ССС единогласно:</b> @{cd['target_name']} забанен.",
                    parse_mode="HTML",
                )
            except Exception as e:
                await context.bot.send_message(chat_id, f"⚠️ Ошибка бана: <code>{e}</code>", parse_mode="HTML")
        else:
            await context.bot.send_message(
                chat_id,
                f"🕊 <b>Суд ССС:</b> @{cd['target_name']} оправдан (За: {yes}, Против: {no}).",
                parse_mode="HTML",
            )
    else:
        verdict = "ЗА БАН" if yes > no else "ОПРАВДАТЬ"
        admin_id = context.application.bot_data.get("admin_id")
        if admin_id:
            kb = InlineKeyboardMarkup([[
                InlineKeyboardButton("Забанить", callback_data=f"ctch:y:{chat_id}:{tid}"),
                InlineKeyboardButton("Оставить", callback_data=f"ctch:n:{chat_id}:{tid}"),
            ]])
            try:
                await context.bot.send_message(
                    admin_id,
                    f"⚖️ <b>Обычный суд</b> в чате <code>{chat_id}</code>\n"
                    f"Подсудимый: @{cd['target_name']} (id <code>{tid}</code>)\n"
                    f"За: {yes} · Против: {no}\n<b>Решение: {verdict}</b>",
                    parse_mode="HTML",
                    reply_markup=kb,
                )
            except Exception:
                pass
        await context.bot.send_message(
            chat_id,
            f"📜 Суд завершён. За: {yes} · Против: {no}. Решение отправлено админу.",
        )


def register(app):
    app.add_handler(MessageHandler(RX(r"^[+]суд\b"), _start_court))
    app.add_handler(PollAnswerHandler(poll_answer))
    app.add_handler(PollHandler(poll_closed))
