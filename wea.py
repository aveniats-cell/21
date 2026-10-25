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
            await event.reply("❌ Город не найден.")
            return

        loc = results[0]
        lat, lon = loc["latitude"], loc["longitude"]
        display_name = loc.get("name", city)
        country = loc.get("country", "")

        # Шаг 2: погода по координатам
        weather_url = "https://api.open-meteo.com/v1/forecast"
        w_params = {
            "latitude": lat, "longitude": lon,
            "current": "temperature_2m,apparent_temperature,relative_humidity_2m,wind_speed_10m,weather_code",
            "timezone": "auto",
        }
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(weather_url, params=w_params, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    w_data = await resp.json()
        except Exception as e:
            await event.reply(f"❌ Ошибка погоды: {e}")
            return

        cur = w_data.get("current", {})
        temp = cur.get("temperature_2m")
        feels = cur.get("apparent_temperature")
        hum = cur.get("relative_humidity_2m")
        wind = cur.get("wind_speed_10m")
        code = cur.get("weather_code", 0)

        # Расшифровка WMO-кодов (основные)
        weather_desc = {
            0: "☀️ Ясно", 1: "🌤️ Малооблачно", 2: "⛅ Переменная облачность", 3: "☁️ Пасмурно",
            45: "🌫️ Туман", 48: "🌫️ Изморозь",
            51: "🌦️ Лёгкая морось", 53: "🌦️ Морось", 55: "🌧️ Сильная морось",
            61: "🌧️ Небольшой дождь", 63: "🌧️ Дождь", 65: "🌧️ Сильный дождь",
            71: "🌨️ Небольшой снег", 73: "🌨️ Снег", 75: "❄️ Сильный снег",
            80: "🌦️ Ливень", 81: "🌧️ Сильный ливень", 82: "⛈️ Очень сильный ливень",
            95: "⛈️ Гроза", 96: "⛈️ Гроза с градом", 99: "⛈️ Сильная гроза с градом",
        }.get(code, "🌡️ Неизвестно")

        await event.reply(
            f"🌍 **{display_name}** {country}\n"
            f"{weather_desc}\n"
            f"🌡️ Температура: **{temp}°C** (ощущается как {feels}°C)\n"
            f"💧 Влажность: {hum}%\n"
            f"💨 Ветер: {wind} м/с",
            parse_mode='md'
        )

    logging.info("Wea module: зарегистрирован /wea.")
