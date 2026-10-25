import logging
import time
import aiohttp
from telethon import events

_coins_cache = None
_coins_cache_time = 0
CACHE_TTL = 3600


async def _get_all_coins():
    global _coins_cache, _coins_cache_time
    now = time.time()
    if _coins_cache and (now - _coins_cache_time) < CACHE_TTL:
        return _coins_cache

    url = "https://api.coinpaprika.com/v1/coins"
    async with aiohttp.ClientSession() as session:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
            if resp.status != 200:
                return _coins_cache or []
            data = await resp.json()

    _coins_cache = data
    _coins_cache_time = now
    logging.info(f"Curse: загружено {len(data)} монет с CoinPaprika")
    return data


def _find_coin(query, coins):
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


def register(client):
    @client.on(events.NewMessage(pattern=r'(?i)^/?курс\s+(.+)$'))
    async def curse_cmd(event):
        query = event.pattern_match.group(1).strip()

        try:
            coins = await _get_all_coins()
        except Exception as e:
            await event.reply(f"❌ Ошибка загрузки списка монет: {e}")
            return

        if not coins:
            await event.reply("❌ Не удалось загрузить список монет. Попробуй позже.")
            return

        coin = _find_coin(query, coins)
        if not coin:
            await event.reply(f"❌ Монета «{query}» не найдена. Попробуй тикер (btc) или название (bitcoin).")
            return

        coin_id = coin["id"]
        url = f"https://api.coinpaprika.com/v1/tickers/{coin_id}"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status != 200:
                        await event.reply("❌ Не удалось получить цену.")
                        return
                    data = await resp.json()
        except Exception as e:
            await event.reply(f"❌ Ошибка запроса: {e}")
            return

        name = data.get("name", coin.get("name", coin_id))
        symbol = data.get("symbol", coin.get("symbol", "?")).upper()
        usd = data.get("quotes", {}).get("USD", {})
        price = usd.get("price")
        change = usd.get("percent_change_24h", 0) or 0
        mcap = usd.get("market_cap", 0) or 0

        if price is None:
            await event.reply("❌ Не удалось получить цену.")
            return

        arrow = "📈" if change >= 0 else "📉"
        await event.reply(
            f"💰 **{name} ({symbol})**\n"
            f"Цена: **${price:,.2f}**\n"
            f"{arrow} За 24ч: **{change:+.2f}%**\n"
            f"🏦 Капитализация: ${mcap:,.0f}",
            parse_mode='md'
        )

    logging.info("Curse module: зарегистрирован 'курс <монета>'.")
