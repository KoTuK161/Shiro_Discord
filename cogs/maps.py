from datetime import datetime, timedelta, timezone
import discord
from discord import app_commands
from discord.ext import commands

MSK = timezone(timedelta(hours=3))
START = datetime(2026,6,27,11,0,tzinfo=MSK)
ROTATION = timedelta(hours=4, minutes=30)
MAPS = [
    "E-District",
    "Storm Point",
    "World's Edge"
]

class Maps(commands.Cog):
    def __init__(self,bot):
        self.bot=bot

    @app_commands.command(name="map",description="Текущая карта Apex")
    async def map(self, interaction: discord.Interaction):
        now=datetime.now(MSK)
        if now<START:
            idx=0
            rem=START-now
        else:
            elapsed=now-START
            slot=int(elapsed.total_seconds()//ROTATION.total_seconds())
            idx=slot%len(MAPS)
            end=START+ROTATION*(slot+1)
            rem=end-now
        h, r=divmod(int(rem.total_seconds()),3600)
        m=r//60
        e=discord.Embed(title="Ротация карт Apex",color=0x3498db)
        e.add_field(name="Текущая карта",value=MAPS[idx],inline=False)
        e.add_field(name="Следующая смена",value=f"Через {h} ч {m} мин",inline=False)
        await interaction.response.send_message(embed=e)

async def setup(bot):
    await bot.add_cog(Maps(bot))
