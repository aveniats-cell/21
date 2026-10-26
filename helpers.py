"""Общие утилиты: парсеры, фильтры, резолв юзеров, проверки ролей, rate-limit."""
import functools
import re
import time
from datetime import datetime, timezone

from telegram import Update
from telegram.ext import ContextTypes, filters

import config
import db

ADMIN_ID: int | None = config.ADMIN_ID

MENTION_RE = re.compile(r"@([A-Za-z0-9_]{4,32})")
_DUR = re.compile(r"(\d+)\s*([smhdSMHDсСмМчЧдД])")
_UNIT = {
    "s": 1, "S": 1, "с": 1, "С": 1,
    "m": 60, "M": 60, "м": 60, "М": 60,
    "h": 3600, "H": 3600, "ч": 3600, "Ч": 3600,
    "d": 86400, "D": 86400, "д": 86400, "Д": 86400,
}

RL_MAX_AGE = 3600  # запись rate-limit живёт час — потом чистится


def RX(pattern: str):
    return filters.Regex(re.compile(pattern, re.IGNORECASE))


def parse_duration(text: str) -> int:
    if not text:
        return 0
    total = 0
    for num, unit in _DUR.findall(text):
        total += int(num) * _UNIT.get(unit, 0)
    return total


def fmt_duration(sec: int) -> str:
    if sec <= 0:
        return "навсегда"
    parts = []
    for label, div in (("д", 86400), ("ч", 3600), ("м", 60), ("с", 1)):
        if sec >= div:
            parts.append(f"{sec // div}{label}")
            sec %= div
    return " ".join(parts)


def is_admin_user(user) -> bool:
    if not user:
        return False
    if ADMIN_ID is not None and user.id == ADMIN_ID:
        return True
    if user.username and user.username.lower() == config.ADMIN_USERNAME:
        return True
    return False


def today_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


# ---------- rate-limit ----------
def rate_limit(key: str, cooldown: int, message: str = "⏳ Подожди {left}с."):
    """Не чаще раза в `cooldown` секунд на пользователя в чате."""
    def wrapper(func):
        @functools.wraps(func)
        async def inner(update: Update, context: ContextTypes.DEFAULT_TYPE):
            msg = update.effective_message
            if not msg or not msg.from_user:
                return await func(update, context)
            uid = msg.from_user.id
            cid = msg.chat_id or 0
            now = time.time()
            store = context.application.bot_data.setdefault("ratelimit", {})
            k = (key, cid, uid)
            last = store.get(k, 0)
            if now - last < cooldown:
                left = int(cooldown - (now - last)) + 1
                try:
                    await msg.reply_text(message.format(left=left))
                except Exception:
                    pass
                return
            store[k] = now
            return await func(update, context)
        return inner
    return wrapper


def cleanup_rate_limits(application, max_age: int = RL_MAX_AGE):
    """Удаляет старые записи rate-limit. Синхронная — вызывать без await."""
    store = application.bot_data.get("ratelimit", {})
    now = time.time()
    for k in list(store.keys()):
        if now - store[k] > max_age:
            store.pop(k, None)


# ---------- резолв юзеров ----------
async def resolve_target(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str | None = None):
    msg = update.effective_message
    if msg.reply_to_message and msg.reply_to_message.from_user:
        u = msg.reply_to_message.from_user
        return u.id, u.username, u.first_name

    if text:
        m = MENTION_RE.search(text)
        if m:
            uname = m.group(1)
            try:
                c = await context.bot.get_chat("@" + uname)
                return c.id, c.username, c.first_name
            except Exception:
                pass
            tc = context.application.bot_data.get("telethon")
            if tc:
                try:
                    ent = await tc.get_entity("@" + uname)
                    return (
                        ent.id,
                        getattr(ent, "username", None),
                        getattr(ent, "first_name", None) or getattr(ent, "title", ""),
                    )
                except Exception:
                    pass
    return None, None, None


async def ensure_user(user):
    await db.execute(
        "INSERT OR IGNORE INTO users (user_id, username, first_name) VALUES (?,?,?)",
        (user.id, user.username, user.first_name),
    )
    await db.execute(
        "UPDATE users SET username=?, first_name=? WHERE user_id=?",
        (user.username, user.first_name, user.id),
    )


async def get_roles(chat_id: int, user_id: int) -> set:
    rows = await db.fetchall(
        "SELECT role FROM roles WHERE chat_id=? AND user_id=?", (chat_id, user_id)
    )
    return {r[0] for r in rows}


async def is_sheriff(chat_id: int, user) -> bool:
    if is_admin_user(user):
        return True
    if not user:
        return False
    return "sheriff" in await get_roles(chat_id, user.id)


async def can_moderate(chat_id: int, user) -> bool:
    if is_admin_user(user):
        return True
    if not user:
        return False
    return "commissar" in await get_roles(chat_id, user.id)


async def is_council_member(chat_id: int, user) -> bool:
    if is_admin_user(user):
        return True
    if not user:
        return False
    row = await db.fetchone(
        "SELECT 1 FROM council WHERE chat_id=? AND user_id=?", (chat_id, user.id)
    )
    return row is not None


async def chat_admin_ids(context: ContextTypes.DEFAULT_TYPE, chat_id: int) -> set:
    try:
        admins = await context.bot.get_chat_administrators(chat_id)
        return {a.user.id for a in admins if not a.user.is_bot}
    except Exception:
        return set()
