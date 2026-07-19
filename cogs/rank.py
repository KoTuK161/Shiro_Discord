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
MAP_API_URL = "https://api.mozambiquehe.re/maprotation"
BASE    = Path(__file__).resolve().parent.parent
DATA    = BASE / "data"
DATA.mkdir(exist_ok=True)
USERS   = DATA / "apex_users.json"
CACHE   = {}
MAP_CACHE = {"data": None, "ts": 0}
TTL     = 60
MAP_CACHE_TTL = 60
PRED_CACHE = {"data": None, "ts": 0}
PRED_TTL   = 300
MSK = timezone(timedelta(hours=3))

RANK_LIST_DELETE_LAST = 10

# Ротация карт
MAPS = ["E-District", "Storm Point", "World's Edge"]
MAP_EMOJI = {
    "E-District":   "🏙️",
    "Storm Point":  "⛈️",
    "World's Edge": "🌋",
    "Kings Canyon": "🏜️",
    "Olympus":      "🌿",
    "Broken Moon":  "🌙",
}
MAP_ROTATION = timedelta(hours=4, minutes=30)
MAP_SCHEDULE_SLOTS = 6

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
    "Rookie": 0x808080, "Bronze": 0xcd7f32, "Silver": 0xc0c0c0,
    "Gold": 0xffd700, "Platinum": 0x00c8c8, "Diamond": 0x4aa3ff,
    "Master": 0x9b59b6, "Apex Predator": 0xff0000,
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

ADM_PANEL_PATH = Path("/app/data/adm_panel.json")
ADM_DEFAULTS = {
    "rank_channel_id":      None,
    "map_channel_id":       None,
    "rank_list_channel_id": None,
    "rank_list_delay":      900,
    "shiro_react":          True,
}
SUPERADMIN_ID = 629953087586566164

# ==========================================================
# Утилиты
# ==========================================================

def load_panel() -> dict:
    if ADM_PANEL_PATH.exists():
        try:
            return json.loads(ADM_PANEL_PATH.read_text("utf-8"))
        except Exception:
            pass
    return {}


def get_guild_cfg(guild_id) -> dict:
    d = load_panel()
    cfg = d.get(str(guild_id), {})
    return {**ADM_DEFAULTS, **cfg}


def is_admin(user_id: int, guild_id: int) -> bool:
    if user_id == SUPERADMIN_ID:
        return True
    d = load_panel()
    admins = d.get(str(guild_id), {}).get("admins", [])
    return user_id in admins


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
            needed   = pred_threshold - rp
            pos_str  = f" · В топе: **#{ladder_pos}**" if ladder_pos else ""
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


async def fetch_map_rotation() -> dict | None:
    now = time.time()
    if MAP_CACHE["data"] and now - MAP_CACHE["ts"] < MAP_CACHE_TTL:
        return MAP_CACHE["data"]
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(
                MAP_API_URL,
                params={"auth": API_KEY, "version": 2},
                timeout=aiohttp.ClientTimeout(total=10)
            ) as r:
                if r.status != 200:
                    return None
                data = await r.json()
                MAP_CACHE["data"] = data
                MAP_CACHE["ts"]   = now
                return data
    except Exception:
        return None


def round_to_half_hour(dt: datetime) -> datetime:
    """Округляет время до ближайших :00 или :30."""
    minute = dt.minute
    if minute < 15:
        # Округляем вниз до :00
        return dt.replace(minute=0, second=0, microsecond=0)
    elif minute < 45:
        # Округляем до :30
        return dt.replace(minute=30, second=0, microsecond=0)
    else:
        # Округляем вверх до следующего :00
        return (dt + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)


def build_map_schedule(current_name: str, slot_end: datetime) -> str:
    idx = MAPS.index(current_name) if current_name in MAPS else -1
    lines = []
    for i in range(1, MAP_SCHEDULE_SLOTS + 1):
        future_name  = MAPS[(idx + i) % len(MAPS)]
        future_start = round_to_half_hour(slot_end + MAP_ROTATION * (i - 1))
        emoji = MAP_EMOJI.get(future_name, "🗺️")
        lines.append(f"{future_start.strftime('%H:%M %d.%m')} — {emoji} {future_name}")
    return "\n".join(lines)


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
        self.bot  = bot
        self._enabled: dict[int, bool] = {}
        self._loop_task: asyncio.Task | None = None

    def cog_load(self):
        self._loop_task = asyncio.create_task(self._run_rank_list_loop())

    def cog_unload(self):
        if self._loop_task:
            self._loop_task.cancel()

    # -------------------------------------------------------
    # Авто-обновление топ-листа
    # -------------------------------------------------------

    async def _run_rank_list_loop(self):
        await self.bot.wait_until_ready()
        last_post: dict[int, float] = {}
        while not self.bot.is_closed():
            for guild in self.bot.guilds:
                gid = guild.id
                if not self._enabled.get(gid, True):
                    continue
                cfg     = get_guild_cfg(gid)
                chan_id = cfg.get("rank_list_channel_id")
                if not chan_id:
                    continue
                delay = int(cfg.get("rank_list_delay") or 900)
                now   = time.time()
                if now - last_post.get(gid, 0) < delay:
                    continue
                channel = self.bot.get_channel(int(chan_id))
                if not channel:
                    continue
                try:
                    await self._post_rank_list(channel, gid)
                    last_post[gid] = time.time()
                except Exception as e:
                    log.error(f"[rank_list_loop] {e}")
            await asyncio.sleep(30)

    async def _post_rank_list(self, channel: discord.TextChannel, guild_id: int):
        d           = load_users()
        gid         = str(guild_id)
        guild_users = [v for v in d.values() if v.get("guild_id") == gid]

        # Получаем ротацию карт
        map_data     = await fetch_map_rotation()
        map_section  = ""
        if map_data:
            br = map_data.get("ranked", {})
            current      = br.get("current", {})
            current_name = current.get("map", "Неизвестно")
            remaining_sec = current.get("remainingMins", 0) * 60
            h, rem = divmod(max(remaining_sec, 0), 3600)
            m, s   = divmod(rem, 60)
            time_str = f"{h}ч {m:02d}м {s:02d}с" if h > 0 else f"{m}м {s:02d}с"
            slot_end = datetime.now(MSK) + timedelta(seconds=remaining_sec)
            schedule = build_map_schedule(current_name, slot_end)
            cur_emoji = MAP_EMOJI.get(current_name, "🗺️")
            map_section = (
                f"**🗺️ Текущая карта:** {cur_emoji} {current_name}\n"
                f"**⏱️ До смены:** {time_str}\n\n"
                f"**📅 Расписание:**\n```{schedule}```"
            )

        if not guild_users:
            if map_section:
                now_msk = datetime.now(MSK).strftime("%d.%m.%Y %H:%M МСК")
                embed = discord.Embed(
                    title="🗺️ Ротация карт Apex Legends (Ranked)",
                    description=map_section,
                    color=0x3498db
                )
                embed.set_footer(text=f"Обновлено: {now_msk}")
                try:
                    async for msg in channel.history(limit=RANK_LIST_DELETE_LAST):
                        try:
                            await msg.delete()
                            await asyncio.sleep(0.3)
                        except Exception:
                            pass
                except Exception:
                    pass
                await channel.send(embed=embed)
            return

        # Строим топ игроков
        players = []
        for u in guild_users:
            discord_id = u.get("discord_id")
            mention    = f"<@{discord_id}>" if discord_id else u.get("discord_name", "?")
            data       = await self._fetch(uid=u["uid"]) if u.get("uid") else await self._fetch(player=u.get("ea_name"))

            if "error" in data:
                players.append({"mention": mention, "ea_name": u.get("ea_name", "?"), "rank_str": "❓ Нет данных", "rp": -1})
            else:
                try:
                    rp      = int(data["global"]["rank"].get("rankScore", 0))
                    r_block = data["global"]["rank"]
                    ea_name = get_display_name(u, data)
                    players.append({"mention": mention, "ea_name": ea_name, "rank_str": format_rank_str(r_block, rp), "rp": rp})
                except Exception:
                    players.append({"mention": mention, "ea_name": u.get("ea_name", "?"), "rank_str": "❓ Ошибка", "rp": -1})

        players.sort(key=lambda x: x["rp"], reverse=True)

        rank_lines = [
            f"**#{i}** {p['mention']}\nНик: **{p['ea_name']}**\nРанг: {p['rank_str']}"
            for i, p in enumerate(players, 1)
        ]

        now_msk = datetime.now(MSK).strftime("%d.%m.%Y %H:%M МСК")

        # Один embed: топ + карты
        description = "\n\n".join(rank_lines)
        if map_section:
            description += f"\n\n{'─' * 30}\n\n{map_section}"

        embed = discord.Embed(
            title="🏆 Ranked список сервера",
            description=description,
            color=0x3498db
        )
        embed.set_footer(text=f"Всего игроков: {len(players)} · Обновлено: {now_msk}")

        try:
            async for msg in channel.history(limit=RANK_LIST_DELETE_LAST):
                try:
                    await msg.delete()
                    await asyncio.sleep(0.3)
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
            ea_name   = data["global"].get("name", nick)
            uid       = str(data["global"].get("uid", ""))
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
                content="❌ UID должен быть числовым EA-идентификатором.\n\n1. Зайди на https://apexlegendsstatus.com\n2. Найди профиль по нику\n3. В URL будет `/profile/uid/PC/1234567890`")
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
        if not is_admin(interaction.user.id, interaction.guild_id):
            await interaction.response.send_message("❌ У тебя нет доступа.", ephemeral=True)
            return
        self._enabled[interaction.guild_id] = True
        if self._loop_task is None or self._loop_task.done():
            self._loop_task = asyncio.create_task(self._run_rank_list_loop())
        await interaction.response.send_message("✅ Автообновление топ-листа **включено**.", ephemeral=True)

    @app_commands.command(name="rank_list_off", description="Выключить автообновление топ-листа")
    async def rank_list_off(self, interaction: discord.Interaction):
        if not is_admin(interaction.user.id, interaction.guild_id):
            await interaction.response.send_message("❌ У тебя нет доступа.", ephemeral=True)
            return
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
