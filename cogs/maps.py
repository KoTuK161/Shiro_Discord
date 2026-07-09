import os
import time
import asyncio
from datetime import datetime, timezone, timedelta
import aiohttp
import discord
from discord import app_commands
from discord.ext import commands

API_KEY = os.getenv("APEX_API_KEY")
API_URL = "https://api.mozambiquehe.re/maprotation"

MSK = timezone(timedelta(hours=3))
ROTATION = timedelta(hours=4, minutes=30)

MAPS = [
    "E-District",
    "Storm Point",
    "World's Edge",
]

MAP_EMOJI = {
    "E-District":   "🏙️",
    "Storm Point":  "⛈️",
    "World's Edge": "🌋",
    "Kings Canyon": "🏜️",
    "Olympus":      "🌿",
    "Broken Moon":  "🌙",
}

MAP_IMAGES = {
    "E-District":   "https://cdn.discordapp.com/attachments/1265754689643872359/1523771080786055349/kvartal.png",
    "Storm Point":  "https://cdn.discordapp.com/attachments/1265754689643872359/1523776463378190527/shtorm.png",
    "World's Edge": "https://cdn.discordapp.com/attachments/1265754689643872359/1523781224391250096/world.png",
    "Kings Canyon": "",
    "Olympus":      "",
    "Broken Moon":  "",
}

SCHEDULE_SLOTS = 6
CACHE_TTL = 60

_cache = {"data": None, "ts": 0}


async def send_and_delete(interaction, delay=86400, **kwargs):
    """Отправляет followup-сообщение и удаляет его через delay секунд."""
    msg = await interaction.followup.send(**kwargs)
    async def _delete():
        await asyncio.sleep(delay)
        try:
            await msg.delete()
        except Exception:
            pass
    asyncio.create_task(_delete())


async def fetch_rotation() -> dict | None:
    now = time.time()
    if _cache["data"] and now - _cache["ts"] < CACHE_TTL:
        return _cache["data"]
    params = {"auth": API_KEY, "version": 2}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(API_URL, params=params, timeout=aiohttp.ClientTimeout(total=10)) as r:
                if r.status != 200:
                    return None
                data = await r.json()
                _cache["data"] = data
                _cache["ts"] = now
                return data
    except Exception:
        return None


def get_emoji(map_name: str) -> str:
    return MAP_EMOJI.get(map_name, "🗺️")


def format_remaining(remaining_secs: int) -> str:
    h, r = divmod(max(remaining_secs, 0), 3600)
    m, s = divmod(r, 60)
    if h > 0:
        return f"{h}ч {m:02d}м {s:02d}с"
    return f"{m}м {s:02d}с"


def round_time(dt: datetime) -> datetime:
    if dt.minute == 59:
        dt = dt + timedelta(minutes=1)
    return dt


def build_schedule(current_name: str, slot_end: datetime) -> list[str]:
    lines = []
    if current_name in MAPS:
        idx = MAPS.index(current_name)
    else:
        idx = -1

    for i in range(1, SCHEDULE_SLOTS + 1):
        future_idx = (idx + i) % len(MAPS)
        future_name = MAPS[future_idx]
        future_start = slot_end + ROTATION * (i - 1)
        future_start = round_time(future_start)
        emoji = get_emoji(future_name)
        time_str = future_start.strftime("%H:%M %d.%m")
        lines.append(f"{time_str} — {emoji} {future_name}")

    return lines


class Maps(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="map", description="Текущая карта Apex (BR Ranked)")
    async def map(self, interaction: discord.Interaction):
        await interaction.response.defer()

        data = await fetch_rotation()
        if data is None:
            await send_and_delete(interaction, content="❌ Не удалось получить данные о ротации карт. Попробуй позже.")
            return

        br = data.get("ranked")
        if not br:
            await send_and_delete(interaction, content="❌ Данные о ранкед-ротации недоступны.")
            return

        current = br.get("current", {})
        current_name = current.get("map", "Неизвестно")
        current_emoji = get_emoji(current_name)

        remaining_secs = current.get("remainingMins", 0) * 60
        remaining_str = format_remaining(remaining_secs)

        now = datetime.now(MSK)
        slot_end = now + timedelta(seconds=remaining_secs)

        schedule_lines = build_schedule(current_name, slot_end)
        schedule_text = "\n".join(schedule_lines) if schedule_lines else "Нет данных"

        e = discord.Embed(title="Ротация карт Apex Legends (Ranked)", color=0x3498db)
        e.add_field(name="🗺️ Текущая карта", value=f"{current_emoji} **{current_name}**", inline=False)
        e.add_field(name="⏱️ До смены", value=remaining_str, inline=False)
        e.add_field(name="📅 Дальнейшее расписание", value=f"```{schedule_text}```", inline=False)

        image_url = MAP_IMAGES.get(current_name)
        if image_url:
            e.set_image(url=image_url)

        await send_and_delete(interaction, embed=e)


async def setup(bot):
    await bot.add_cog(Maps(bot))
