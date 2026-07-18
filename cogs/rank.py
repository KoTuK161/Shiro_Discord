import os, json, time, asyncio, logging
from datetime import datetime, timezone, timedelta
from pathlib import Path
import aiohttp
import discord
from discord import app_commands
from discord.ext import commands, tasks

log = logging.getLogger(__name__)

API_KEY = os.getenv("APEX_API_KEY")
API_URL = "https://api.mozambiquehe.re/bridge"
BASE    = Path(__file__).resolve().parent.parent
DATA    = BASE / "data"
DATA.mkdir(exist_ok=True)
USERS   = DATA / "apex_users.json"
CACHE   = {}
TTL     = 60
PRED_CACHE = {"data": None, "ts": 0}
PRED_TTL   = 300
MSK = timezone(timedelta(hours=3))

RANK_LIST_DELETE_LAST = 5

RANK_EMOJI = {
    "Apex Predator": "<:apexpredator1:1262965581448216597>",
    "Master":        "<:master1:1262965564469674035>",
    "Diamond I":     "<:diamond1:1262965538305609818>",
    "Diamond II":    "<:diamond2:1262965540222406706>",
    "Diamond III":   "<:diamond3:1262965541610590259>",
    "Diamond IV":    "<:diamond4:1262965543087116329>",
    "Platinum I":    "<:platinum1:1262965428376834069>",
    "Platinum II":   "<:platinum2:1262965430054555768>",
    "Platinum III":  "<:platinum3:1262965431648518175>",
    "Platinum IV":   "<:platinum4:1262965433338822666>",
    "Gold I":        "<:gold1:1262965228589809755>",
    "Gold II":       "<:gold2:1262965229990445077>",
    "Gold III":      "<:gold3:1262965231873818706>",
    "Gold IV":       "<:gold4:1262965233467785370>",
    "Silver I":      "<:silver1:1262964955242565755>",
    "Silver II":     "<:silver2:1262964956715024476>",
    "Silver III":    "<:silver3:1262964958820569138>",
    "Silver IV":     "<:silver4:1262964960426987631>",
    "Bronze I":      "<:bronze1:1262964908564283432>",
    "Bronze II":     "<:bronze2:1262964910137151621>",
    "Bronze III":    "<:bronze3:1262964911613546537>",
    "Bronze IV":     "<:bronze4:1262964913177890957>",
    "Rookie I":      "<:rookie1:1262964851521753189>",
    "Rookie II":     "<:rookie2:1262964853224505355>",
    "Rookie III":    "<:rookie3:1262964854788984884>",
    "Rookie IV":     "<:rookie4:1262964856546525186>",
}

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
    "Apex Predator": "https://cdn.discordapp.com/attachments/1265754689643872359/1524881932033196173/baje_predator.png",
}

RANKS = [
    ("Rookie IV",   0),   ("Rookie III",   250),  ("Rookie II",   500),  ("Rookie I",   750),
    ("Bronze IV",   1000),("Bronze III",   1500),  ("Bronze II",   2000), ("Bronze I",   2500),
    ("Silver IV",   3000),("Silver III",   3500),  ("Silver II",   4000), ("Silver I",   4500),
    ("Gold IV",     5500),("Gold III",     6250),  ("Gold II",     7000), ("Gold I",     7750),
    ("Platinum IV", 8500),("Platinum III", 9250),  ("Platinum II", 10000),("Platinum I", 11000),
    ("Diamond IV",  12000),("Diamond III", 13000), ("Diamond II",  14000),("Diamond I",  15000),
    ("Master",      16000),
]

# ==========================================================
# Вспомогательные функции
# ==========================================================

def load_panel() -> dict:
    from adm_panel import DATA_FILE
    if DATA_FILE.exists():
        try:
            return json.loads(DATA_FILE.read_text("utf-8"))
        except Exception:
            pass
    return {}


def get_guild_cfg(guild_id) -> dict:
    from adm_panel import DEFAULTS
    d = load_panel()
    cfg = d.get(str(guild_id), {})
    return {**DEFAULTS, **cfg}


def load_users() -> dict:
    if USERS.exists():
        try:
            return json.loads(USERS.read_text("utf-8"))
        except Exception:
            pass
    return {}


def save_users(d: dict):
    USERS.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")


def get_display_name(entry: dict = None, api_data=None):
    entry = entry or {}
    display = (entry.get("display_name") or "").strip()
    if display:
        return display
    ea = (entry.get("ea_name") or "").strip()
    if ea:
        return ea
    if api_data:
        return api_data.get("global", {}).get("name", "?")
    return "?"


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


def get_rank_emoji(rank_name: str) -> str:
    return RANK_EMOJI.get(rank_name, "🏅")


def div_to_roman(div: str) -> str:
    return {"1": "I", "2": "II", "3": "III", "4": "IV"}.get(str(div).strip(), str(div).strip())


def parse_rank(r: dict, rp: int, pred_threshold: int = None):
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
        if pred_threshold is not None:
            needed  = pred_threshold - rp
            pos_str = f" · В топе: **#{ladder_pos}**" if ladder_pos else ""
            next_str = f"**До ранга Predator:** {needed} RP{pos_str}" if needed > 0 else f"Достаточно для Predator!{pos_str}"
        else:
            pos_str  = f"** · В топе:** #{ladder_pos}" if ladder_pos else ""
            next_str = f"Максимальный ранг (кроме Predator){pos_str}"
    else:
        _, next_rp = get_rank_info(rp)
        next_str = f"{next_rp} RP" if next_rp is not None else "Максимальный ранг"
        if api_rank_name and api_rank_div and api_rank_div != "0":
            rank_name = f"{api_rank_name} {div_to_roman(api_rank_div)}"
        elif api_rank_name:
            rank_name = api_rank_name
        else:
            rank_name, _ = get_rank_info(rp)
        tier = api_rank_name if api_rank_name else rank_name.split()[0]

    return rank_name, tier, next_str


def format_rank_str(r: dict, rp: int) -> str:
    api_rank_name = r.get("rankName", "")
    api_rank_div  = str(r.get("rankDiv", "")).strip()
    ladder_pos    = r.get("ladderPosPlatform") or r.get("ladderPos")

    if api_rank_name == "Apex Predator":
        rank_name    = "Apex Predator"
        rank_display = f"Apex Predator (#{ladder_pos} в топе, {rp} RP)" if ladder_pos else f"Apex Predator ({rp} RP)"
    elif api_rank_name == "Master":
        rank_name    = "Master"
        rank_display = f"Master ({rp} RP)"
    elif api_rank_name and api_rank_div and api_rank_div != "0":
        rank_name    = f"{api_rank_name} {div_to_roman(api_rank_div)}"
        rank_display = f"{rank_name} ({rp} RP)"
    else:
        rank_name, _ = get_rank_info(rp)
        rank_display = f"{rank_name} ({rp} RP)"

    emoji = get_rank_emoji(rank_name)
    return f"{emoji} {rank_display}"


async def fetch_predator_threshold() -> int | None:
    now = time.time()
    if PRED_CACHE["data"] and now - PRED_CACHE["ts"] < PRED_TTL:
        return PRED_CACHE["data"]
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(
                "https://api.mozambiquehe.re/predator",
                params={"auth": API_KEY},
                timeout=aiohttp.ClientTimeout(total=5)
            ) as r:
                if r.status != 200:
                    return None
                data = json.loads(await r.text())
                pc   = data.get("RP", {}).get("PC", {})
                val  = pc.get("val") or pc.get("RP") or pc.get("rankScore")
                if val is not None:
                    PRED_CACHE["data"] = int(val)
                    PRED_CACHE["ts"]   = now
                    return int(val)
    except Exception as e:
        log.error(f"[Predator API] {e}")
    return None


async def send_and_delete(interaction, delay=86400, **kwargs):
    msg = await interaction.followup.send(**kwargs)
    async def _delete():
        await asyncio.sleep(delay)
        try:
            await msg.delete()
        except Exception:
            pass
    asyncio.create_task(_delete())


async def check_channel(interaction: discord.Interaction) -> bool:
    cfg     = get_guild_cfg(interaction.guild_id)
    chan_id = cfg.get("rank_channel_id")
    if chan_id is None or interaction.channel_id == int(chan_id):
        return True
    await interaction.response.send_message(
        f"❌ Эта команда работает только в канале <#{chan_id}>", ephemeral=True
    )
    return False


# ==========================================================
# Cog
# ==========================================================

class Rank(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._enabled: dict[int, bool] = {}  # guild_id -> bool
        self.rank_list_updater.start()

    def cog_unload(self):
        self.rank_list_updater.cancel()

    def restart_updater(self):
        """Вызывается из adm_panel при изменении интервала."""
        self.rank_list_updater.restart()

    # -------------------------------------------------------
    # Авто-обновление топ-листа
    # -------------------------------------------------------

    @tasks.loop(seconds=60)
    async def rank_list_updater(self):
        for guild in self.bot.guilds:
            gid = guild.id
            if not self._enabled.get(gid, True):
                continue
            cfg     = get_guild_cfg(gid)
            chan_id = cfg.get("rank_list_channel_id")
            if not chan_id:
                continue
            channel = self.bot.get_channel(int(chan_id))
            if not channel:
                continue
            await self._post_rank_list(channel, gid)

    @rank_list_updater.before_loop
    async def before_updater(self):
        await self.bot.wait_until_ready()

    @rank_list_updater.error
    async def updater_error(self, error):
        log.error(f"[rank_list_updater] {error}")

    async def _post_rank_list(self, channel: discord.TextChannel, guild_id: int):
        d          = load_users()
        gid        = str(guild_id)
        guild_users = [v for v in d.values() if v.get("guild_id") == gid]
        if not guild_users:
            return

        players = []
        for u in guild_users:
            discord_id = u.get("discord_id")
            mention    = f"<@{discord_id}>" if discord_id else u.get("discord_name", "?")
            data       = await self._fetch(uid=u["uid"]) if u.get("uid") else await self._fetch(player=u.get("ea_name"))

            if "error" in data:
                players.append({"mention": mention, "ea_name": u.get("ea_name","?"), "rank_str": "❓ Нет данных", "rp": -1})
            else:
                try:
                    rp      = int(data["global"]["rank"].get("rankScore", 0))
                    r_block = data["global"]["rank"]
                    ea_name = get_display_name(u, data)
                    players.append({"mention": mention, "ea_name": ea_name, "rank_str": format_rank_str(r_block, rp), "rp": rp})
                except Exception:
                    players.append({"mention": mention, "ea_name": u.get("ea_name","?"), "rank_str": "❓ Ошибка", "rp": -1})

        players.sort(key=lambda x: x["rp"], reverse=True)

        lines = [
            f"**#{i}** {p['mention']}\nНик: **{p['ea_name']}**\nРанг: {p['rank_str']}"
            for i, p in enumerate(players, 1)
        ]

        now_msk = datetime.now(MSK).strftime("%d.%m.%Y %H:%M МСК")
        embed   = discord.Embed(title="🏆 Ranked список сервера", description="\n\n".join(lines), color=0x3498db)
        embed.set_footer(text=f"Всего игроков: {len(players)} · Обновлено: {now_msk}")

        try:
            async for msg in channel.history(limit=RANK_LIST_DELETE_LAST):
                try:
                    await msg.delete()
                    await asyncio.sleep(0.5)
                except Exception:
                    pass
        except Exception as e:
            log.warning(f"[rank_list] удаление: {e}")

        try:
            await channel.send(embed=embed)
        except Exception as e:
            log.error(f"[rank_list] отправка: {e}")

    # -------------------------------------------------------
    # Fetch helpers
    # -------------------------------------------------------

    async def _fetch(self, player=None, uid=None):
        key = uid if uid else player
        if key in CACHE and time.time() - CACHE[key][0] < TTL:
            return CACHE[key][1]
        params = {"auth": API_KEY, "platform": "PC"}
        if uid:
            params["uid"] = uid
        else:
            params["player"] = player
        async with aiohttp.ClientSession() as s:
            async with s.get(API_URL, params=params) as r:
                if r.status != 200:
                    return {"error": r.status}
                data = await r.json()
        CACHE[key] = (time.time(), data)
        return data

    async def fetch(self, player=None, uid=None):
        return await self._fetch(player=player, uid=uid)

    def register_user(self, member, guild_id, ea_name: str, uid: str):
        d   = load_users()
        key = f"{member.id}:{guild_id}"
        if key not in d:
            d[key] = {
                "discord_id": str(member.id), "guild_id": str(guild_id),
                "discord_name": member.name, "ea_name": ea_name,
                "display_name": "", "uid": uid,
            }
            save_users(d)

    async def build_embed(self, data, identifier, footer=None):
        g  = data["global"]
        r  = g["rank"]
        rp = int(r.get("rankScore", 0))

        api_rank_name  = r.get("rankName", "")
        pred_threshold = await fetch_predator_threshold() if api_rank_name == "Master" else None
        rank_name, tier, next_str = parse_rank(r, rp, pred_threshold)
        color = COLORS.get(tier, 0x2f3136)

        rt         = data.get("realtime", {})
        is_online  = rt.get("isOnline", 0)
        is_in_game = rt.get("isInGame", 0)
        party_full = rt.get("partyFull", 0)
        online_str = "🟢 Онлайн" if is_online else "🔴 Оффлайн"
        ingame_str = "🎮 В игре" if is_in_game else "🏠 В лобби"
        party_str  = "🔒 Заполнено" if party_full else "🔓 Есть место"

        label = "📈" if tier not in ("Apex Predator", "Master") else "📈"
        next_label = "До следующего ранга:" if tier not in ("Apex Predator", "Master") else ""

        desc = (
            f"🎮 **Ник:** {identifier}\n\n"
            f"⭐ **RP:** {rp}\n\n"
            f"🏆 **Ранг:** {rank_name}\n\n"
            f"📈 {('**' + next_label + '** ') if next_label else ''}{next_str}\n\n"
            f"**Статус:** {online_str}"
        )
        if is_online:
            desc += f" · {ingame_str}\n**Пати:** {party_str}"

        embed = discord.Embed(title="Apex Legends", description=desc, color=color)
        if thumb := RANK_THUMBNAIL.get(tier):
            embed.set_thumbnail(url=thumb)
        if footer:
            embed.set_footer(text=footer)
        return embed

    # -------------------------------------------------------
    # /rank
    # -------------------------------------------------------

    @app_commands.command(name="rank", description="Показать ранг по нику EA")
    async def rank(self, interaction: discord.Interaction, nick: str):
        if not await check_channel(interaction): return
        await interaction.response.defer()
        data = await self.fetch(player=nick)
        if "error" in data:
            m = {404: "Игрок не найден. Попробуй `/rankuid`.", 429: "Лимит API.", 500: "Ошибка API."}
            await send_and_delete(interaction, content="❌ " + m.get(data["error"], f"HTTP {data['error']}"))
            return
        try:
            ea_name = data["global"].get("name", nick)
            uid     = str(data["global"].get("uid", ""))
            self.register_user(interaction.user, interaction.guild_id, ea_name, uid)
            entry     = load_users().get(f"{interaction.user.id}:{interaction.guild_id}", {})
            saved_uid = str(entry.get("uid", "")).strip()
            display   = ((entry.get("display_name") or "").strip() or ea_name) if saved_uid == uid else ea_name
            await send_and_delete(interaction, embed=await self.build_embed(data, display))
        except Exception as ex:
            await send_and_delete(interaction, content=f"⚠ Ошибка: {ex}")

    # -------------------------------------------------------
    # /rankuid
    # -------------------------------------------------------

    @app_commands.command(name="rankuid", description="Показать ранг по числовому UID")
    async def rankuid(self, interaction: discord.Interaction, uid: str):
        if not await check_channel(interaction): return
        await interaction.response.defer()
        if not uid.isdigit():
            await send_and_delete(interaction,
                content="❌ UID должен быть числовым.\n\n1. Зайди на https://apexlegendsstatus.com\n2. Найди профиль по нику\n3. В URL будет `/profile/uid/PC/1234567890`")
            return
        data = await self.fetch(uid=uid)
        if "error" in data:
            m = {404: "Игрок не найден.", 429: "Лимит API.", 500: "Ошибка API."}
            await send_and_delete(interaction, content="❌ " + m.get(data["error"], f"HTTP {data['error']}"))
            return
        try:
            ea_name   = data["global"].get("name", uid)
            self.register_user(interaction.user, interaction.guild_id, ea_name, uid)
            entry     = load_users().get(f"{interaction.user.id}:{interaction.guild_id}", {})
            saved_uid = str(entry.get("uid", "")).strip()
            display   = ((entry.get("display_name") or "").strip() or ea_name) if saved_uid == str(uid) else ea_name
            await send_and_delete(interaction, embed=await self.build_embed(data, display))
        except Exception as ex:
            await send_and_delete(interaction, content=f"⚠ Ошибка: {ex}")

    # -------------------------------------------------------
    # /rankds
    # -------------------------------------------------------

    @app_commands.command(name="rankds", description="Показать ранг пользователя Discord")
    @app_commands.describe(member="Пользователь Discord")
    async def rankds(self, interaction: discord.Interaction, member: discord.Member):
        if not await check_channel(interaction): return
        await interaction.response.defer()
        d     = load_users()
        entry = d.get(f"{member.id}:{interaction.guild_id}")
        if not entry:
            await send_and_delete(interaction, content=f"❌ {member.mention} не привязал Apex аккаунт.\nНужно использовать `/rank` или `/rankuid`.")
            return
        data = await self.fetch(uid=entry["uid"]) if entry.get("uid") else await self.fetch(player=entry.get("ea_name"))
        if "error" in data:
            m = {404: "Игрок не найден.", 429: "Лимит API.", 500: "Ошибка API."}
            await send_and_delete(interaction, content="❌ " + m.get(data["error"], f"HTTP {data['error']}"))
            return
        try:
            dn         = (entry.get("display_name") or "").strip()
            identifier = dn or data["global"].get("name") or get_display_name(entry, data)
            footer     = f"Discord: {member.display_name} ({member.name})"
            await send_and_delete(interaction, embed=await self.build_embed(data, identifier, footer=footer))
        except Exception as ex:
            await send_and_delete(interaction, content=f"⚠ Ошибка: {ex}")

    # -------------------------------------------------------
    # /rank_list_on / off
    # -------------------------------------------------------

    @app_commands.command(name="rank_list_on", description="Включить автообновление топ-листа")
    async def rank_list_on(self, interaction: discord.Interaction):
        from adm_panel import check_admin
        if not await check_admin(interaction): return
        self._enabled[interaction.guild_id] = True
        if not self.rank_list_updater.is_running():
            self.rank_list_updater.start()
        await interaction.response.send_message("✅ Автообновление топ-листа **включено**.", ephemeral=True)

    @app_commands.command(name="rank_list_off", description="Выключить автообновление топ-листа")
    async def rank_list_off(self, interaction: discord.Interaction):
        from adm_panel import check_admin
        if not await check_admin(interaction): return
        self._enabled[interaction.guild_id] = False
        await interaction.response.send_message("⛔ Автообновление топ-листа **выключено**.", ephemeral=True)

    # -------------------------------------------------------
    # /unrank
    # -------------------------------------------------------

    @app_commands.command(name="unrank", description="Удалить свой Apex аккаунт из списка")
    async def unrank(self, interaction: discord.Interaction):
        d   = load_users()
        key = f"{interaction.user.id}:{interaction.guild_id}"
        if key not in d:
            await interaction.response.send_message("❌ Твой аккаунт не привязан.", ephemeral=True)
            return
        ea_name = d[key].get("ea_name", "?")
        del d[key]
        save_users(d)
        await interaction.response.send_message(f"✅ Аккаунт **{ea_name}** удалён.", ephemeral=True)


async def setup(bot):
    await bot.add_cog(Rank(bot))
