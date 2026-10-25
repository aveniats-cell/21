import logging
import aiohttp
from telethon import events

# Простой маппинг тикеров на ID CoinPaprika
COIN_MAP = {
    "btc": "btc-bitcoin", "bitcoin": "btc-bitcoin",
    "eth": "eth-ethereum", "ethereum": "eth-ethereum",
    "sol": "sol-solana", "solana": "sol-solana",
    "doge": "doge-dogecoin", "dogecoin": "doge-dogecoin",
    "ton": "ton-toncoin", "toncoin": "ton-toncoin",
    "xrp": "xrp-xrp", "ada": "ada-cardano",
}

def register(client):
    @client.on(events.NewMessage(pattern=r'^/curse\s+(.+)'))
    async def curse_cmd(event):
        query = event.pattern_match.group(1).strip().lower()
        coin_id = COIN_MAP.get(query, query)  # если не в маппинге — пробуем как есть

        url = f"https://api.coinpaprika.com/v1/tickers/{coin_id}"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status != 200:
                        await event.reply("❌ Монета не найдена. Попробуй тикер (btc, eth) или название.")
                        return
                    data = await resp.json()
        except Exception as e:
            await event.reply(f"❌ Ошибка запроса: {e}")
            return

        name = data.get("name", coin_id)
        symbol = data.get("symbol", "?").upper()
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

    logging.info("Curse module: зарегистрирован /curse.")
