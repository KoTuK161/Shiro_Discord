import json
import logging
from pathlib import Path
import discord
from discord.ext import commands

log = logging.getLogger(__name__)

# ==========================================================
# Путь к конфигу
# ==========================================================

CONFIG_PATH = Path("/app/data/roles_config.json")


# ==========================================================
# Загрузка конфига
# ==========================================================

def load_config() -> dict:
    if CONFIG_PATH.exists():
        try:
            return json.loads(CONFIG_PATH.read_text("utf-8"))
        except Exception as e:
            log.error(f"Ошибка чтения roles_config.json: {e}")
    return {}


def get_guild_cfg(guild_id: int) -> dict | None:
    """Возвращает конфиг сервера или None если не найден."""
    cfg = load_config()
    return cfg.get(str(guild_id))


# ==========================================================
# Вспомогательные функции
# ==========================================================

def parse_emoji(emoji_str: str, guild: discord.Guild):
    """Возвращает объект эмодзи для кастомных или строку для юникод."""
    if emoji_str.startswith("<"):
        emoji_id = int(emoji_str.split(":")[-1].rstrip(">"))
        return discord.utils.get(guild.emojis, id=emoji_id)
    return emoji_str


def emoji_matches(payload_emoji: discord.PartialEmoji, role_map_key: str) -> bool:
    """Сравнивает эмодзи из payload с ключом в конфиге."""
    if role_map_key.startswith("<"):
        emoji_id = int(role_map_key.split(":")[-1].rstrip(">"))
        return payload_emoji.id == emoji_id
    return str(payload_emoji) == role_map_key


# ==========================================================
# Cog
# ==========================================================

class Roles(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_ready(self):
        """При запуске бота добавляем реакции на сообщения из конфига."""
        cfg = load_config()

        for guild in self.bot.guilds:
            guild_cfg = cfg.get(str(guild.id))
            if not guild_cfg:
                continue

            message_id = guild_cfg.get("message_id")
            role_map   = guild_cfg.get("roles", {})

            if not message_id or not role_map:
                continue

            for channel in guild.text_channels:
                try:
                    message = await channel.fetch_message(message_id)
                    existing_ids = {r.emoji.id for r in message.reactions if hasattr(r.emoji, "id")}
                    existing_str = {str(r.emoji) for r in message.reactions}

                    for emoji_key in role_map:
                        if emoji_key.startswith("<"):
                            emoji_id = int(emoji_key.split(":")[-1].rstrip(">"))
                            if emoji_id in existing_ids:
                                continue
                            emoji_obj = parse_emoji(emoji_key, guild)
                            if emoji_obj:
                                await message.add_reaction(emoji_obj)
                        else:
                            if emoji_key not in existing_str:
                                await message.add_reaction(emoji_key)
                    break  # нашли сообщение — дальше не ищем
                except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                    continue

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        if payload.user_id == self.bot.user.id:
            return

        log.info(f"[reaction_add] guild={payload.guild_id} msg={payload.message_id} emoji={payload.emoji} user={payload.user_id}")

        guild_cfg = get_guild_cfg(payload.guild_id)
        if not guild_cfg:
            log.warning(f"[reaction_add] Нет конфига для сервера {payload.guild_id}")
            return

        expected_msg_id = guild_cfg.get("message_id")
        if payload.message_id != expected_msg_id:
            log.debug(f"[reaction_add] Сообщение {payload.message_id} != ожидаемого {expected_msg_id} — пропуск")
            return

        role_map = guild_cfg.get("roles", {})
        log.info(f"[reaction_add] role_map={list(role_map.keys())}")

        matched_key = None
        for key in role_map:
            if emoji_matches(payload.emoji, key):
                matched_key = key
                break

        log.info(f"[reaction_add] matched_key={matched_key}")

        guild = self.bot.get_guild(payload.guild_id)
        if not guild:
            log.warning(f"[reaction_add] Сервер {payload.guild_id} не найден")
            return

        # Эмодзи не из конфига — убираем реакцию
        if matched_key is None:
            log.warning(f"[reaction_add] Эмодзи {payload.emoji} не найден в конфиге — удаляем реакцию")
            channel = guild.get_channel(payload.channel_id)
            if not channel:
                return
            try:
                message = await channel.fetch_message(payload.message_id)
                user = guild.get_member(payload.user_id)
                if user:
                    await message.remove_reaction(payload.emoji, user)
            except (discord.Forbidden, discord.HTTPException):
                pass
            return

        role_id = role_map[matched_key]
        role = guild.get_role(role_id)
        member = guild.get_member(payload.user_id)
        log.info(f"[reaction_add] role_id={role_id} role={role} member={member}")

        if role is None:
            log.warning(f"[reaction_add] Роль {role_id} не найдена на сервере {guild.name}")
            return
        if member is None:
            log.warning(f"[reaction_add] Участник {payload.user_id} не найден на сервере {guild.name}")
            return

        try:
            await member.add_roles(role, reason="Reaction role")
            log.info(f"[reaction_add] Роль {role.name} выдана {member.name}")
        except discord.Forbidden:
            log.warning(f"[reaction_add] Нет прав выдать роль {role.name} на сервере {guild.name}")

    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, payload: discord.RawReactionActionEvent):
        if payload.user_id == self.bot.user.id:
            return

        guild_cfg = get_guild_cfg(payload.guild_id)
        if not guild_cfg:
            return

        if payload.message_id != guild_cfg.get("message_id"):
            return

        role_map = guild_cfg.get("roles", {})

        matched_key = None
        for key in role_map:
            if emoji_matches(payload.emoji, key):
                matched_key = key
                break

        if matched_key is None:
            return

        guild = self.bot.get_guild(payload.guild_id)
        if not guild:
            return

        role = guild.get_role(role_map[matched_key])
        member = guild.get_member(payload.user_id)
        if role and member:
            try:
                await member.remove_roles(role, reason="Reaction role removed")
            except discord.Forbidden:
                log.warning(f"Нет прав снять роль {role.name} на сервере {guild.name}")


async def setup(bot: commands.Bot):
    await bot.add_cog(Roles(bot))
