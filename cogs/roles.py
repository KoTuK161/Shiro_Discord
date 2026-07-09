import discord
from discord.ext import commands

# ==========================================================
# НАСТРОЙКИ
# ==========================================================

ROLE_MESSAGE_ID = 1524606476298092614

ROLE_MAP = {
    "<:Apex:1524609710089703485>": 1524612216983257088,
    "<:cs:1524611072391119000>":   1524612470440988702,
}

# ==========================================================
# Дальше — логика, редактировать не нужно
# ==========================================================

def parse_emoji(emoji_str: str, guild: discord.Guild):
    """Возвращает объект эмодзи для кастомных или строку для юникод."""
    if emoji_str.startswith("<"):
        emoji_id = int(emoji_str.split(":")[-1].rstrip(">"))
        return discord.utils.get(guild.emojis, id=emoji_id)
    return emoji_str


def emoji_matches(payload_emoji: discord.PartialEmoji, role_map_key: str) -> bool:
    """Сравнивает эмодзи из payload с ключом в ROLE_MAP."""
    if role_map_key.startswith("<"):
        emoji_id = int(role_map_key.split(":")[-1].rstrip(">"))
        return payload_emoji.id == emoji_id
    return str(payload_emoji) == role_map_key


class Roles(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_ready(self):
        """При запуске бота добавляем реакции на сообщение если их нет."""
        for guild in self.bot.guilds:
            for channel in guild.text_channels:
                try:
                    message = await channel.fetch_message(ROLE_MESSAGE_ID)
                    existing_ids = {r.emoji.id for r in message.reactions if hasattr(r.emoji, 'id')}
                    existing_str = {str(r.emoji) for r in message.reactions}

                    for emoji_key in ROLE_MAP:
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
                    return
                except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                    continue

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        if payload.message_id != ROLE_MESSAGE_ID:
            return
        if payload.user_id == self.bot.user.id:
            return

        matched_key = None
        for key in ROLE_MAP:
            if emoji_matches(payload.emoji, key):
                matched_key = key
                break

        if matched_key is None:
            guild = self.bot.get_guild(payload.guild_id)
            if not guild:
                return
            channel = guild.get_channel(payload.channel_id)
            if not channel:
                return
            try:
                message = await channel.fetch_message(ROLE_MESSAGE_ID)
                user = guild.get_member(payload.user_id)
                if user:
                    await message.remove_reaction(payload.emoji, user)
            except (discord.Forbidden, discord.HTTPException):
                pass
            return

        guild = self.bot.get_guild(payload.guild_id)
        if not guild:
            return
        role = guild.get_role(ROLE_MAP[matched_key])
        member = guild.get_member(payload.user_id)
        if role and member:
            try:
                await member.add_roles(role, reason="Reaction role")
            except discord.Forbidden:
                pass

    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, payload: discord.RawReactionActionEvent):
        if payload.message_id != ROLE_MESSAGE_ID:
            return
        if payload.user_id == self.bot.user.id:
            return

        matched_key = None
        for key in ROLE_MAP:
            if emoji_matches(payload.emoji, key):
                matched_key = key
                break

        if matched_key is None:
            return

        guild = self.bot.get_guild(payload.guild_id)
        if not guild:
            return
        role = guild.get_role(ROLE_MAP[matched_key])
        member = guild.get_member(payload.user_id)
        if role and member:
            try:
                await member.remove_roles(role, reason="Reaction role removed")
            except discord.Forbidden:
                pass


async def setup(bot: commands.Bot):
    await bot.add_cog(Roles(bot))
