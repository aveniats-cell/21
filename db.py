import datetime
import logging
import os
import time

import libsql_experimental as libsql

TURSO_URL = os.environ.get("TURSO_DATABASE_URL", "")
TURSO_TOKEN = os.environ.get("TURSO_AUTH_TOKEN", "")

_conn = None
_last_healthcheck = 0.0
HEALTHCHECK_INTERVAL = 60  # сек: не чаще, чем раз в минуту

logger = logging.getLogger(__name__)


# ==================== ПОДКЛЮЧЕНИЕ ====================

def _is_connection_error(exc: Exception) -> bool:
    """Проверяет, что ошибка — потеря stream / соединения с Turso."""
    msg = str(exc).lower()
    return (
        "stream not found" in msg
        or "status=404" in msg
        or ("hrana" in msg and "404" in msg)
        or "connection" in msg and "closed" in msg
    )


def _reconnect():
    """Принудительно пересоздаёт соединение с Turso."""
    global _conn, _last_healthcheck
    try:
        if _conn is not None:
            _conn.close()
    except Exception:
        pass
    _conn = None
    _last_healthcheck = 0.0
    logger.warning("DB: переподключение к Turso...")


def get_db():
    """Возвращает живое соединение. Проверяет stream и переподключается при необходимости."""
    global _conn, _last_healthcheck

    if _conn is None:
        if not TURSO_URL or not TURSO_TOKEN:
            raise ValueError("TURSO_DATABASE_URL или TURSO_AUTH_TOKEN не заданы")
        _conn = libsql.connect(database=TURSO_URL, auth_token=TURSO_TOKEN)
        _init_tables()
        _last_healthcheck = time.time()
        return _conn

    # Периодическая проверка живости stream (не чаще раза в минуту)
    now = time.time()
    if now - _last_healthcheck >= HEALTHCHECK_INTERVAL:
        try:
            _conn.execute("SELECT 1").fetchone()
        except Exception as e:
            if _is_connection_error(e):
                logger.warning("DB: stream мёртв, переподключаюсь... (%s)", e)
                _reconnect()
                return get_db()
            raise
        _last_healthcheck = now

    return _conn


def _init_tables():
    conn = _conn
    conn.execute("""
        CREATE TABLE IF NOT EXISTS profiles (
            user_id       INTEGER PRIMARY KEY,
            username      TEXT,
            first_name    TEXT,
            first_seen    TEXT,
            message_count INTEGER DEFAULT 0,
            is_criminal   INTEGER DEFAULT 0,
            awards        TEXT    DEFAULT ''
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS mutes (
            user_id    INTEGER PRIMARY KEY,
            chat_id    INTEGER NOT NULL,
            until_date TEXT    NOT NULL
        )
    """)
    conn.commit()
    logging.info("DB: таблицы profiles и mutes готовы")
    _init_halloween_tables()


# ==================== ПРОФИЛИ ====================

def ensure_profile(user_id, username, first_name):
    for attempt in range(2):
        try:
            conn = get_db()
            conn.execute("""
                INSERT INTO profiles (user_id, username, first_name, first_seen)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    username   = COALESCE(?, username),
                    first_name = COALESCE(?, first_name)
            """, (
                user_id, username, first_name,
                datetime.date.today().isoformat(),
                username, first_name,
            ))
            conn.commit()
            return
        except Exception as e:
            if _is_connection_error(e) and attempt == 0:
                _reconnect()
                continue
            raise


def inc_message_count(user_id):
    for attempt in range(2):
        try:
            conn = get_db()
            conn.execute(
                "UPDATE profiles SET message_count = message_count + 1 WHERE user_id = ?",
                (user_id,),
            )
            conn.commit()
            return
        except Exception as e:
            if _is_connection_error(e) and attempt == 0:
                _reconnect()
                continue
            raise


def mark_criminal(user_id):
    for attempt in range(2):
        try:
            conn = get_db()
            conn.execute("UPDATE profiles SET is_criminal = 1 WHERE user_id = ?", (user_id,))
            conn.commit()
            return
        except Exception as e:
            if _is_connection_error(e) and attempt == 0:
                _reconnect()
                continue
            raise


def get_profile(user_id):
    for attempt in range(2):
        try:
            conn = get_db()
            row = conn.execute(
                "SELECT user_id, username, first_name, first_seen, message_count, "
                "is_criminal, awards FROM profiles WHERE user_id = ?",
                (user_id,),
            ).fetchone()
            if not row:
                return None
            return {
                "user_id": row[0], "username": row[1], "first_name": row[2],
                "first_seen": row[3], "message_count": row[4],
                "is_criminal": row[5], "awards": row[6],
            }
        except Exception as e:
            if _is_connection_error(e) and attempt == 0:
                _reconnect()
                continue
            raise


def set_awards(user_id, awards):
    for attempt in range(2):
        try:
            conn = get_db()
            conn.execute("UPDATE profiles SET awards = ? WHERE user_id = ?", (awards, user_id))
            conn.commit()
            return
        except Exception as e:
            if _is_connection_error(e) and attempt == 0:
                _reconnect()
                continue
            raise


# ==================== МУТЫ ====================

def save_mute(user_id, chat_id, until_date):
    for attempt in range(2):
        try:
            conn = get_db()
            conn.execute("""
                INSERT INTO mutes (user_id, chat_id, until_date)
                VALUES (?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET chat_id = ?, until_date = ?
            """, (user_id, chat_id, until_date.isoformat(), chat_id, until_date.isoformat()))
            conn.commit()
            return
        except Exception as e:
            if _is_connection_error(e) and attempt == 0:
                _reconnect()
                continue
            raise


def remove_mute(user_id):
    for attempt in range(2):
        try:
            conn = get_db()
            conn.execute("DELETE FROM mutes WHERE user_id = ?", (user_id,))
            conn.commit()
            return
        except Exception as e:
            if _is_connection_error(e) and attempt == 0:
                _reconnect()
                continue
            raise


def get_active_mutes():
    for attempt in range(2):
        try:
            conn = get_db()
            now = datetime.datetime.now().isoformat()
            rows = conn.execute(
                "SELECT user_id, chat_id, until_date FROM mutes WHERE until_date > ?",
                (now,),
            ).fetchall()
            return [
                {"user_id": r[0], "chat_id": r[1],
                 "until_date": datetime.datetime.fromisoformat(r[2])}
                for r in rows
            ]
        except Exception as e:
            if _is_connection_error(e) and attempt == 0:
                _reconnect()
                continue
            raise


# ==================== HALLOWEEN 2026 ====================

def _init_halloween_tables():
    conn = _conn
    conn.execute("""CREATE TABLE IF NOT EXISTS pumpkins (
        user_id INTEGER PRIMARY KEY, amount REAL DEFAULT 0)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS inventory (
        user_id INTEGER, item_id TEXT, amount INTEGER DEFAULT 0,
        PRIMARY KEY (user_id, item_id))""")
    conn.execute("""CREATE TABLE IF NOT EXISTS awards (
        user_id INTEGER, award_id TEXT, earned_at TEXT,
        PRIMARY KEY (user_id, award_id))""")
    conn.execute("""CREATE TABLE IF NOT EXISTS mining_stats (
        user_id INTEGER PRIMARY KEY, total_mines INTEGER DEFAULT 0,
        fails_streak INTEGER DEFAULT 0)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS daily_bonus (
        user_id INTEGER PRIMARY KEY, last_day TEXT)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS luck_buff (
        user_id INTEGER PRIMARY KEY, bonus REAL DEFAULT 0,
        until_mine INTEGER DEFAULT 0)""")
    conn.commit()
    logging.info("DB: таблицы Halloween готовы")


def hw_add_pumpkins(user_id, amount):
    for attempt in range(2):
        try:
            conn = get_db()
            conn.execute("""INSERT INTO pumpkins (user_id, amount) VALUES (?, ?)
                ON CONFLICT(user_id) DO UPDATE SET amount = amount + ?""",
                (user_id, amount, amount))
            conn.commit()
            return
        except Exception as e:
            if _is_connection_error(e) and attempt == 0:
                _reconnect()
                continue
            raise


def hw_get_pumpkins(user_id):
    for attempt in range(2):
        try:
            conn = get_db()
            row = conn.execute(
                "SELECT amount FROM pumpkins WHERE user_id = ?", (user_id,)
            ).fetchone()
            return row[0] if row else 0.0
        except Exception as e:
            if _is_connection_error(e) and attempt == 0:
                _reconnect()
                continue
            raise


def hw_spend_pumpkins(user_id, amount):
    for attempt in range(2):
        try:
            conn = get_db()
            row = conn.execute(
                "SELECT amount FROM pumpkins WHERE user_id = ?", (user_id,)
            ).fetchone()
            if not row or row[0] < amount:
                return False
            conn.execute(
                "UPDATE pumpkins SET amount = amount - ? WHERE user_id = ?",
                (amount, user_id),
            )
            conn.commit()
            return True
        except Exception as e:
            if _is_connection_error(e) and attempt == 0:
                _reconnect()
                continue
            raise


def hw_add_inventory(user_id, item_id, amount=1):
    for attempt in range(2):
        try:
            conn = get_db()
            conn.execute("""INSERT INTO inventory (user_id, item_id, amount) VALUES (?, ?, ?)
                ON CONFLICT(user_id, item_id) DO UPDATE SET amount = amount + ?""",
                (user_id, item_id, amount, amount))
            conn.commit()
            return
        except Exception as e:
            if _is_connection_error(e) and attempt == 0:
                _reconnect()
                continue
            raise


def hw_get_inventory(user_id):
    for attempt in range(2):
        try:
            conn = get_db()
            rows = conn.execute(
                "SELECT item_id, amount FROM inventory WHERE user_id = ? AND amount > 0",
                (user_id,),
            ).fetchall()
            return {r[0]: r[1] for r in rows}
        except Exception as e:
            if _is_connection_error(e) and attempt == 0:
                _reconnect()
                continue
            raise


def hw_remove_inventory(user_id, item_id, amount=1):
    for attempt in range(2):
        try:
            conn = get_db()
            row = conn.execute(
                "SELECT amount FROM inventory WHERE user_id = ? AND item_id = ?",
                (user_id, item_id),
            ).fetchone()
            if not row or row[0] < amount:
                return False
            conn.execute(
                "UPDATE inventory SET amount = amount - ? WHERE user_id = ? AND item_id = ?",
                (amount, user_id, item_id),
            )
            conn.commit()
            return True
        except Exception as e:
            if _is_connection_error(e) and attempt == 0:
                _reconnect()
                continue
            raise


def hw_has_award(user_id, award_id):
    for attempt in range(2):
        try:
            conn = get_db()
            return conn.execute(
                "SELECT 1 FROM awards WHERE user_id = ? AND award_id = ?",
                (user_id, award_id),
            ).fetchone() is not None
        except Exception as e:
            if _is_connection_error(e) and attempt == 0:
                _reconnect()
                continue
            raise


def hw_give_award(user_id, award_id):
    for attempt in range(2):
        try:
            conn = get_db()
            if conn.execute(
                "SELECT 1 FROM awards WHERE user_id = ? AND award_id = ?",
                (user_id, award_id),
            ).fetchone() is not None:
                return False
            conn.execute(
                "INSERT INTO awards (user_id, award_id, earned_at) VALUES (?, ?, ?)",
                (user_id, award_id, datetime.datetime.now().isoformat()),
            )
            conn.commit()
            return True
        except Exception as e:
            if _is_connection_error(e) and attempt == 0:
                _reconnect()
                continue
            raise


def hw_get_mining_stats(user_id):
    for attempt in range(2):
        try:
            conn = get_db()
            row = conn.execute(
                "SELECT total_mines, fails_streak FROM mining_stats WHERE user_id = ?",
                (user_id,),
            ).fetchone()
            if not row:
                conn.execute("INSERT INTO mining_stats (user_id) VALUES (?)", (user_id,))
                conn.commit()
                return {"total_mines": 0, "fails_streak": 0}
            return {"total_mines": row[0], "fails_streak": row[1]}
        except Exception as e:
            if _is_connection_error(e) and attempt == 0:
                _reconnect()
                continue
            raise


def hw_update_mining_stats(user_id, success):
    for attempt in range(2):
        try:
            conn = get_db()
            if success:
                conn.execute("""UPDATE mining_stats SET total_mines = total_mines + 1,
                    fails_streak = 0 WHERE user_id = ?""", (user_id,))
            else:
                conn.execute("""UPDATE mining_stats SET total_mines = total_mines + 1,
                    fails_streak = fails_streak + 1 WHERE user_id = ?""", (user_id,))
            conn.commit()
            return
        except Exception as e:
            if _is_connection_error(e) and attempt == 0:
                _reconnect()
                continue
            raise


def hw_claim_daily_bonus(user_id):
    for attempt in range(2):
        try:
            today = datetime.date.today().isoformat()
            conn = get_db()
            row = conn.execute(
                "SELECT last_day FROM daily_bonus WHERE user_id = ?", (user_id,)
            ).fetchone()
            if row and row[0] == today:
                return False
            conn.execute("""INSERT INTO daily_bonus (user_id, last_day) VALUES (?, ?)
                ON CONFLICT(user_id) DO UPDATE SET last_day = ?""",
                (user_id, today, today))
            conn.commit()
            return True
        except Exception as e:
            if _is_connection_error(e) and attempt == 0:
                _reconnect()
                continue
            raise


def hw_set_luck_buff(user_id, bonus):
    for attempt in range(2):
        try:
            conn = get_db()
            conn.execute("""INSERT INTO luck_buff (user_id, bonus, until_mine)
                VALUES (?, ?, 1) ON CONFLICT(user_id) DO UPDATE SET bonus = ?, until_mine = 1""",
                (user_id, bonus, bonus))
            conn.commit()
            return
        except Exception as e:
            if _is_connection_error(e) and attempt == 0:
                _reconnect()
                continue
            raise


def hw_get_luck_buff(user_id):
    for attempt in range(2):
        try:
            conn = get_db()
            row = conn.execute(
                "SELECT bonus, until_mine FROM luck_buff WHERE user_id = ?", (user_id,)
            ).fetchone()
            if not row or row[1] <= 0:
                return 0.0
            return row[0]
        except Exception as e:
            if _is_connection_error(e) and attempt == 0:
                _reconnect()
                continue
            raise


def hw_consume_luck_buff(user_id):
    for attempt in range(2):
        try:
            conn = get_db()
            conn.execute("UPDATE luck_buff SET until_mine = 0 WHERE user_id = ?", (user_id,))
            conn.commit()
            return
        except Exception as e:
            if _is_connection_error(e) and attempt == 0:
                _reconnect()
                continue
            raise
