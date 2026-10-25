import io
import json
import logging
import urllib.request

from telethon import events


# === РЕГИСТРАЦИЯ ВСЕХ ХЭНДЛЕРОВ МОДУЛЯ ===
def register(client):
    """Вызывается из main.py после старта клиента."""

    @client.on(events.NewMessage(pattern=r'^/meme'))
    async def meme_cmd(event):
        # Опционально: /meme <subreddit> — мем из конкретного сабреддита
        args = event.message.text.split()
        subreddit = args[1].lstrip('r/') if len(args) > 1 else "memes"

        try:
            url = f"https://meme-api.com/gimme/{subreddit}"
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=10) as r:
                data = json.loads(r.read().decode())
        except Exception as e:
            await event.reply(f"❌ Не удалось загрузить мем: {e}")
            return

        # Фильтр NSFW — обязательно, контент с Reddit непредсказуем
        if data.get("nsfw"):
            await event.reply("🔞 Мем оказался NSFW. Попробуй ещё раз.")
            return

        title = data.get("title", "Без названия")[:100]
        sub = data.get("subreddit", subreddit)
        ups = data.get("ups", 0)
        image_url = data.get("url", "")

        if not image_url:
            await event.reply("❌ Мем без картинки. Попробуй ещё раз.")
            return

        caption = f"**{title}**\n\nr/{sub} · ⬆ {ups:,}"

        try:
            # Telethon умеет отправлять картинку прямо по URL
            await client.send_file(event.chat_id, image_url, caption=caption, parse_mode='md')
        except Exception:
            # Fallback: если URL со спецсимволами не прошёл — качаем и шлём как файл
            try:
                req = urllib.request.Request(image_url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=15) as r:
                    img_data = io.BytesIO(r.read())
                    img_data.name = "meme.jpg"
                await client.send_file(event.chat_id, img_data, caption=caption, parse_mode='md')
            except Exception as e:
                await event.reply(f"❌ Не удалось отправить мем: {e}")

    logging.info("Meme module: зарегистрирован /meme.")
