import os
import json
import time
import asyncio
from datetime import datetime, timezone, timedelta
from pathlib import Path
import aiohttp
import discord
from discord import app_commands
from discord.ext import commands

API_KEY = os.getenv("APEX_API_KEY")
API_URL = "https://api.mozambiquehe.re/maprotation"

MSK      = timezone(timedelta(hours=3))
ROTATION = timedelta(hours=4, minutes=30)

MAPS = ["E-District", "Storm Point", "World's Edge"]

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
CACHE_TTL      = 60
_cache         = {"data": None, "ts": 0}


def get_guild_cfg(guild_id) -> dict:
    try:
        from adm_panel import DATA_FILE, DEFAULTS
        if DATA_FILE.exists():
            d   = json.loads(DATA_FILE.read_text("utf-8"))
            cfg = d.get(str(guild_id), {})
            return {**DEFAULTS, **cfg}
    except Exception:
        pass
    return {}


async def send_and_delete(interaction, delay=86400, **kwargs):
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
                _cache["ts"]   = now
                return data
    except Exception:
        return None


def get_emoji(map_name: str) -> str:
    return MAP_EMOJI.get(map_name, "🗺️")


def format_remaining(secs: int) -> str:
    h, r = divmod(max(secs, 0), 3600)
    m, s = divmod(r, 60)
    return f"{h}ч {m:02d}м {s:02d}с" if h > 0 else f"{m}м {s:02d}с"


def round_time(dt: datetime) -> datetime:
    return dt + timedelta(minutes=1) if dt.minute == 59 else dt


def build_schedule(current_name: str, slot_end: datetime) -> list[str]:
    idx = MAPS.index(current_name) if current_name in MAPS else -1
    lines = []
    for i in range(1, SCHEDULE_SLOTS + 1):
        future_name  = MAPS[(idx + i) % len(MAPS)]
        future_start = round_time(slot_end + ROTATION * (i - 1))
        lines.append(f"{future_start.strftime('%H:%M %d.%m')} — {get_emoji(future_name)} {future_name}")
    return lines


class Maps(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="map", description="Текущая карта Apex (BR Ranked)")
    async def map(self, interaction: discord.Interaction):
        # Проверка канала из adm_panel
        cfg     = get_guild_cfg(interaction.guild_id)
        chan_id = cfg.get("map_channel_id")
        if chan_id and interaction.channel_id != int(chan_id):
            await interaction.response.send_message(
                f"❌ Эта команда работает только в канале <#{chan_id}>", ephemeral=True
            )
            return

        await interaction.response.defer()
        data = await fetch_rotation()
        if data is None:
            await send_and_delete(interaction, content="❌ Не удалось получить данные ротации.")
            return
        br = data.get("ranked")
        if not br:
            await send_and_delete(interaction, content="❌ Данные ранкед-ротации недоступны.")
            return

        current       = br.get("current", {})
        current_name  = current.get("map", "Неизвестно")
        remaining_sec = current.get("remainingMins", 0) * 60
        slot_end      = datetime.now(MSK) + timedelta(seconds=remaining_sec)

        schedule_text = "\n".join(build_schedule(current_name, slot_end)) or "Нет данных"

        e = discord.Embed(title="Ротация карт Apex Legends (Ranked)", color=0x3498db)
        e.add_field(name="🗺️ Текущая карта",       value=f"{get_emoji(current_name)} **{current_name}**", inline=False)
        e.add_field(name="⏱️ До смены",             value=format_remaining(remaining_sec),                inline=False)
        e.add_field(name="📅 Дальнейшее расписание", value=f"```{schedule_text}```",                       inline=False)

        if img := MAP_IMAGES.get(current_name):
            e.set_image(url=img)

        await send_and_delete(interaction, embed=e)


async def setup(bot):
    await bot.add_cog(Maps(bot))
