import asyncio
import datetime
import logging

from telethon import events, Button
from telethon.tl.functions.channels import EditBannedRequest
from telethon.tl.types import ChatBannedRights


def register(
    client,
    active_votes,
    muted_users,
    pending_admin_votes,
    daily_requests,
    holy_trinity,
    max_requests,
    vote_timeout,
    mute_duration,
):
    def is_holy_trinity(user) -> bool:
        if not user or not user.username:
            return False
        return user.username.lower() in holy_trinity

    def check_daily_limit(user) -> bool:
        today = datetime.date.today()
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

    async def set_restrictions(chat_id, user_id, can_send: bool):
        try:
            rights = ChatBannedRights(
                until_date=None if can_send else datetime.datetime.now() + datetime.timedelta(seconds=mute_duration),
                send_messages=not can_send,
                send_media=not can_send,
                send_stickers=not can_send,
                send_gifs=not can_send,
                send_games=not can_send,
                send_inline=not can_send,
                embed_links=not can_send,
            )
            await client(EditBannedRequest(chat_id, user_id, rights))
            if not can_send:
                muted_users[user_id] = datetime.datetime.now() + datetime.timedelta(seconds=mute_duration)
            else:
                muted_users.pop(user_id, None)
            return True
        except Exception as e:
            logging.error(f"Restrict error: {e}")
            return False

    async def ban_user(chat_id, user_id):
        try:
            rights = ChatBannedRights(until_date=None, view_messages=True)
            await client(EditBannedRequest(chat_id, user_id, rights))
            return True
        except Exception as e:
            logging.error(f"Ban error: {e}")
            return False

    def vote_keyboard(target_id: int):
        return [
            [Button.inline("🔨 Блокировать", data=f"vote|ban|{target_id}".encode()),
             Button.inline("✅ Не блокировать", data=f"vote|noban|{target_id}".encode())]
        ]

    def build_vote_text(target_id: int, vote_data: dict) -> str:
        ban = sum(1 for v in vote_data["votes"].values() if v == "ban")
        noban = sum(1 for v in vote_data["votes"].values() if v == "noban")
        total = len(vote_data["allowed_voters"])
        voted = len(vote_data["votes"])

        text = (
            f"🗳 **Голосование:** заблокировать пользователя `{target_id}`?\n\n"
            f"🔨 За бан: **{ban}**\n"
            f"✅ Против: **{noban}**\n"
            f"👥 Проголосовали: {voted}/{total}"
        )
        if voted:
            vlist = ", ".join(f"@{uid}→{v}" for uid, v in vote_data["votes"].items())
            text += f"\n\n📝 Голоса: {vlist}"
        return text

    async def finish_vote(chat_id: int, target_id: int, reason: str = "timeout"):
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
            success = await ban_user(chat_id, target_id)
            if success:
                result = f"🔨 Пользователь `{target_id}` **забанен**. (за {ban_votes} / против {noban_votes})"
            else:
                result = f"❌ Ошибка бана пользователя `{target_id}`. Проверьте права бота."
        else:
            result = f"✅ Пользователь `{target_id}` **не забанен**. (за {ban_votes} / против {noban_votes})"
            if target_id in muted_users:
                await set_restrictions(chat_id, target_id, True)

        try:
            await client.edit_message(chat_id, vote_data["message_id"], result, buttons=None, parse_mode='md')
        except Exception:
            pass

        pending_admin_votes.pop(target_id, None)
        await client.send_message(chat_id, result, parse_mode='md')

    async def vote_timeout_task(chat_id: int, target_id: int):
        await asyncio.sleep(vote_timeout)
        if chat_id in active_votes and target_id in active_votes[chat_id]:
            await finish_vote(chat_id, target_id, reason="timeout")

    async def mute_timeout_task(chat_id: int, user_id: int):
        await asyncio.sleep(mute_duration)
        if user_id in muted_users and user_id not in active_votes.get(chat_id, {}):
            await set_restrictions(chat_id, user_id, True)

    @client.on(events.NewMessage(pattern=r'(?i)^/?суд\s+@?(\w+)$'))
    async def block_command(event):
        chat_id = event.chat_id
        initiator = await event.get_sender()

        if not check_daily_limit(initiator):
            await event.reply("⛔ Вы исчерпали лимит запросов на суд (2 в день).")
            return

        target_username = event.pattern_match.group(1)

        try:
            target = await client.get_entity(f"@{target_username}")
            target_id = target.id
            if target.bot:
                await event.reply("❌ Нельзя блокировать ботов.")
                return
            if target_id == initiator.id:
                await event.reply("❌ Нельзя блокировать себя.")
                return
        except Exception as e:
            await event.reply(f"❌ Не удалось найти `@{target_username}`. Ошибка: {e}", parse_mode='md')
            return

        if chat_id in active_votes and target_id in active_votes[chat_id]:
            await event.reply("⏳ Голосование по этому пользователю уже идёт.")
            return

        allowed_voters = set(holy_trinity)
        is_admin_initiator = is_holy_trinity(initiator)
        initiator_username = initiator.username.lower() if initiator.username else None

        vote_msg = await event.reply(
            build_vote_text(target_id, {"votes": {}, "allowed_voters": allowed_voters}),
            buttons=vote_keyboard(target_id),
            parse_mode='md'
        )

        active_votes[chat_id][target_id] = {
            "initiator": initiator.id,
            "initiator_username": initiator_username,
            "votes": {},
            "message_id": vote_msg.id,
            "started_by_admin": is_admin_initiator,
            "allowed_voters": allowed_voters,
        }
        asyncio.create_task(vote_timeout_task(chat_id, target_id))

    @client.on(events.CallbackQuery(pattern=r'^vote\|'))
    async def vote_callback(event):
        user = await event.get_sender()
        data = event.data.decode()
        _, action, target_str = data.split("|")
        target_id = int(target_str)
        chat_id = event.chat_id

        vote_data = active_votes.get(chat_id, {}).get(target_id)
        if not vote_data:
            await event.answer("Голосование уже завершено.", alert=True)
            return

        if not user.username:
            await event.answer("У вас нет юзернейма, голос не может быть учтён.", alert=True)
            return

        username = user.username.lower()
        if username not in vote_data["allowed_voters"]:
            await event.answer("Вы не входите в совет голосующих.", alert=True)
            return

        vote_data["votes"][username] = action
        await event.answer("Голос учтён.")

        try:
            await event.edit(
                build_vote_text(target_id, vote_data),
                buttons=vote_keyboard(target_id),
                parse_mode='md'
            )
        except Exception:
            pass

        if len(vote_data["votes"]) >= len(vote_data["allowed_voters"]):
            await finish_vote(chat_id, target_id, reason="all_voted")

    @client.on(events.NewMessage(pattern=r'(?i)^/?ожидание$'))
    async def pending_command(event):
        user = await event.get_sender()
        if not is_holy_trinity(user):
            return

        chat_id = event.chat_id
        items = [(tid, d) for tid, d in pending_admin_votes.items() if d["chat_id"] == chat_id]

        if not items:
            await event.reply("Нет отложенных голосований.")
            return

        for target_id, data in items:
            if chat_id not in active_votes or target_id not in active_votes[chat_id]:
                allowed = set(holy_trinity)
                initiator_username = None
                try:
                    initiator_entity = await client.get_entity(data["initiator"])
                    if initiator_entity.username:
                        initiator_username = initiator_entity.username.lower()
                except Exception:
                    pass

                vote_msg = await event.reply(
                    build_vote_text(target_id, {"votes": {}, "allowed_voters": allowed}),
                    buttons=vote_keyboard(target_id),
                    parse_mode='md'
                )
                active_votes[chat_id][target_id] = {
                    "initiator": data["initiator"],
                    "initiator_username": initiator_username,
                    "votes": {},
                    "message_id": vote_msg.id,
                    "started_by_admin": True,
                    "allowed_voters": allowed,
                }
                asyncio.create_task(vote_timeout_task(chat_id, target_id))

        for tid, _ in items:
            pending_admin_votes.pop(tid, None)

    logging.info("Moderation module: зарегистрированы 'суд', 'ожидание', vote-callback.")
