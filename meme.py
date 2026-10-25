import io
import logging
import random

# Важно: библиотека imgapi использует scrapling для обхода блокировок.
# Убедитесь, что в requirements.txt добавлены строки ниже (см. в конце).
from imgapi import image_search, random_image
from telethon import events


def register(client):
    """Вызывается из main.py после старта клиента."""

    @client.on(events.NewMessage(pattern=r'^/img'))
    async def img_cmd(event):
        # Формат: /img <запрос> [количество]
        text = event.message.text[len('/img'):].strip()
        if not text:
            await event.reply(
                "❌ Использование: `/img <запрос>` или `/img <запрос> <кол-во>`\n"
                "Пример: `/img кот в космосе` или `/img закат 3`",
                parse_mode='md'
            )
            return

        parts = text.rsplit(maxsplit=1)
        query = text
        count = 1

        # Пытаемся понять, указал ли пользователь количество в конце
        if len(parts) == 2 and parts[1].isdigit():
            query = parts[0]
            count = int(parts[1])
            # Ограничиваем, чтобы не спамить и не повесить бота
            count = max(1, min(count, 5))

        try:
            # Ищем картинки. По умолчанию используем Bing и DuckDuckGo,
            # так как Google блокирует запросы с серверов Render без прокси.
            urls = image_search(query, engines=["bing", "ddg"], n=count)

            if not urls:
                await event.reply("❌ По вашему запросу ничего не найдено.")
                return

            # Отправляем картинки по одной
            for i, url in enumerate(urls, 1):
                try:
                    caption = f"🖼 **{query}** ({i}/{len(urls)})"
                    await client.send_file(
                        event.chat_id,
                        url,
                        caption=caption,
                        parse_mode='md'
                    )
                except Exception as e:
                    logging.warning(f"Не удалось отправить картинку {url}: {e}")
                    # Пропускаем битую ссылку и пробуем следующую
                    continue

        except Exception as e:
            logging.error(f"Image search error: {e}")
            await event.reply(f"❌ Ошибка поиска: `{e}`", parse_mode='md')

    # Дополнительная команда: просто случайная картинка по запросу
    @client.on(events.NewMessage(pattern=r'^/randompic'))
    async def random_pic_cmd(event):
        query = event.message.text[len('/randompic'):].strip()
        if not query:
            await event.reply("❌ Использование: `/randompic <запрос>`", parse_mode='md')
            return

        try:
            url = random_image(query, engines=["bing", "ddg"])
            if not url:
                await event.reply("❌ Ничего не найдено.")
                return
            await client.send_file(event.chat_id, url, caption=f"🎲 {query}")
        except Exception as e:
            await event.reply(f"❌ Ошибка: `{e}`", parse_mode='md')

    logging.info("Image module: зарегистрированы /img и /randompic.")
