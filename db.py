"""Слой БД (Turso). Один поток + asyncio.Lock. Миграции и триггеры браков."""
import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor

import libsql_experimental as libsql
import config

log = logging.getLogger(__name__)

_conn = None
_lock = asyncio.Lock()
_executor = ThreadPoolExecutor(max_workers=1)

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

# Миграции: приводят данные к консистентному виду до создания триггеров.
MIGRATIONS = [
    # Если пользователь оказался в нескольких активных браках в одном чате —
    # оставляем только самый новый, остальные деактивируем.
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

# Триггеры: страхуют от «двое одновременно вступили в брак» и от багов в коде.
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


# ---------- синхронные воркеры ----------
def _init_sync():
    global _conn
    _conn = libsql.connect(config.TURSO_URL, auth_token=config.TURSO_API)
    for stmt in SCHEMA:
        _conn.execute(stmt)
    for stmt in MIGRATIONS:
        try:
            _conn.execute(stmt)
        except Exception as e:
            log.warning("Migration failed: %s", e)
    for stmt in TRIGGERS:
        _conn.execute(stmt)
    _conn.commit()


def _execute_sync(sql, params):
    cur = _conn.execute(sql, params)
    _conn.commit()
    return cur


def _fetchall_sync(sql, params):
    return _conn.execute(sql, params).fetchall()


def _execute_multi_sync(statements, expected):
    try:
        for i, (sql, params) in enumerate(statements):
            _conn.execute(sql, params)
            rc = _conn.execute("SELECT changes()").fetchone()[0]
            if expected is not None and i < len(expected) and expected[i] is not None:
                if rc != expected[i]:
                    raise RuntimeError(
                        f"atomic check failed at stmt#{i}: got {rc}, expected {expected[i]}"
                    )
        _conn.commit()
    except Exception:
        try:
            _conn.rollback()
        except Exception:
            pass
        raise


# ---------- асинхронный API ----------
async def init():
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(_executor, _init_sync)


async def execute(sql, params=()):
    async with _lock:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(_executor, _execute_sync, sql, params)


async def fetchall(sql, params=()):
    async with _lock:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(_executor, _fetchall_sync, sql, params)


async def fetchone(sql, params=()):
    rows = await fetchall(sql, params)
    return rows[0] if rows else None


async def execute_multi(statements, expected_rowcounts=None):
    async with _lock:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            _executor, _execute_multi_sync, statements, expected_rowcounts
        )
