import os, json, time
from pathlib import Path
import aiohttp
import discord
from discord import app_commands
from discord.ext import commands

API_KEY=os.getenv("APEX_API_KEY")
API_URL="https://api.mozambiquehe.re/bridge"
BASE=Path(__file__).resolve().parent.parent
DATA=BASE/"data"
DATA.mkdir(exist_ok=True)
USERS=DATA/"apex_users.json"
CACHE={}
TTL=60

RANKS=[
("Rookie",0),("Bronze",1000),("Silver",3000),("Gold",5400),
("Platinum",8200),("Diamond",11400),("Master",15000)
]
COLORS={
"Rookie":0x808080,"Bronze":0xcd7f32,"Silver":0xc0c0c0,
"Gold":0xffd700,"Platinum":0x00c8c8,"Diamond":0x4aa3ff,
"Master":0x9b59b6,"Apex Predator":0xff0000
}

class Rank(commands.Cog):
    def __init__(self,bot):
        self.bot=bot

    def save_user(self,member,nick):
        d={}
        if USERS.exists():
            try:d=json.loads(USERS.read_text("utf-8"))
            except: d={}
        sid=str(member.id)
        if sid not in d:
            d[sid]={"discord_name":member.name,"ea_name":nick}
            USERS.write_text(json.dumps(d,ensure_ascii=False,indent=2),encoding="utf-8")

    async def fetch(self,player):
        if player in CACHE and time.time()-CACHE[player][0]<TTL:
            return CACHE[player][1]
        params={"auth":API_KEY,"player":player,"platform":"PC"}
        async with aiohttp.ClientSession() as s:
            async with s.get(API_URL,params=params) as r:
                if r.status!=200:
                    return {"error":r.status}
                data=await r.json()
        CACHE[player]=(time.time(),data)
        return data

    @app_commands.command(name="rank",description="Показать ранг Apex Legends")
    async def rank(self,interaction:discord.Interaction,nick:str):
        await interaction.response.defer()
        self.save_user(interaction.user,nick)
        data=await self.fetch(nick)
        if "error" in data:
            m={404:"Игрок не найден.",429:"Лимит API превышен.",500:"Ошибка API."}
            await interaction.followup.send("❌ "+m.get(data["error"],f"HTTP {data['error']}"))
            return
        try:
            g=data["global"]; r=g["rank"]
            rp=int(r.get("rankScore",0))
            rn=r.get("rankName","Unknown")
            div=r.get("rankDiv","")
            full=(rn+" "+str(div)).strip()
            nxt=None
            for name,val in RANKS:
                if val>rp:
                    nxt=val-rp; break
            desc=f"🎮 **Ник:** {nick}\n⭐ **RP:** {rp}\n🏆 **Ранг:** {full}\n"
            desc+=f"📈 **До следующего ранга:** {nxt if nxt is not None else 'Максимальный ранг'}"
            e=discord.Embed(title="Apex Legends",description=desc,color=COLORS.get(rn,0x2f3136))
            await interaction.followup.send(embed=e)
        except Exception as ex:
            await interaction.followup.send(f"⚠ Ошибка обработки: {ex}")

async def setup(bot):
    await bot.add_cog(Rank(bot))
