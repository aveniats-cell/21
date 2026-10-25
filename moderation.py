import logging
from datetime import date, datetime, timedelta
from html import escape as esc

from telegram import (
    ChatPermissions,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Update,
)
from telegram.constants import ParseMode
from telegram.error import TelegramError
from telegram.ext import (
    CallbackQueryHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

logger = logging.getLogger(__name__)


def register(app, state: dict) -> None:
    active_votes = state["active_votes"]
    pending_admin_votes = state["pending_admin_votes"]
    daily_requests = state["daily_requests"]
    holy_trinity = state["holy_trinity"]
    max_requests = state["max_requests"]
    vote_timeout = state["vote_timeout"]
    mute_duration = state["mute_duration"]
    muted_users = state["muted_users"]

    # ---------- хелперы ----------

    def is_holy_trinity(user) -> bool:
        return bool(user and user.username and user.username.lower() in holy_trinity)

    def check_daily_limit(user) -> bool:
        today = date.today()
        rec = daily_requests[user.id]
        if rec["date"] != today:
            rec["date"] = today
            rec["count"] = 0
        if is_holy_trinity(user):
            return True
        if rec["count"] < max_requests:
            rec["count"] += 1
            return True
        return False

    async def set_restrictions(bot, chat_id: int, user_id: int, can_send: bool) -> bool:
        try:
            if can_send:
                perms = ChatPermissions(
                    can_send_messages=True,
                    can_send_media_messages=True,
                    can_send_other_messages=True,
                    can_add_web_page_previews=True,
                )
                await bot.restrict_chat_member(chat_id, user_id, permissions=perms)
                muted_users.pop(user_id, None)
            else:
                perms = ChatPermissions(
                    can_send_messages=False,
                    can_send_media_messages=False,
                    can_send_other_messages=False,
                    can_add_web_page_previews=False,
                )
                until = datetime.now() + timedelta(seconds=mute_duration)
                await bot.restrict_chat_member(
                    chat_id, user_id, permissions=perms, until_date=until
                )
                muted_users[user_id] = until
            return True
        except TelegramError as e:
            logger.error("Restrict error: %s", e)
            return False

    async def ban_user(bot, chat_id: int, user_id: int) -> bool:
        try:
            await bot.ban_chat_member(chat_id, user_id)
            return True
        except TelegramError as e:
            logger.error("Ban error: %s", e)
            return False

    def vote_keyboard(target_id: int) -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup([[
            InlineKeyboardButton("🔨 Блокировать", callback_data=f"vote|ban|{target_id}"),
            InlineKeyboardButton("✅ Не блокировать", callback_data=f"vote|noban|{target_id}"),
        ]])

    def build_vote_text(target_id: int, vote_data: dict) -> str:
        ban = sum(1 for v in vote_data["votes"].values() if v == "ban")
        noban = sum(1 for v in vote_data["votes"].values() if v == "noban")
        total = len(vote_data["allowed_voters"])
        voted = len(vote_data["votes"])

        text = (
            f"🗳 <b>Голосование:</b> заблокировать пользователя "
            f"<code>{target_id}</code>?\n\n"
            f"🔨 За бан: <b>{ban}</b>\n"
            f"✅ Против: <b>{noban}</b>\n"
            f"👥 Проголосовали: {voted}/{total}"
        )
        if voted:
            vlist = ", ".join(f"@{esc(uid)}→{v}" for uid, v in vote_data["votes"].items())
            text += f"\n\n📝 Голоса: {vlist}"
        return text

    # ---------- завершение голосования ----------

    async def finish_vote(bot, chat_id: int, target_id: int, reason: str = "timeout") -> None:
        vote_data = active_votes[chat_id].pop(target_id, None)
        if not vote_data:
            return

        votes = vote_data["votes"]
        ban_votes = sum(1 for v in votes.values() if v == "ban")
        noban_votes = sum(1 for v in votes.values() if v == "noban")

        only_initiator = (
            vote_data.get("started_by_admin")
            and len(votes) == 1
            and vote_data.get("initiator_username") in votes
            and votes[vote_data["initiator_username"]] == "ban"
        )
        ban_applied = False if only_initiator else (ban_votes > noban_votes and ban_votes >= 1)

        if ban_applied:
            ok = await ban_user(bot, chat_id, target_id)
            if ok:
                result = (
                    f"🔨 Пользователь <code>{target_id}</code> <b>забанен</b>. "
                    f"(за {ban_votes} / против {noban_votes})"
                )
            else:
                result = (
                    f"❌ Ошибка бана <code>{target_id}</code>. "
                    f"Проверьте права бота."
                )
        else:
            result = (
                f"✅ Пользователь <code>{target_id}</code> <b>не забанен</b>. "
                f"(за {ban_votes} / против {noban_votes})"
            )
            if target_id in muted_users:
                await set_restrictions(bot, chat_id, target_id, True)

        try:
            await bot.edit_message_text(
                chat_id=chat_id,
                message_id=vote_data["message_id"],
                text=result,
                parse_mode=ParseMode.HTML,
            )
        except TelegramError:
            pass

        pending_admin_votes.pop(target_id, None)
        await bot.send_message(chat_id, result, parse_mode=ParseMode.HTML)

    async def vote_timeout_job(context: ContextTypes.DEFAULT_TYPE) -> None:
        chat_id, target_id = context.job.data
        if chat_id in active_votes and target_id in active_votes[chat_id]:
            await finish_vote(context.bot, chat_id, target_id, reason="timeout")

    # ---------- хэндлеры ----------

    async def block_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        msg = update.effective_message
        chat_id = update.effective_chat.id
        initiator = update.effective_user

        parts = (msg.text or "").split(maxsplit=1)
        if len(parts) < 2 or not parts[1].strip():
            await msg.reply_text(
                "❌ Использование: <code>/суд @username</code>",
                parse_mode=ParseMode.HTML,
            )
            return

        target_username = parts[1].strip().lstrip("@").lower()
        if not target_username:
            await msg.reply_text("❌ Укажите юзернейм.")
            return

        if not check_daily_limit(initiator):
            await msg.reply_text("⛔ Вы исчерпали лимит запросов на суд (2 в день).")
            return

        try:
            target = await context.bot.get_chat(f"@{target_username}")
            if getattr(target, "is_bot", False):
                await msg.reply_text("❌ Нельзя блокировать ботов.")
                return
            target_id = target.id
            if target_id == initiator.id:
                await msg.reply_text("❌ Нельзя блокировать себя.")
                return
        except Exception:
            await msg.reply_text(
                f"❌ Не удалось найти <code>@{esc(target_username)}</code>.",
                parse_mode=ParseMode.HTML,
            )
            return

        if chat_id in active_votes and target_id in active_votes[chat_id]:
            await msg.reply_text("⏳ Голосование по этому пользователю уже идёт.")
            return

        allowed_voters = set(holy_trinity)
        is_admin_initiator = is_holy_trinity(initiator)
        initiator_username = initiator.username.lower() if initiator.username else None

        vote_msg = await msg.reply_text(
            build_vote_text(target_id, {"votes": {}, "allowed_voters": allowed_voters}),
            reply_markup=vote_keyboard(target_id),
            parse_mode=ParseMode.HTML,
        )

        active_votes[chat_id][target_id] = {
            "initiator": initiator.id,
            "initiator_username": initiator_username,
            "votes": {},
            "message_id": vote_msg.message_id,
            "started_by_admin": is_admin_initiator,
            "allowed_voters": allowed_voters,
        }
        context.job_queue.run_once(
            vote_timeout_job,
            when=vote_timeout,
            data=(chat_id, target_id),
            name=f"vote_{chat_id}_{target_id}",
        )

    async def vote_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        user = query.from_user
        chat_id = update.effective_chat.id

        try:
            _, action, target_str = query.data.split("|")
            target_id = int(target_str)
        except ValueError:
            await query.answer("Некорректные данные голосования.", show_alert=True)
            return

        vote_data = active_votes.get(chat_id, {}).get(target_id)
        if not vote_data:
            await query.answer("Голосование уже завершено.", show_alert=True)
            return

        if not user.username:
            await query.answer(
                "У вас нет юзернейма, голос не может быть учтён.",
                show_alert=True,
            )
            return

        username = user.username.lower()
        if username not in vote_data["allowed_voters"]:
            await query.answer("Вы не входите в совет голосующих.", show_alert=True)
            return

        vote_data["votes"][username] = action
        await query.answer("Голос учтён.")

        try:
            await query.edit_message_text(
                build_vote_text(target_id, vote_data),
                reply_markup=vote_keyboard(target_id),
                parse_mode=ParseMode.HTML,
            )
        except TelegramError:
            pass

        if len(vote_data["votes"]) >= len(vote_data["allowed_voters"]):
            await finish_vote(context.bot, chat_id, target_id, reason="all_voted")

    async def pending_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        user = update.effective_user
        if not is_holy_trinity(user):
            return

        msg = update.effective_message
        chat_id = update.effective_chat.id
        items = [(tid, d) for tid, d in pending_admin_votes.items() if d["chat_id"] == chat_id]

        if not items:
            await msg.reply_text("Нет отложенных голосований.")
            return

        for target_id, data in items:
            if chat_id in active_votes and target_id in active_votes[chat_id]:
                continue

            allowed = set(holy_trinity)
            initiator_username = None
            try:
                initiator_entity = await context.bot.get_chat(data["initiator"])
                if getattr(initiator_entity, "username", None):
                    initiator_username = initiator_entity.username.lower()
            except Exception:
                pass

            vote_msg = await msg.reply_text(
                build_vote_text(target_id, {"votes": {}, "allowed_voters": allowed}),
                reply_markup=vote_keyboard(target_id),
                parse_mode=ParseMode.HTML,
            )
            active_votes[chat_id][target_id] = {
                "initiator": data["initiator"],
                "initiator_username": initiator_username,
                "votes": {},
                "message_id": vote_msg.message_id,
                "started_by_admin": True,
                "allowed_voters": allowed,
            }
            context.job_queue.run_once(
                vote_timeout_job,
                when=vote_timeout,
                data=(chat_id, target_id),
                name=f"vote_{chat_id}_{target_id}",
            )

        for tid, _ in items:
            pending_admin_votes.pop(tid, None)

    app.add_handler(
        MessageHandler(filters.Regex(r"^/?суд\s+@?\w+$", flags=re.IGNORECASE if (re := __import__("re")) else 0), block_command)
    )
    app.add_handler(CallbackQueryHandler(vote_callback, pattern=r"^vote\|"))
    app.add_handler(
        MessageHandler(filters.Regex(r"^/?ожидание$", flags=(__import__("re").IGNORECASE)), pending_command)
    )

    logger.info("Moderation module: 'суд', 'ожидание', vote-callback зарегистрированы.")
