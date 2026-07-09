import os, json, time, asyncio
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


async def send_and_delete(interaction, delay=86400, **kwargs):
    """Отправляет followup-сообщение и удаляет его через delay секунд."""
    msg = await send_and_delete(interaction, **kwargs)
    async def _delete():
        await asyncio.sleep(delay)
        try:
            await msg.delete()
        except Exception:
            pass
    asyncio.create_task(_delete())

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


def parse_rank(r: dict, rp: int):
    api_rank_name = r.get("rankName", "")
    api_rank_div  = str(r.get("rankDiv", "")).strip()
    ladder_pos    = r.get("ladderPosPlatform") or r.get("ladderPos")

    if api_rank_name == "Apex Predator":
        rank_name = "Apex Predator"
        tier      = "Apex Predator"
        next_str  = f"Место в топе:** **#{ladder_pos}" if ladder_pos else "Топ 750"
    elif api_rank_name == "Master":
        rank_name = "Master"
        tier      = "Master"
        next_str  = "Максимальный ранг (кроме Predator)"
    else:
        _, next_rp = get_rank_info(rp)
        next_str = f"{next_rp} RP" if next_rp is not None else "Максимальный ранг"
        if api_rank_name and api_rank_div and api_rank_div != "0":
            rank_name = f"{api_rank_name} {api_rank_div}"
        elif api_rank_name:
            rank_name = api_rank_name
        else:
            rank_name, _ = get_rank_info(rp)
        tier = api_rank_name if api_rank_name else rank_name.split()[0]

    return rank_name, tier, next_str


def format_rank_str(r: dict, rp: int):
    api_rank_name = r.get("rankName", "")
    api_rank_div  = str(r.get("rankDiv", "")).strip()
    ladder_pos    = r.get("ladderPosPlatform") or r.get("ladderPos")

    if api_rank_name == "Apex Predator":
        if ladder_pos:
            return f"Apex Predator (#{ladder_pos} в топе, {rp} RP)"
        return f"Apex Predator ({rp} RP)"
    elif api_rank_name == "Master":
        return f"Master ({rp} RP)"
    elif api_rank_name and api_rank_div and api_rank_div != "0":
        return f"{api_rank_name} {api_rank_div} ({rp} RP)"
    else:
        rank_name, _ = get_rank_info(rp)
        return f"{rank_name} ({rp} RP)"


def load_users() -> dict:
    if USERS.exists():
        try:
            return json.loads(USERS.read_text("utf-8"))
        except:
            pass
    return {}


def save_users(d: dict):
    USERS.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")

def get_display_name(entry: dict=None, api_data=None):
    entry = entry or {}
    display = (entry.get("display_name") or "").strip()
    if display:
        return display
    ea = (entry.get("ea_name") or "").strip()
    if ea:
        return ea
    if api_data:
        return api_data.get("global",{}).get("name","?")
    return "?"


class Rank(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    def register_user(self, member, guild_id, ea_name: str, uid: str):
        """
        Записывает пользователя в JSON только если его там ещё нет.
        Всегда сохраняет и ник и UID одновременно.
        """
        d = load_users()
        key = f"{member.id}:{guild_id}"
        if key not in d:
            d[key] = {
                "discord_id":   str(member.id),
                "guild_id":     str(guild_id),
                "discord_name": member.name,
                "ea_name":      ea_name,
                "display_name": "",
                "uid":          uid,
            }
            save_users(d)

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

    def build_embed(self, data, identifier, footer=None):
        g = data["global"]
        r = g["rank"]
        rp = int(r.get("rankScore", 0))

        rank_name, tier, next_str = parse_rank(r, rp)
        color = COLORS.get(tier, 0x2f3136)

        rt = data.get("realtime", {})
        is_online  = rt.get("isOnline", 0)
        is_in_game = rt.get("isInGame", 0)
        party_full = rt.get("partyFull", 0)

        online_str = "🟢 Онлайн"    if is_online  else "🔴 Оффлайн"
        ingame_str = "🎮 В игре"    if is_in_game else "🏠 В лобби"
        party_str  = "🔒 Заполнено" if party_full else "🔓 Есть место"

        if tier == "Apex Predator":
            desc = (
                f"🎮 **Ник:** {identifier}\n\n"
                f"⭐ **RP:** {rp}\n\n"
                f"🏆 **Ранг:** {rank_name}\n\n"
                f"**{next_str}**\n\n"
                f"**Статус:** {online_str}"
            )
        else:
            desc = (
                f"🎮 **Ник:** {identifier}\n\n"
                f"⭐ **RP:** {rp}\n\n"
                f"🏆 **Ранг:** {rank_name}\n\n"
                f"📈 **До следующего дивизиона:** {next_str}\n\n"
                f"**Статус:** {online_str}"
            )
        if is_online:
            desc += f" · {ingame_str}\n**Пати:** {party_str}"

        embed = discord.Embed(title="Apex Legends", description=desc, color=color)
        # Иконка ранга из API (приоритет) или из локальной таблицы как fallback
        thumb_url = RANK_THUMBNAIL.get(tier)
        if thumb_url:
            embed.set_thumbnail(url=thumb_url)
        if footer:
            embed.set_footer(text=footer)
        return embed

    # ==========================================================
    # /rank — по нику EA
    # ==========================================================

    @app_commands.command(name="rank", description="Показать ранг по нику EA")
    async def rank(self, interaction: discord.Interaction, nick: str):
        await interaction.response.defer()
        data = await self.fetch(player=nick)
        if "error" in data:
            m = {
                404: "Игрок не найден. Попробуй `/rankuid` с числовым UID.",
                429: "Лимит API превышен.",
                500: "Ошибка API."
            }
            await send_and_delete(interaction, "❌ " + m.get(data["error"], f"HTTP {data['error']}"))
            return
        try:
            # Берём UID и ник прямо из ответа API
            ea_name = data["global"].get("name", nick)
            uid     = str(data["global"].get("uid", ""))
            self.register_user(interaction.user, interaction.guild_id, ea_name, uid)
            entry = load_users().get(f"{interaction.user.id}:{interaction.guild_id}", {})
            await send_and_delete(interaction, embed=self.build_embed(data, get_display_name(entry, data)))
        except Exception as ex:
            await send_and_delete(interaction, f"⚠ Ошибка обработки: {ex}")

    # ==========================================================
    # /rankuid — по числовому UID
    # ==========================================================

    @app_commands.command(name="rankuid", description="Показать ранг по числовому UID (если ник не работает)")
    async def rankuid(self, interaction: discord.Interaction, uid: str):
        await interaction.response.defer()
        if not uid.isdigit():
            await send_and_delete(interaction, 
                "❌ UID должен быть числовым EA-идентификатором.\n\n"
                "Как найти свой EA UID:\n"
                "1. Зайди на https://apexlegendsstatus.com\n"
                "2. Найди свой профиль по нику\n"
                "3. В адресной строке будет ссылка вида `/profile/uid/PC/1234567890` — "
                "это и есть твой UID (только цифры)"
            )
            return
        data = await self.fetch(uid=uid)
        if "error" in data:
            m = {404: "Игрок не найден.", 429: "Лимит API превышен.", 500: "Ошибка API."}
            await send_and_delete(interaction, "❌ " + m.get(data["error"], f"HTTP {data['error']}"))
            return
        try:
            # Берём ник прямо из ответа API
            ea_name = data["global"].get("name", uid)
            self.register_user(interaction.user, interaction.guild_id, ea_name, uid)
            entry = load_users().get(f"{interaction.user.id}:{interaction.guild_id}", {})
            await send_and_delete(interaction, embed=self.build_embed(data, get_display_name(entry, data)))
        except Exception as ex:
            await send_and_delete(interaction, f"⚠ Ошибка обработки: {ex}")

    # ==========================================================
    # /rankds — по Discord-тегу
    # ==========================================================

    @app_commands.command(name="rankds", description="Показать ранг пользователя Discord по его тегу")
    @app_commands.describe(member="Пользователь Discord, чей ранг хочешь посмотреть")
    async def rankds(self, interaction: discord.Interaction, member: discord.Member):
        await interaction.response.defer()

        d = load_users()
        key = f"{member.id}:{interaction.guild_id}"
        entry = d.get(key)

        if not entry:
            await send_and_delete(interaction, 
                f"❌ Пользователь {member.mention} ещё не привязал свой Apex аккаунт.\n"
                f"Ему нужно использовать `/rank <EA ник>` или `/rankuid <uid>`."
            )
            return

        # Ищем по UID если есть — надёжнее
        if entry.get("uid"):
            data = await self.fetch(uid=entry["uid"])
        else:
            data = await self.fetch(player=entry.get("ea_name"))

        if "error" in data:
            m = {404: "Игрок не найден.", 429: "Лимит API превышен.", 500: "Ошибка API."}
            await send_and_delete(interaction, "❌ " + m.get(data["error"], f"HTTP {data['error']}"))
            return

        try:
            identifier = get_display_name(entry, data)
            footer = f"Discord: {member.display_name} ({member.name})"
            await send_and_delete(interaction, embed=self.build_embed(data, identifier, footer=footer))
        except Exception as ex:
            await send_and_delete(interaction, f"⚠ Ошибка обработки: {ex}")

    # ==========================================================
    # /rank_list — список сервера
    # ==========================================================

    @app_commands.command(name="rank_list", description="Список игроков с рангами на этом сервере")
    async def rank_list(self, interaction: discord.Interaction):
        await interaction.response.defer()

        d = load_users()
        gid = str(interaction.guild_id)
        guild_users = [v for v in d.values() if v.get("guild_id") == gid]

        if not guild_users:
            await send_and_delete(interaction, "📋 На этом сервере пока никто не использовал `/rank`.")
            return

        async with interaction.channel.typing():
            players = []
            for u in guild_users:
                discord_id = u.get("discord_id")
                mention = f"<@{discord_id}>" if discord_id else u.get("discord_name", "?")

                # Всегда ищем по UID — он надёжнее ника
                if u.get("uid"):
                    data = await self.fetch(uid=u["uid"])
                else:
                    data = await self.fetch(player=u.get("ea_name"))

                if "error" in data:
                    players.append({
                        "mention":  mention,
                        "ea_name":  u.get("ea_name", "?"),
                        "rank_str": "❓ Не удалось получить",
                        "rp":       -1,
                    })
                else:
                    try:
                        rp      = int(data["global"]["rank"].get("rankScore", 0))
                        r_block = data["global"]["rank"]
                        ea_name = get_display_name(u, data)
                        players.append({
                            "mention":  mention,
                            "ea_name":  ea_name,
                            "rank_str": format_rank_str(r_block, rp),
                            "rp":       rp,
                        })
                    except Exception:
                        players.append({
                            "mention":  mention,
                            "ea_name":  u.get("ea_name", "?"),
                            "rank_str": "❓ Ошибка данных",
                            "rp":       -1,
                        })

            players.sort(key=lambda x: x["rp"], reverse=True)

            lines = []
            for i, p in enumerate(players, start=1):
                lines.append(
                    f"**#{i}** {p['mention']}\n"
                    f"Ник: **{p['ea_name']}**\n"
                    f"Ранг: **{p['rank_str']}**"
                )

            embed = discord.Embed(
                title="🏆 Ranked список сервера",
                description="\n\n".join(lines),
                color=0x3498db
            )
            embed.set_footer(text=f"Всего игроков: {len(players)}")
            await send_and_delete(interaction, embed=embed)

    # ==========================================================
    # /unrank — удалить свою запись
    # ==========================================================

    @app_commands.command(name="unrank", description="Удалить свой Apex аккаунт из списка сервера")
    async def unrank(self, interaction: discord.Interaction):
        d = load_users()
        key = f"{interaction.user.id}:{interaction.guild_id}"

        if key not in d:
            await interaction.response.send_message(
                "❌ Твой аккаунт не привязан на этом сервере.",
                ephemeral=True
            )
            return

        ea_name = d[key].get("ea_name", "?")
        del d[key]
        save_users(d)
        await interaction.response.send_message(
            f"✅ Аккаунт **{ea_name}** удалён из списка сервера.",
            ephemeral=True
        )


async def setup(bot):
    await bot.add_cog(Rank(bot))
