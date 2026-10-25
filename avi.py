import asyncio
import datetime
import logging
import os
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from collections import defaultdict
from telethon import TelegramClient, events, Button
from telethon.sessions import StringSession
from telethon.tl.functions.channels import EditBannedRequest
from telethon.tl.types import ChatBannedRights

# === НАСТРОЙКИ ИЗ ПЕРЕМЕННЫХ ОКРУЖЕНИЯ ===
API_ID = int(os.environ.get("API_ID", 0))
API_HASH = os.environ.get("API_HASH", "")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
SESSION_STR = os.environ.get("SESSION_STR", "")

HOLY_TRINITY = {1319217425, 5376112672, 855714453}
MAX_REQUESTS_PER_DAY = 2
VOTE_TIMEOUT = 300            # 5 минут
MUTE_DURATION = 60 * 60 * 24  # 24 часа

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# === ФИКТИВНЫЙ ВЕБ-СЕРВЕР ДЛЯ RENDER ===
# Render (Web Service) требует, чтобы приложение открыло порт.
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")
    def log_message(self, format, *args):
        pass

def run_health_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
    server.serve_forever()

# === ХРАНИЛИЩА ===
daily_requests = defaultdict(lambda: {"date": datetime.date.today(), "count": 0})
active_votes = defaultdict(dict)
muted_users = {}
pending_admin_votes = {}

# === КЛИЕНТ ===
# Используем StringSession, чтобы не хранить файлы на сервере
client = TelegramClient(StringSession(SESSION_STR), API_ID, API_HASH)

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

async def set_restrictions(chat_id, user_id, can_send: bool):
    try:
        rights = ChatBannedRights(
            until_date=None if can_send else datetime.datetime.now() + datetime.timedelta(seconds=MUTE_DURATION),
            send_messages=not can_send,
            send_media=not can_send,
            send_stickers=not can_send,
            send_gifs=not can_send,
            send_games=not can_send,
            send_inline=not can_send,
            embed_links=not can_send
        )
        await client(EditBannedRequest(chat_id, user_id, rights))
        if not can_send:
            muted_users[user_id] = datetime.datetime.now() + datetime.timedelta(seconds=MUTE_DURATION)
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
        vlist = ", ".join(f"`{uid}`→{v}" for uid, v in vote_data["votes"].items())
        text += f"\n\n📝 Голоса: {vlist}"
    return text

# === ЗАВЕРШЕНИЕ ГОЛОСОВАНИЯ ===
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
        and vote_data.get("initiator") in votes
        and votes[vote_data["initiator"]] == "ban"
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
    await asyncio.sleep(VOTE_TIMEOUT)
    if chat_id in active_votes and target_id in active_votes[chat_id]:
        await finish_vote(chat_id, target_id, reason="timeout")

async def mute_timeout_task(chat_id: int, user_id: int):
    await asyncio.sleep(MUTE_DURATION)
    if user_id in muted_users and user_id not in active_votes.get(chat_id, {}):
        await set_restrictions(chat_id, user_id, True)

# === /block ===
@client.on(events.NewMessage(pattern=r'^/block'))
async def block_command(event):
    chat_id = event.chat_id
    initiator = await event.get_sender()
    
    if not check_daily_limit(initiator.id):
        await event.reply("⛔ Вы исчерпали лимит запросов на блок (2 в день).")
        return

    args = event.message.text.split()
    if len(args) < 2:
        await event.reply("Использование: `/block @username`", parse_mode='md')
        return
    
    target_username = args[1].lstrip("@")

    # === MTProto: Поиск пользователя, даже если он не писал боту ===
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

    # Собираем совет
    voters = []
    try:
        participants = await client.get_participants(chat_id)
        participant_ids = {p.id for p in participants}
        for admin_id in HOLY_TRINITY:
            if admin_id in participant_ids:
                voters.append(admin_id)
    except Exception as e:
        logging.error(f"Participants error: {e}")

    is_admin_initiator = initiator.id in HOLY_TRINITY
    if is_admin_initiator and initiator.id not in voters:
        voters.append(initiator.id)

    # Никого из совета нет онлайн
    if not voters:
        await set_restrictions(chat_id, target_id, False)
        pending_admin_votes[target_id] = {
            "chat_id": chat_id,
            "initiator": initiator.id,
            "target_id": target_id,
        }
        asyncio.create_task(mute_timeout_task(chat_id, target_id))
        await event.reply(
            f"⚠️ Никого из совета нет онлайн. Пользователь `{target_id}` ограничен в сообщениях. "
            f"Как только админ зайдёт — `/pending` и проголосует.",
            parse_mode='md'
        )
        return

    # Запуск голосования
    vote_msg = await event.reply(
        build_vote_text(target_id, {"votes": {}, "allowed_voters": set(voters)}),
        buttons=vote_keyboard(target_id),
        parse_mode='md'
    )

    active_votes[chat_id][target_id] = {
        "initiator": initiator.id,
        "votes": {},
        "message_id": vote_msg.id,
        "started_by_admin": is_admin_initiator,
        "allowed_voters": set(voters),
    }
    asyncio.create_task(vote_timeout_task(chat_id, target_id))

# === КНОПКИ ===
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

    if user.id not in vote_data["allowed_voters"]:
        await event.answer("Вы не входите в совет голосующих.", alert=True)
        return

    vote_data["votes"][user.id] = action
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

# === /pending ===
@client.on(events.NewMessage(pattern=r'^/pending'))
async def pending_command(event):
    user = await event.get_sender()
    if user.id not in HOLY_TRINITY:
        return
        
    chat_id = event.chat_id
    items = [(tid, d) for tid, d in pending_admin_votes.items() if d["chat_id"] == chat_id]
    
    if not items:
        await event.reply("Нет отложенных голосований.")
        return

    for target_id, data in items:
        if chat_id not in active_votes or target_id not in active_votes[chat_id]:
            allowed = set(HOLY_TRINITY) | {data["initiator"]}
            vote_msg = await event.reply(
                build_vote_text(target_id, {"votes": {}, "allowed_voters": allowed}),
                buttons=vote_keyboard(target_id),
                parse_mode='md'
            )
            active_votes[chat_id][target_id] = {
                "initiator": data["initiator"],
                "votes": {},
                "message_id": vote_msg.id,
                "started_by_admin": data["initiator"] in HOLY_TRINITY,
                "allowed_voters": allowed,
            }
            asyncio.create_task(vote_timeout_task(chat_id, target_id))
            
    for tid, _ in items:
        pending_admin_votes.pop(tid, None)

# === ЗАПУСК ===
async def main():
    if not API_ID or not API_HASH or not BOT_TOKEN or not SESSION_STR:
        logging.error("❌ ОШИБКА: Не заданы переменные окружения (API_ID, API_HASH, BOT_TOKEN или SESSION_STR)!")
        return

    # Запускаем сервер для Render в фоне
    threading.Thread(target=run_health_server, daemon=True).start()
    logging.info("Фоновый веб-сервер для Render успешно запущен.")

    # Запускаем MTProto клиент
    await client.start(bot_token=BOT_TOKEN)
    logging.info("Бот запущен через MTProto (Telethon)! Готов к работе.")
    
    await client.run_until_disconnected()

if __name__ == "__main__":
    asyncio.run(main())
