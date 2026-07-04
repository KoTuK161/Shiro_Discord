from datetime import datetime, timedelta, timezone
import discord
from discord import app_commands
from discord.ext import commands

MSK = timezone(timedelta(hours=3))
START = datetime(2026, 6, 27, 11, 0, tzinfo=MSK)
ROTATION = timedelta(hours=4, minutes=30)
MAPS = [
    "E-District",
    "Storm Point",
    "World's Edge"
]

MAP_EMOJI = {
    "E-District":   "🏙️",
    "Storm Point":  "⛈️",
    "World's Edge": "🌋"
}

class Maps(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="map", description="Текущая карта Apex")
    async def map(self, interaction: discord.Interaction):
        now = datetime.now(MSK)

        if now < START:
            idx = 0
            slot = 0
            slot_start = START
        else:
            elapsed = now - START
            slot = int(elapsed.total_seconds() // ROTATION.total_seconds())
            idx = slot % len(MAPS)
            slot_start = START + ROTATION * slot

        slot_end = slot_start + ROTATION
        remaining = slot_end - now

        total_sec = int(remaining.total_seconds())
        h, r = divmod(total_sec, 3600)
        m, s = divmod(r, 60)

        current_map = MAPS[idx]
        emoji = MAP_EMOJI[current_map]

        # Строим расписание — следующие 6 слотов
        schedule_lines = []
        for i in range(1, 7):
            future_slot = slot + i
            future_idx = future_slot % len(MAPS)
            future_start = START + ROTATION * future_slot
            future_map = MAPS[future_idx]
            future_emoji = MAP_EMOJI[future_map]
            time_str = future_start.strftime("%H:%M")
            date_str = future_start.strftime("%d.%m")
            schedule_lines.append(f"{time_str} {date_str} — {future_emoji} {future_map}")

        schedule_text = "\n".join(schedule_lines)

        e = discord.Embed(title="Ротация карт Apex Legends", color=0x3498db)
        e.add_field(
            name="🗺️ Текущая карта",
            value=f"{emoji} **{current_map}**",
            inline=False
        )
        e.add_field(
            name="⏱️ До смены",
            value=f"{h}ч {m:02d}м {s:02d}с",
            inline=False
        )
        e.add_field(
            name="📅 Дальнейшее расписание",
            value=f"```{schedule_text}```",
            inline=False
        )

        await interaction.response.send_message(embed=e)


async def setup(bot):
    await bot.add_cog(Maps(bot))
