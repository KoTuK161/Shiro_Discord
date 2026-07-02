import os
import asyncio
import logging
from pathlib import Path
import discord
from discord.ext import commands

# ==========================================================
# Логирование
# ==========================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("/app/bot.log", encoding="utf-8"),
        logging.StreamHandler()
    ]
)
log = logging.getLogger(__name__)

# ==========================================================
# Настройки
# ==========================================================

TOKEN = os.getenv("DISCORD_TOKEN")
DEBUG = os.getenv("DEBUG", "False") == "True"
GUILD_ID = int(os.getenv("GUILD_ID", "0"))

log.info(f"DEBUG = {DEBUG}")
log.info(f"GUILD_ID = {GUILD_ID}")

BASE_DIR = Path(__file__).parent
IMAGE_DIR = BASE_DIR / "images"

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(
    command_prefix="!",
    intents=intents,
    help_command=None
)

# ==========================================================
# События
# ==========================================================

@bot.event
async def on_ready():
    log.info("=" * 60)
    log.info(f"Bot User: {bot.user}")
    log.info(f"Application ID: {bot.application_id}")
    log.info(f"Guild ID: {GUILD_ID}")
    log.info(f"DEBUG: {DEBUG}")

    log.info("Команды в tree ДО sync:")
    for cmd in bot.tree.get_commands():
        log.info(f" - {cmd.name}")

    if DEBUG:
        guild = discord.Object(id=GUILD_ID)
        bot.tree.clear_commands(guild=None)
        await bot.tree.sync()
        bot.tree.copy_global_to(guild=guild)
        synced = await bot.tree.sync(guild=guild)
    else:
        bot.tree.clear_commands(guild=discord.Object(id=GUILD_ID))
        await bot.tree.sync(guild=discord.Object(id=GUILD_ID))
        synced = await bot.tree.sync()

    log.info("Команды, которые Discord принял:")
    for cmd in synced:
        log.info(f" - {cmd.name}")
    log.info(f"Всего синхронизировано: {len(synced)}")

    await bot.change_presence(
        status=discord.Status.online,
        activity=discord.Game("Играет в шахматы")
    )
    log.info("=" * 60)


@bot.event
async def on_message(message):
    if message.author.bot:
        return
    await bot.process_commands(message)
    text = message.content.lower()

    words_png1 = ["заебал", "надоел"]
    words_png2 = ["мило", "красиво", "кавайно"]
    words_png3 = ["господи", "боже"]
    words_png4 = ["бесит", "бесишь", "бесят"]
    words_png5 = ["поздравл"]
    words_png6 = ["крутой", "крутая"]

    words_gif1 = ["широ"]
    words_gif2 = ["панцу", "pantsu"]
    words_gif3 = ["мягк", "упруг"]
    words_gif4 = ["приятного", "аппетита"]

    if any(word in text for word in words_png1):
        await message.reply(
            "Ну серьёзно..)",
            file=discord.File(IMAGE_DIR / "img1.png")
        )
    elif any(word in text for word in words_png2):
        await message.reply(
            "Мило 😍",
            file=discord.File(IMAGE_DIR / "img2.png")
        )
    elif any(word in text for word in words_png3):
        await message.reply(
            "Давайте все вместе помолимся за наше духовное спокойствие 😇",
            file=discord.File(IMAGE_DIR / "img3.png")
        )
    elif any(word in text for word in words_png4):
        await message.reply(
            "Не беситесь 👿",
            file=discord.File(IMAGE_DIR / "img4.png")
        )
    elif any(word in text for word in words_png5):
        await message.reply(
            "Присоединяюсь к поздравлениям! 🎉",
            file=discord.File(IMAGE_DIR / "img5.png")
        )
    elif any(word in text for word in words_png6):
        await message.reply(
            "Даже круче, чем я?",
            file=discord.File(IMAGE_DIR / "img6.png")
        )
    elif any(word in text for word in words_gif1):
        await message.reply(
            "Ну кто меня разбудил, чего хотели... 😴",
            file=discord.File(IMAGE_DIR / "gif1.gif")
        )
    elif any(word in text for word in words_gif2):
        await message.reply(
            "Да ну Вас, извращенцы! 😒",
            file=discord.File(IMAGE_DIR / "gif2.gif")
        )
    elif any(word in text for word in words_gif3):
        await message.reply(
            "М-м-мягкие 😊",
            file=discord.File(IMAGE_DIR / "gif3.gif")
        )
    elif any(word in text for word in words_gif4):
        await message.reply(
            "Приятного аппетита! 🍩",
            file=discord.File(IMAGE_DIR / "gif4.gif")
        )

# ==========================================================
# Загрузка Cogs
# ==========================================================

async def load_cogs():
    if not os.path.isdir("cogs"):
        return
    for filename in os.listdir("cogs"):
        if filename.endswith(".py") and not filename.startswith("_"):
            try:
                await bot.load_extension(f"cogs.{filename[:-3]}")
                log.info(f"Загружен модуль: {filename}")
            except Exception as e:
                log.error(f"Ошибка загрузки {filename}: {e}")

# ==========================================================
# Запуск
# ==========================================================

async def main():
    async with bot:
        await load_cogs()
        await bot.start(TOKEN)

if __name__ == "__main__":
    asyncio.run(main())
