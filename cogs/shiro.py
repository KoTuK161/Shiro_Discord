import discord
from discord import app_commands
from discord.ext import commands

# ==========================================================
# ID пользователя @jiehubblu_kot — единственный владелец /shiro
# Замени на реальный Discord ID пользователя
# ==========================================================
SHIRO_OWNER_ID = 629953087586566164  # <-- вставь сюда ID пользователя

# ID упоминаемого пользователя в команде !бан
BAN_TARGET_ID = 629953087586566164   # <-- вставь сюда ID @jiehubblu_kot

# Ссылка на изображение для команды !бан
BAN_IMAGE_URL = "https://cdn.discordapp.com/attachments/1265754689643872359/1522697173731639316/35da5b7c8763e53eeb538822e0558157.png"


class Shiro(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ==========================================================
    # !бан — префиксная команда
    # ==========================================================

    @commands.command(name="бан")
    async def ban_cmd(self, ctx: commands.Context):
        embed = discord.Embed(
            description=f"Братик <@{BAN_TARGET_ID}>, дай мне разрешение и ты больше не увидишь его в живых!",
            color=0xff4444
        )
        embed.set_image(url=BAN_IMAGE_URL)
        await ctx.send(embed=embed)

    # ==========================================================
    # /shiro {text} — слэш-команда только для владельца
    # ==========================================================

    @app_commands.command(name="shiro", description="Написать от имени бота")
    @app_commands.describe(text="Текст, который напишет бот")
    async def shiro_cmd(self, interaction: discord.Interaction, text: str):
        # Проверяем ID пользователя — жёстко, без привязки к роли
        if interaction.user.id != SHIRO_OWNER_ID:
            await interaction.response.send_message(
                "❌ У тебя нет доступа к этой команде.",
                ephemeral=True  # видит только сам пользователь
            )
            return

        # Отправляем текст от имени бота в тот же канал
        await interaction.channel.send(text)

        # Подтверждение — видит только вызвавший, сразу исчезает
        await interaction.response.send_message("✅", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Shiro(bot))
