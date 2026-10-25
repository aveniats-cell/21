import asyncio
import datetime
import logging
from collections import defaultdict
from telegram import Update, ChatPermissions, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, ContextTypes
)

# === НАСТРОЙКИ ===
BOT_TOKEN = "YOUR_BOT_TOKEN"  # ← замените на реальный токен
HOLY_TRINITY = {1319217425, 5376112672, 855714453}  # «святая тройка»
MAX_REQUESTS_PER_DAY = 2
VOTE_TIMEOUT = 300            # 5 минут
MUTE_DURATION = 60 * 60 * 24  # 24 часа мут (если голосование не завершится)

logging.basicConfig(level=logging.INFO)

# === ХРАНИЛИЩА ===
daily_requests = defaultdict(lambda: {"date": datetime.date.today(), "count": 0})
# chat_id -> {target_id: {"initiator", "votes": {uid: "ban"/"noban"}, "message_id",
#                         "task", "started_by_admin", "allowed_voters": set}}
active_votes = defaultdict(dict)
muted_users = {}          # user_id -> datetime окончания мута
pending_admin_votes = {}  # target_id -> {chat_id, initiator, target_id}


# === ВСПОМОГАТЕЛЬНЫЕ ===
def check_daily_limit(user_id: int) -> bool:
    today = datetime.date.today()
    rec = daily_requests[user_id]
    if rec["date"] != today:
        rec["date"] = today
        rec["count"] = 0
    if user_id in HOLY_TRINITY:
        return True
    if rec["count"] < MAX_REQUESTS_PER_DAY:
        rec["count"] += 1
        return True
    return False


async def set_permissions(context, chat_id, user_id, can_send: bool):
    try:
        await context.bot.restrict_chat_member(
            chat_id, user_id,
            permissions=ChatPermissions(
                can_send_messages=can_send,
                can_send_media_messages=can_send,
                can_send_other_messages=can_send,
                can_add_web_page_previews=can_send
            )
        )
        return True
    except Exception as e:
        logging.error(f"restrict error: {e}")
        return False


async def mute_user(context, chat_id, user_id):
    if await set_permissions(context, chat_id, user_id, False):
        muted_users[user_id] = datetime.datetime.now() + datetime.timedelta(seconds=MUTE_DURATION)
        return True
    return False


async def unmute_user(context, chat_id, user_id):
    if await set_permissions(context, chat_id, user_id, True):
        muted_users.pop(user_id, None)


def vote_keyboard(target_id: int):
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🔨 Блокировать", callback_data=f"vote|ban|{target_id}"),
            InlineKeyboardButton("✅ Не блокировать", callback_data=f"vote|noban|{target_id}")
        ]
    ])


def build_vote_text(target_id: int, vote_data: dict) -> str:
    ban = sum(1 for v in vote_data["votes"].values() if v == "ban")
    noban = sum(1 for v in vote_data["votes"].values() if v == "noban")
    total = len(vote_data["allowed_voters"])
    voted = len(vote_data["votes"])
    lines = [
        f"🗳 Голосование: заблокировать пользователя <code>{target_id}</code>?",
        f"За бан: <b>{ban}</b> | Против: <b>{noban}</b>",
        f"Проголосовали: {voted}/{total}"
    ]
    if voted:
        vlist = ", ".join(f"{uid}→{v}" for uid, v in vote_data["votes"].items())
        lines.append(f"Голоса: {vlist}")
    return "\n".join(lines)


# === ЗАВЕРШЕНИЕ ГОЛОСОВАНИЯ ===
async def finish_vote(context, chat_id: int, target_id: int, reason: str = "timeout"):
    vote_data = active_votes[chat_id].pop(target_id, None)
    if not vote_data:
        return

    task = vote_data.get("task")
    if task and not task.done():
        task.cancel()

    votes = vote_data["votes"]
    ban_votes = sum(1 for v in votes.values() if v == "ban")
    noban_votes = sum(1 for v in votes.values() if v == "noban")

    # Админ-инициатор не может забанить в одиночку
    only_initiator = (
        vote_data.get("started_by_admin")
        and len(votes) == 1
        and vote_data.get("initiator") in votes
        and votes[vote_data["initiator"]] == "ban"
    )

    if only_initiator:
        ban_applied = False
    else:
        ban_applied = ban_votes > noban_votes and ban_votes >= 1

    if ban_applied:
        try:
            await context.bot.ban_chat_member(chat_id, target_id)
            result = f"🔨 Пользователь <code>{target_id}</code> забанен. (за {ban_votes} / против {noban_votes})"
        except Exception as e:
            result = f"❌ Ошибка бана: {e}"
    else:
        result = f"✅ Пользователь <code>{target_id}</code> не забанен. (за {ban_votes} / против {noban_votes})"
        if target_id in muted_users:
            await unmute_user(context, chat_id, target_id)

    if vote_data.get("message_id"):
        try:
            await context.bot.edit_message_reply_markup(
                chat_id, vote_data["message_id"], reply_markup=None
            )
        except Exception:
            pass

    pending_admin_votes.pop(target_id, None)
    await context.bot.send_message(chat_id, result, parse_mode="HTML")


async def vote_timeout(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    await finish_vote(context, job.data["chat_id"], job.data["target_id"], reason="timeout")


async def mute_timeout(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    chat_id = job.data["chat_id"]
    user_id = job.data["user_id"]
    if user_id in muted_users and user_id not in active_votes.get(chat_id, {}):
        await unmute_user(context, chat_id, user_id)


# === /block ===
async def block_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    chat = update.effective_chat
    initiator = update.effective_user

    if not check_daily_limit(initiator.id):
        await msg.reply_text("⛔ Вы исчерпали лимит запросов на блок (2 в день).")
        return

    if not context.args:
        await msg.reply_text("Использование: /block @username")
        return
    target_username = context.args[0].lstrip("@")

    try:
        member = await context.bot.get_chat_member(chat.id, f"@{target_username}")
        target_id = member.user.id
        if member.user.is_bot:
            await msg.reply_text("❌ Нельзя блокировать ботов.")
            return
        if target_id == initiator.id:
            await msg.reply_text("❌ Нельзя блокировать себя.")
            return
    except Exception:
        await msg.reply_text("❌ Не удалось найти пользователя в чате.")
        return

    if target_id in active_votes[chat.id]:
        await msg.reply_text("⏳ Голосование по этому пользователю уже идёт.")
        return

    # Совет голосующих
    voters = []
    for admin_id in HOLY_TRINITY:
        try:
            m = await context.bot.get_chat_member(chat.id, admin_id)
            if m.status in ("member", "administrator", "creator"):
                voters.append(admin_id)
        except Exception:
            pass

    is_admin_initiator = initiator.id in HOLY_TRINITY
    if is_admin_initiator and initiator.id not in voters:
        voters.append(initiator.id)

    # Никого из совета нет онлайн
    if not voters:
        await mute_user(context, chat.id, target_id)
        pending_admin_votes[target_id] = {
            "chat_id": chat.id,
            "initiator": initiator.id,
            "target_id": target_id,
        }
        context.job_queue.run_once(
            mute_timeout, MUTE_DURATION,
            data={"chat_id": chat.id, "user_id": target_id},
            name=f"mute_timeout_{target_id}"
        )
        await msg.reply_text(
            f"⚠️ Никого из совета нет онлайн. Пользователь <code>{target_id}</code> "
            f"ограничен в сообщениях. Как только админ зайдёт — /pending и проголосует.",
            parse_mode="HTML"
        )
        return

    # Запуск голосования
    vote_msg = await msg.reply_text(
        build_vote_text(target_id, {"votes": {}, "allowed_voters": set(voters)}),
        reply_markup=vote_keyboard(target_id),
        parse_mode="HTML"
    )

    vote_data = {
        "initiator": initiator.id,
        "votes": {},
        "message_id": vote_msg.message_id,
        "started_by_admin": is_admin_initiator,
        "allowed_voters": set(voters),
        "task": None,
    }
    active_votes[chat.id][target_id] = vote_data

    task = context.job_queue.run_once(
        vote_timeout, VOTE_TIMEOUT,
        data={"chat_id": chat.id, "target_id": target_id},
        name=f"vote_timeout_{chat.id}_{target_id}"
    )
    vote_data["task"] = task


# === КНОПКИ ===
async def vote_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    data = query.data

    if not data.startswith("vote|"):
        return

    _, action, target_str = data.split("|")
    target_id = int(target_str)
    chat_id = query.message.chat_id

    vote_data = active_votes.get(chat_id, {}).get(target_id)
    if not vote_data:
        await query.answer("Голосование уже завершено.", show_alert=True)
        return

    if user.id not in vote_data["allowed_voters"]:
        await query.answer("Вы не входите в совет голосующих.", show_alert=True)
        return

    vote_data["votes"][user.id] = action
    await query.answer("Голос учтён.")

    try:
        await query.edit_message_text(
            build_vote_text(target_id, vote_data),
            reply_markup=vote_keyboard(target_id),
            parse_mode="HTML"
        )
    except Exception:
        pass

    if len(vote_data["votes"]) >= len(vote_data["allowed_voters"]):
        await finish_vote(context, chat_id, target_id, reason="all_voted")


# === /pending ===
async def pending_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user
    if user.id not in HOLY_TRINITY:
        return

    items = [(tid, d) for tid, d in pending_admin_votes.items() if d["chat_id"] == chat.id]
    if not items:
        await update.message.reply_text("Нет отложенных голосований.")
        return

    for target_id, data in items:
        if target_id not in active_votes[chat.id]:
            allowed = set(HOLY_TRINITY) | {data["initiator"]}
            vote_data = {
                "initiator": data["initiator"],
                "votes": {},
                "message_id": None,
                "started_by_admin": data["initiator"] in HOLY_TRINITY,
                "allowed_voters": allowed,
                "task": None,
            }
            active_votes[chat.id][target_id] = vote_data

            vote_msg = await update.message.reply_text(
                build_vote_text(target_id, vote_data),
                reply_markup=vote_keyboard(target_id),
                parse_mode="HTML"
            )
            vote_data["message_id"] = vote_msg.message_id

            task = context.job_queue.run_once(
                vote_timeout, VOTE_TIMEOUT,
                data={"chat_id": chat.id, "target_id": target_id},
                name=f"vote_timeout_{chat.id}_{target_id}"
            )
            vote_data["task"] = task

    for tid, _ in items:
        pending_admin_votes.pop(tid, None)


def main():
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("block", block_command))
    app.add_handler(CommandHandler("pending", pending_command))
    app.add_handler(CallbackQueryHandler(vote_callback, pattern=r"^vote\|"))

    app.run_polling()


if __name__ == "__main__":
    main()
