import logging
import aiohttp
from telethon import events

def register(client):
    @client.on(events.NewMessage(pattern=r'^/wea\s+(.+)'))
    async def wea_cmd(event):
        city = event.pattern_match.group(1).strip()

        # Шаг 1: геокодинг (город -> координаты)
        geo_url = "https://geocoding-api.open-meteo.com/v1/search"
        params = {"name": city, "count": 1, "language": "ru", "format": "json"}
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(geo_url, params=params, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    geo_data = await resp.json()
        except Exception as e:
            await event.reply(f"❌ Ошибка геокодинга: {e}")
            return

        results = geo_data.get("results")
        if not results:
            await event.reply("❌ Город не найден. Попробуй написать название по-другому (например, Tambow или Тамбов).")
            return

        loc = results[0]
        lat, lon = loc["latitude"], loc["longitude"]
        display_name = loc.get("name", city)
        country = loc.get("country", "")

        # Шаг 2: погода — используем НОВЫЙ параметр current с правильными именами полей
        weather_url = "https://api.open-meteo.com/v1/forecast"
        w_params = {
            "latitude": lat,
            "longitude": lon,
            "current": "temperature_2m,wind_speed_10m,weather_code,relative_humidity_2m",
            "timezone": "auto",
        }
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(weather_url, params=w_params, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    w_data = await resp.json()
        except Exception as e:
            await event.reply(f"❌ Ошибка погоды: {e}")
            return

        # Парсим объект current (новый формат)
        cur = w_data.get("current", {})
        temp = cur.get("temperature_2m")
        wind = cur.get("wind_speed_10m")
        hum = cur.get("relative_humidity_2m")
        code = cur.get("weather_code", 0)

        # Если вдруг current пустой — сообщаем
        if temp is None and wind is None:
            await event.reply("❌ Не удалось получить данные о погоде. Попробуй позже.")
            return

        # Расшифровка WMO-кодов
        weather_desc = {
            0: "☀️ Ясно", 1: "🌤️ Малооблачно", 2: "⛅ Переменная облачность", 3: "☁️ Пасмурно",
            45: "🌫️ Туман", 48: "🌫️ Изморозь",
            51: "🌦️ Лёгкая морось", 53: "🌦️ Морось", 55: "🌧️ Сильная морось",
            61: "🌧️ Небольшой дождь", 63: "🌧️ Дождь", 65: "🌧️ Сильный дождь",
            71: "🌨️ Небольшой снег", 73: "🌨️ Снег", 75: "❄️ Сильный снег",
            80: "🌦️ Ливень", 81: "🌧️ Сильный ливень", 82: "⛈️ Очень сильный ливень",
            95: "⛈️ Гроза", 96: "⛈️ Гроза с градом", 99: "⛈️ Сильная гроза с градом",
        }.get(code, "🌡️ Неизвестно")

        temp_str = f"{temp}°C" if temp is not None else "н/д"
        hum_str = f"{hum}%" if hum is not None else "н/д"
        wind_str = f"{wind} км/ч" if wind is not None else "н/д"

        await event.reply(
            f"🌍 **{display_name}** {country}\n"
            f"{weather_desc}\n"
            f"🌡️ Температура: **{temp_str}**\n"
            f"💧 Влажность: {hum_str}\n"
            f"💨 Ветер: {wind_str}",
            parse_mode='md'
        )

    logging.info("Wea module: зарегистрирован /wea.")
