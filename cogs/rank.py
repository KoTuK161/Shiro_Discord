import os, json, time
from pathlib import Path
import aiohttp
import discord
from discord import app_commands
from discord.ext import commands

API_KEY = os.getenv("APEX_API_KEY")
API_URL = "https://api.mozambiquehe.re/bridge"
BASE = Path(__file__).resolve().parent.parent
DATA = BASE / "data"
DATA.mkdir(exist_ok=True)
USERS = DATA / "apex_users.json"
CACHE = {}
TTL = 60

RANKS = [
    ("Rookie IV",     0),
    ("Rookie III",    250),
    ("Rookie II",     500),
    ("Rookie I",      750),
    ("Bronze IV",     1000),
    ("Bronze III",    1500),
    ("Bronze II",     2000),
    ("Bronze I",      2500),
    ("Silver IV",     3000),
    ("Silver III",    3500),
    ("Silver II",     4000),
    ("Silver I",      4500),
    ("Gold IV",       5500),
    ("Gold III",      6250),
    ("Gold II",       7000),
    ("Gold I",        7750),
    ("Platinum IV",   8500),
    ("Platinum III",  9250),
    ("Platinum II",   10000),
    ("Platinum I",    11000),
    ("Diamond IV",    12000),
    ("Diamond III",   13000),
    ("Diamond II",    14000),
    ("Diamond I",     15000),
    ("Master",        16000),
    ("Apex Predator", 999999),
]

COLORS = {
    "Rookie":        0x808080,
    "Bronze":        0xcd7f32,
    "Silver":        0xc0c0c0,
    "Gold":          0xffd700,
    "Platinum":      0x00c8c8,
    "Diamond":       0x4aa3ff,
    "Master":        0x9b59b6,
    "Apex Predator": 0xff0000,
}

# Вставь сюда прямые ссылки на PNG из Discord
# ПКМ по загруженной картинке -> "Копировать ссылку на медиа"
RANK_THUMBNAIL = {
    "Rookie":        "https://cdn.discordapp.com/attachments/1265754689643872359/1522668237572280531/baje.png",
    "Bronze":        "https://cdn.discordapp.com/attachments/1265754689643872359/1522668237572280531/baje.png",
    "Silver":        "https://cdn.discordapp.com/attachments/1265754689643872359/1522668237572280531/baje.png",
    "Gold":          "https://cdn.discordapp.com/attachments/1265754689643872359/1522668237572280531/baje.png",
    "Platinum":      "https://cdn.discordapp.com/attachments/1265754689643872359/1522668237572280531/baje.png",
    "Diamond":       "https://cdn.discordapp.com/attachments/1265754689643872359/1522668237572280531/baje.png",
    "Master":        "https://cdn.discordapp.com/attachments/1265754689643872359/1522668237572280531/baje.png",
    "Apex Predator": "https://cdn.discordapp.com/attachments/1265754689643872359/1522668237572280531/baje.png",
}


def get_rank_info(rp: int):
    """Определяет текущий ранг и сколько RP до следующего дивизиона."""
    current_name = RANKS[0][0]
    next_rp = None
    for i, (name, threshold) in enumerate(RANKS):
        if rp >= threshold:
            current_name = name
            if i + 1 < len(RANKS):
                next_rp = RANKS[i + 1][1] - rp
        else:
            break
    return current_name, next_rp


class Rank(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    def save_user(self, member, guild_id, identifier, by_uid=False):
        d = {}
        if USERS.exists():
            try:
                d = json.loads(USERS.read_text("utf-8"))
            except:
                d = {}
        sid = str(member.id)
        gid = str(guild_id)
        # Ключ — discord_id:guild_id, чтобы один человек мог быть на разных серверах
        key = f"{sid}:{gid}"
        entry = {
            "discord_id":   sid,
            "guild_id":     gid,
            "discord_name": member.name,
        }
        if by_uid:
            entry["uid"] = identifier
        else:
            entry["ea_name"] = identifier
        d[key] = entry  # всегда обновляем
        USERS.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")

    async def fetch(self, player=None, uid=None):
        cache_key = uid if uid else player
        if cache_key in CACHE and time.time() - CACHE[cache_key][0] < TTL:
            return CACHE[cache_key][1]
        if uid:
            params = {"auth": API_KEY, "uid": uid, "platform": "PC"}
        else:
            params = {"auth": API_KEY, "player": player, "platform": "PC"}
        async with aiohttp.ClientSession() as s:
            async with s.get(API_URL, params=params) as r:
                if r.status != 200:
                    return {"error": r.status}
                data = await r.json()
        CACHE[cache_key] = (time.time(), data)
        return data

    def build_embed(self, data, identifier):
        g = data["global"]
        r = g["rank"]
        rp = int(r.get("rankScore", 0))
        rank_name, next_rp = get_rank_info(rp)
        tier = rank_name.split()[0]
        color = COLORS.get(tier, 0x2f3136)

        if next_rp is not None:
            next_str = f"{next_rp} RP"
        else:
            next_str = "Максимальный ранг"

        # Realtime данные
        rt = data.get("realtime", {})
        is_online  = rt.get("isOnline", 0)
        is_in_game = rt.get("isInGame", 0)
        party_full = rt.get("partyFull", 0)

        online_str  = "🟢 Онлайн"  if is_online  else "🔴 Оффлайн"
        ingame_str  = "🎮 В игре"  if is_in_game else "🏠 В лобби"
        party_str   = "🔒 Заполнено" if party_full else "🔓 Есть место"

        desc = (
            f"🎮 **Ник:** {g.get('name', identifier)}\n\n"
            f"⭐ **RP:** {rp}\n\n"
            f"🏆 **Ранг:** {rank_name}\n\n"
            f"📈 **До следующего дивизиона:** {next_str}\n\n"
            f"**Статус:** {online_str}"
        )

        # Статус в игре и пати показываем только если игрок онлайн
        if is_online:
            desc += f" · {ingame_str}\n**Пати:** {party_str}"
        else:
            desc += ""

        embed = discord.Embed(title="Apex Legends", description=desc, color=color)
        thumb_url = RANK_THUMBNAIL.get(tier)
        if thumb_url:
            embed.set_thumbnail(url=thumb_url)
        return embed

    @app_commands.command(name="rank", description="Показать ранг по нику EA")
    async def rank(self, interaction: discord.Interaction, nick: str):
        await interaction.response.defer()
        self.save_user(interaction.user, interaction.guild_id, nick, by_uid=False)
        data = await self.fetch(player=nick)
        if "error" in data:
            m = {
                404: "Игрок не найден. Попробуй `/rankuid` с числовым UID.",
                429: "Лимит API превышен.",
                500: "Ошибка API."
            }
            await interaction.followup.send("❌ " + m.get(data["error"], f"HTTP {data['error']}"))
            return
        try:
            await interaction.followup.send(embed=self.build_embed(data, nick))
        except Exception as ex:
            await interaction.followup.send(f"⚠ Ошибка обработки: {ex}")

    @app_commands.command(name="rankuid", description="Показать ранг по числовому UID (если ник не работает)")
    async def rankuid(self, interaction: discord.Interaction, uid: str):
        await interaction.response.defer()
        if not uid.isdigit():
            await interaction.followup.send(
                "❌ UID должен быть числовым идентификатором.\n\n"
                "Как найти свой UID:\n"
                "1. Зайди на https://steamid.io/\n"
                "2. Вставь ссылку на Steam профиль.\n"
                "3. Копируй **steamID64**\n"
                "Это и есть твой UID (только цифры)"
            )
            return
        self.save_user(interaction.user, interaction.guild_id, uid, by_uid=True)
        data = await self.fetch(uid=uid)
        if "error" in data:
            m = {404: "Игрок не найден.", 429: "Лимит API превышен.", 500: "Ошибка API."}
            await interaction.followup.send("❌ " + m.get(data["error"], f"HTTP {data['error']}"))
            return
        try:
            await interaction.followup.send(embed=self.build_embed(data, uid))
        except Exception as ex:
            await interaction.followup.send(f"⚠ Ошибка обработки: {ex}")

    @app_commands.command(name="rank_list", description="Список игроков с рангами на этом сервере")
    async def rank_list(self, interaction: discord.Interaction):
        await interaction.response.defer()

        d = {}
        if USERS.exists():
            try:
                d = json.loads(USERS.read_text("utf-8"))
            except:
                pass

        gid = str(interaction.guild_id)
        guild_users = [v for v in d.values() if v.get("guild_id") == gid]

        if not guild_users:
            await interaction.followup.send("📋 На этом сервере пока никто не использовал `/rank`.")
            return

        async with interaction.channel.typing():
            players = []
            for u in guild_users:
                discord_id = u.get("discord_id")
                mention = f"<@{discord_id}>" if discord_id else u.get("discord_name", "?")

                if u.get("uid"):
                    data = await self.fetch(uid=u["uid"])
                else:
                    data = await self.fetch(player=u.get("ea_name"))

                if "error" in data:
                    players.append({
                        "mention":  mention,
                        "ea_name":  u.get("ea_name") or u.get("uid", "?"),
                        "rank_str": "❓ Не удалось получить",
                        "rp":       -1,
                    })
                else:
                    try:
                        rp = int(data["global"]["rank"].get("rankScore", 0))
                        rank_name, _ = get_rank_info(rp)
                        # Всегда берём ник из API, не из JSON
                        ea_name = data["global"].get("name", u.get("ea_name") or u.get("uid", "?"))
                        players.append({
                            "mention":  mention,
                            "ea_name":  ea_name,
                            "rank_str": f"{rank_name} ({rp} RP)",
                            "rp":       rp,
                        })
                    except Exception:
                        players.append({
                            "mention":  mention,
                            "ea_name":  u.get("ea_name") or u.get("uid", "?"),
                            "rank_str": "❓ Ошибка данных",
                            "rp":       -1,
                        })

            # Сортируем по убыванию RP
            players.sort(key=lambda x: x["rp"], reverse=True)

            lines = []
            for i, p in enumerate(players, start=1):
                lines.append(
                    f"**#{i}** {p['mention']}\n"
                    f"EA ник: **{p['ea_name']}**\n"
                    f"Ранг: **{p['rank_str']}**"
                )

            embed = discord.Embed(
                title="🏆 Ranked список сервера",
                description="\n\n".join(lines),
                color=0x3498db
            )
            embed.set_footer(text=f"Всего игроков: {len(players)}")
            await interaction.followup.send(embed=embed)


    @app_commands.command(name="rankds", description="Показать ранг пользователя Discord по его тегу")
    @app_commands.describe(member="Пользователь Discord, чей ранг хочешь посмотреть")
    async def rankds(self, interaction: discord.Interaction, member: discord.Member):
        await interaction.response.defer()

        # Ищем пользователя в JSON по discord_id и guild_id
        d = {}
        if USERS.exists():
            try:
                d = json.loads(USERS.read_text("utf-8"))
            except:
                pass

        gid = str(interaction.guild_id)
        sid = str(member.id)
        key = f"{sid}:{gid}"
        entry = d.get(key)

        if not entry:
            await interaction.followup.send(
                f"❌ Пользователь {member.mention} ещё не привязал свой Apex аккаунт.\n"
                f"Ему нужно использовать `/rank <EA ник>` или `/rankuid <uid>`."
            )
            return

        # Получаем данные из API
        if entry.get("uid"):
            data = await self.fetch(uid=entry["uid"])
        else:
            data = await self.fetch(player=entry.get("ea_name"))

        if "error" in data:
            m = {404: "Игрок не найден.", 429: "Лимит API превышен.", 500: "Ошибка API."}
            await interaction.followup.send("❌ " + m.get(data["error"], f"HTTP {data['error']}"))
            return

        try:
            identifier = entry.get("ea_name") or entry.get("uid", "?")
            embed = self.build_embed(data, identifier)
            # Добавляем в footer упоминание Discord пользователя
            embed.set_footer(text=f"Discord: {member.display_name} ({member.name})")
            await interaction.followup.send(embed=embed)
        except Exception as ex:
            await interaction.followup.send(f"⚠ Ошибка обработки: {ex}")


async def setup(bot):
    await bot.add_cog(Rank(bot))
