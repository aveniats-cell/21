"""Слой БД (Turso) через libsql-client (HTTP). Триггеры браков + миграции."""
import asyncio
import logging

import libsql_client
import config

log = logging.getLogger(__name__)

_client = None
_lock = asyncio.Lock()


SCHEMA = [
    f"""CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        username TEXT,
        first_name TEXT,
        coins INTEGER DEFAULT {config.COINS_START},
        credit INTEGER DEFAULT 0,
        mutes_issued INTEGER DEFAULT 0,
        reports INTEGER DEFAULT 0,
        courts INTEGER DEFAULT 0,
        ttt_wins INTEGER DEFAULT 0,
        ttt_losses INTEGER DEFAULT 0,
        ttt_played INTEGER DEFAULT 0,
        divorced_count INTEGER DEFAULT 0
    )""",
    """CREATE TABLE IF NOT EXISTS chat_users (
        chat_id INTEGER,
        user_id INTEGER,
        msg_day INTEGER DEFAULT 0,
        msg_total INTEGER DEFAULT 0,
        day_date TEXT,
        PRIMARY KEY (chat_id, user_id)
    )""",
    """CREATE TABLE IF NOT EXISTS roles (
        chat_id INTEGER,
        user_id INTEGER,
        role TEXT,
        PRIMARY KEY (chat_id, user_id, role)
    )""",
    """CREATE TABLE IF NOT EXISTS council (
        chat_id INTEGER,
        user_id INTEGER,
        PRIMARY KEY (chat_id, user_id)
    )""",
    """CREATE TABLE IF NOT EXISTS marriages (
        chat_id INTEGER,
        user1_id INTEGER,
        user2_id INTEGER,
        forced INTEGER DEFAULT 0,
        started_at TEXT,
        active INTEGER DEFAULT 1,
        PRIMARY KEY (chat_id, user1_id, user2_id)
    )""",
    """CREATE TABLE IF NOT EXISTS pr_channels (
        chat_id INTEGER,
        channel TEXT,
        PRIMARY KEY (chat_id, channel)
    )""",
]

MIGRATIONS = [
    """UPDATE marriages SET active = 0
       WHERE active = 1
         AND EXISTS (
           SELECT 1 FROM marriages m2
           WHERE m2.chat_id = marriages.chat_id
             AND m2.active = 1
             AND m2.started_at > marriages.started_at
             AND (m2.user1_id IN (marriages.user1_id, marriages.user2_id)
                  OR m2.user2_id IN (marriages.user1_id, marriages.user2_id))
         )""",
]

TRIGGERS = [
    """CREATE TRIGGER IF NOT EXISTS trg_marriage_ins
       BEFORE INSERT ON marriages
       WHEN NEW.active = 1
       BEGIN
           SELECT RAISE(ABORT, 'user already in active marriage')
           WHERE EXISTS (
               SELECT 1 FROM marriages
               WHERE chat_id = NEW.chat_id AND active = 1
                 AND NOT (user1_id = NEW.user1_id AND user2_id = NEW.user2_id)
                 AND (user1_id IN (NEW.user1_id, NEW.user2_id)
                      OR user2_id IN (NEW.user1_id, NEW.user2_id))
           );
       END""",
    """CREATE TRIGGER IF NOT EXISTS trg_marriage_upd
       BEFORE UPDATE OF active ON marriages
       WHEN NEW.active = 1 AND OLD.active = 0
       BEGIN
           SELECT RAISE(ABORT, 'user already in active marriage')
           WHERE EXISTS (
               SELECT 1 FROM marriages
               WHERE chat_id = NEW.chat_id AND active = 1
                 AND NOT (user1_id = NEW.user1_id AND user2_id = NEW.user2_id)
                 AND (user1_id IN (NEW.user1_id, NEW.user2_id)
                      OR user2_id IN (NEW.user1_id, NEW.user2_id))
           );
       END""",
]


async def init():
    global _client
    _client = libsql_client.create_client(
        url=config.TURSO_URL,
        auth_token=config.TURSO_API,
    )
    for stmt in SCHEMA:
        await _client.execute(stmt)
    for stmt in MIGRATIONS:
        try:
            await _client.execute(stmt)
        except Exception as e:
            log.warning("Migration failed: %s", e)
    for stmt in TRIGGERS:
        await _client.execute(stmt)


def _changes_of(rs) -> int:
    try:
        rows = getattr(rs, "rows", None)
        if rows:
            v = rows[0][0]
            return int(v) if v is not None else 0
    except Exception:
        pass
    return 0


async def execute(sql, params=()):
    async with _lock:
        return await _client.execute(sql, list(params))


async def fetchall(sql, params=()):
    async with _lock:
        rs = await _client.execute(sql, list(params))
        return [tuple(r) for r in (rs.rows or [])]


async def fetchone(sql, params=()):
    rows = await fetchall(sql, params)
    return rows[0] if rows else None


async def execute_multi(statements, expected_rowcounts=None):
    """Атомарная пачка через batch(). После каждого statement — SELECT changes()."""
    async with _lock:
        items = []
        for sql, params in statements:
            items.append((sql, list(params)))
            items.append(("SELECT changes() AS c", []))
        results = await _client.batch(items)
        if expected_rowcounts is not None:
            for i, exp in enumerate(expected_rowcounts):
                if exp is None:
                    continue
                chk = _changes_of(results[i * 2 + 1])
                if chk != exp:
                    raise RuntimeError(
                        f"atomic check failed at stmt#{i}: got {chk}, expected {exp}"
                    )
        return results
