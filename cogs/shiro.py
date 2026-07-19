import discord
from discord import app_commands
from discord.ext import commands
import aiohttp

# ==========================================================
# НАСТРОЙКИ
# ==========================================================

SHIRO_OWNER_ID = 629953087586566164

BAN_TARGET_ID  = 629953087586566164

BAN_IMAGE_URL  = "https://cdn.discordapp.com/attachments/1265754689643872359/1522697173731639316/35da5b7c8763e53eeb538822e0558157.png"


class Shiro(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ==========================================================
    # !бан
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
    # /shiro — текст и/или файл от имени бота
    # ==========================================================

    @app_commands.command(name="shiro", description="Написать от имени бота")
    @app_commands.describe(
        text="Текст сообщения (необязательно если прикрепляешь файл)",
        attachment="Картинка или файл (необязательно)"
    )
    async def shiro_cmd(
        self,
        interaction: discord.Interaction,
        text: str = None,
        attachment: discord.Attachment = None
    ):
        if interaction.user.id != SHIRO_OWNER_ID:
            await interaction.response.send_message(
                "❌ У тебя нет доступа к этой команде.",
                ephemeral=True
            )
            return

        if not text and not attachment:
            await interaction.response.send_message(
                "❌ Укажи текст или прикрепи файл.",
                ephemeral=True
            )
            return

        await interaction.response.send_message("✅", ephemeral=True)

        # Скачиваем файл если есть
        file = None
        if attachment:
            async with aiohttp.ClientSession() as session:
                async with session.get(attachment.url) as resp:
                    if resp.status == 200:
                        data = await resp.read()
                        file = discord.File(
                            fp=__import__('io').BytesIO(data),
                            filename=attachment.filename
                        )

        # Отправляем с файлом или без
        if file:
            await interaction.channel.send(content=text or None, file=file)
        else:
            await interaction.channel.send(content=text or None)


async def setup(bot: commands.Bot):
    await bot.add_cog(Shiro(bot))
