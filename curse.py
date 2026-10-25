import logging
import re
import time
from html import escape as esc

import aiohttp
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes, MessageHandler, filters

logger = logging.getLogger(__name__)

_coins_cache: list | None = None
_coins_cache_time = 0.0
CACHE_TTL = 3600

CURSE_RE = re.compile(r"^/?курс\s+(.+)$", re.IGNORECASE)


async def _get_all_coins() -> list:
    global _coins_cache, _coins_cache_time
    now = time.time()
    if _coins_cache and (now - _coins_cache_time) < CACHE_TTL:
        return _coins_cache

    url = "https://api.coinpaprika.com/v1/coins"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status != 200:
                    return _coins_cache or []
                data = await resp.json()
    except Exception as e:
        logger.warning("Curse: не удалось загрузить список монет: %s", e)
        return _coins_cache or []

    _coins_cache = data
    _coins_cache_time = now
    logger.info("Curse: загружено %s монет с CoinPaprika", len(data))
    return data


def _find_coin(query: str, coins: list) -> dict | None:
    q = query.lower().strip()
    for c in coins:
        if c.get("symbol", "").lower() == q:
            return c
    for c in coins:
        if c.get("name", "").lower() == q:
            return c
    for c in coins:
        if q in c.get("name", "").lower():
            return c
    return None


def register(app) -> None:
    async def curse_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        msg = update.effective_message
        m = CURSE_RE.match(msg.text or "")
        if not m:
            return
        query = m.group(1).strip()

        coins = await _get_all_coins()
        if not coins:
            await msg.reply_text("❌ Не удалось загрузить список монет. Попробуй позже.")
            return

        coin = _find_coin(query, coins)
        if not coin:
            await msg.reply_text(
                f"❌ Монета «{esc(query)}» не найдена. "
                f"Попробуй тикер (btc) или название (bitcoin).",
                parse_mode=ParseMode.HTML,
            )
            return

        coin_id = coin["id"]
        url = f"https://api.coinpaprika.com/v1/tickers/{coin_id}"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status != 200:
                        await msg.reply_text("❌ Не удалось получить цену.")
                        return
                    data = await resp.json()
        except Exception as e:
            await msg.reply_text(f"❌ Ошибка запроса: {esc(str(e))}", parse_mode=ParseMode.HTML)
            return

        name = data.get("name", coin.get("name", coin_id))
        symbol = data.get("symbol", coin.get("symbol", "?")).upper()
        usd = data.get("quotes", {}).get("USD", {})
        price = usd.get("price")
        change = usd.get("percent_change_24h", 0) or 0
        mcap = usd.get("market_cap", 0) or 0

        if price is None:
            await msg.reply_text("❌ Не удалось получить цену.")
            return

        arrow = "📈" if change >= 0 else "📉"
        await msg.reply_text(
            f"💰 <b>{esc(name)} ({esc(symbol)})</b>\n"
            f"Цена: <b>${price:,.2f}</b>\n"
            f"{arrow} За 24ч: <b>{change:+.2f}%</b>\n"
            f"🏦 Капитализация: ${mcap:,.0f}",
            parse_mode=ParseMode.HTML,
        )

    app.add_handler(MessageHandler(filters.Regex(CURSE_RE), curse_cmd))

    logger.info("Curse module: 'курс <монета>' зарегистрирован.")
