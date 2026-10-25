import datetime
import logging
import os

import libsql_experimental as libsql

TURSO_URL = os.environ.get("TURSO_DATABASE_URL", "")
TURSO_TOKEN = os.environ.get("TURSO_AUTH_TOKEN", "")

_conn = None
logger = logging.getLogger(__name__)


def _get_db():
    global _conn
    if _conn is None:
        if not TURSO_URL or not TURSO_TOKEN:
            raise ValueError("TURSO_DATABASE_URL или TURSO_AUTH_TOKEN не заданы")
        _conn = libsql.connect(database=TURSO_URL, auth_token=TURSO_TOKEN)
        _init_tables()
    return _conn


def _init_tables() -> None:
    conn = _conn
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS profiles (
            user_id       INTEGER PRIMARY KEY,
            username      TEXT,
            first_name    TEXT,
            first_seen    TEXT,
            message_count INTEGER DEFAULT 0,
            is_criminal   INTEGER DEFAULT 0,
            awards        TEXT    DEFAULT ''
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS mutes (
            user_id    INTEGER PRIMARY KEY,
            chat_id    INTEGER NOT NULL,
            until_date TEXT    NOT NULL
        )
        """
    )
    conn.commit()
    logger.info("DB: таблицы profiles и mutes готовы")


# ------------------------- ПРОФИЛИ -------------------------

def ensure_profile(user_id: int, username: str | None, first_name: str | None) -> None:
    conn = _get_db()
    conn.execute(
        """
        INSERT INTO profiles (user_id, username, first_name, first_seen)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            username   = COALESCE(?, username),
            first_name = COALESCE(?, first_name)
        """,
        (
            user_id, username, first_name,
            datetime.date.today().isoformat(),
            username, first_name,
        ),
    )
    conn.commit()


def inc_message_count(user_id: int) -> None:
    conn = _get_db()
    conn.execute(
        "UPDATE profiles SET message_count = message_count + 1 WHERE user_id = ?",
        (user_id,),
    )
    conn.commit()


def mark_criminal(user_id: int) -> None:
    conn = _get_db()
    conn.execute("UPDATE profiles SET is_criminal = 1 WHERE user_id = ?", (user_id,))
    conn.commit()


def get_profile(user_id: int) -> dict | None:
    conn = _get_db()
    row = conn.execute(
        "SELECT user_id, username, first_name, first_seen, message_count, "
        "is_criminal, awards FROM profiles WHERE user_id = ?",
        (user_id,),
    ).fetchone()
    if not row:
        return None
    return {
        "user_id": row[0],
        "username": row[1],
        "first_name": row[2],
        "first_seen": row[3],
        "message_count": row[4],
        "is_criminal": row[5],
        "awards": row[6],
    }


def set_awards(user_id: int, awards: str) -> None:
    conn = _get_db()
    conn.execute("UPDATE profiles SET awards = ? WHERE user_id = ?", (awards, user_id))
    conn.commit()


# -------------------------- МУТЫ ---------------------------

def save_mute(user_id: int, chat_id: int, until_date: datetime.datetime) -> None:
    conn = _get_db()
    conn.execute(
        """
        INSERT INTO mutes (user_id, chat_id, until_date)
        VALUES (?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            chat_id = ?, until_date = ?
        """,
        (user_id, chat_id, until_date.isoformat(), chat_id, until_date.isoformat()),
    )
    conn.commit()


def remove_mute(user_id: int) -> None:
    conn = _get_db()
    conn.execute("DELETE FROM mutes WHERE user_id = ?", (user_id,))
    conn.commit()


def get_active_mutes() -> list[dict]:
    conn = _get_db()
    now = datetime.datetime.now().isoformat()
    rows = conn.execute(
        "SELECT user_id, chat_id, until_date FROM mutes WHERE until_date > ?",
        (now,),
    ).fetchall()
    return [
        {
            "user_id": r[0],
            "chat_id": r[1],
            "until_date": datetime.datetime.fromisoformat(r[2]),
        }
        for r in rows
    ]
