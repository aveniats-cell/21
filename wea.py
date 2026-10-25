import logging
import aiohttp
from telethon import events

def register(client):
    @client.on(events.NewMessage(pattern=r'^/wea\s+(.+)'))
    async def wea_cmd(event):
        city = event.pattern_match.group(1).strip()

        # Шаг 1: геокодинг
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

        # Шаг 2: погода (current_weather — стабильный параметр)
        weather_url = "https://api.open-meteo.com/v1/forecast"
        w_params = {
            "latitude": lat,
            "longitude": lon,
            "current_weather": "true",
            "hourly": "relativehumidity_2m",
            "timezone": "auto",
        }
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(weather_url, params=w_params, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    w_data = await resp.json()
        except Exception as e:
            await event.reply(f"❌ Ошибка погоды: {e}")
            return

        cur = w_data.get("current_weather", {})
        temp = cur.get("temperature")
        wind = cur.get("windspeed")
        code = cur.get("weathercode", 0)

        # Влажность: берём из hourly за текущий час
        hum = None
        try:
            hourly = w_data.get("hourly", {})
            times = hourly.get("time", [])
            hums = hourly.get("relativehumidity_2m", [])
            cur_time = cur.get("time", "")
            if cur_time and times:
                # Ищем индекс текущего часа
                idx = times.index(cur_time) if cur_time in times else 0
                if idx < len(hums):
                    hum = hums[idx]
        except Exception:
            pass

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

        hum_str = f"{hum}%" if hum is not None else "н/д"
        wind_str = f"{wind} км/ч" if wind is not None else "н/д"
        temp_str = f"{temp}°C" if temp is not None else "н/д"

        await event.reply(
            f"🌍 **{display_name}** {country}\n"
            f"{weather_desc}\n"
            f"🌡️ Температура: **{temp_str}**\n"
            f"💧 Влажность: {hum_str}\n"
            f"💨 Ветер: {wind_str}",
            parse_mode='md'
        )

    logging.info("Wea module: зарегистрирован /wea.")
