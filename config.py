"""Все секреты — из ENV Render (Settings → Environment)."""
import logging
import os

ADMIN_USERNAME = (os.environ.get("ADMIN_USERNAME") or "@YouWarm").lstrip("@").lower()
ADMIN_ID_RAW   = (os.environ.get("ADMIN_ID") or "").strip()
BOT_TOKEN      = (os.environ.get("BOT_TOKEN") or "").strip()
TURSO_URL      = (os.environ.get("TURSO_URL") or "").strip()
TURSO_API      = (os.environ.get("TURSO_API") or "").strip()
API_ID         = int(os.environ.get("API_ACC") or "0")
API_HASH       = (os.environ.get("API_HASH") or "").strip()
PORT           = int(os.environ.get("PORT") or "8080")

ADMIN_ID = int(ADMIN_ID_RAW) if ADMIN_ID_RAW.isdigit() else None

MAX_MUTE_SEC   = 30 * 24 * 3600
COINS_START    = 100
CREDIT_MAX     = 100


def validate():
    missing = []
    if not BOT_TOKEN:  missing.append("BOT_TOKEN")
    if not TURSO_URL:  missing.append("TURSO_URL")
    if not TURSO_API:  missing.append("TURSO_API")
    if missing:
        logging.basicConfig(level=logging.ERROR)
        logging.error(
            "❌ Не заданы ENV в Render → Environment:\n   "
            + "\n   ".join(missing)
            + "\n   Задай переменные и сделай Manual Deploy."
        )
        raise SystemExit(1)
    # Диагностика: покажем, что реально доехало (без утечки секретов)
    logging.info(
        "ENV OK: BOT_TOKEN=%s TURSO_URL=%s TURSO_API=%s ADMIN_ID=%s ADMIN_USERNAME=%s",
        f"***{BOT_TOKEN[-4:]}" if BOT_TOKEN else "none",
        TURSO_URL,
        "set" if TURSO_API else "missing",
        ADMIN_ID,
        ADMIN_USERNAME,
    )
