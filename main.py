import os
import asyncio
from pathlib import Path
import discord
from discord.ext import commands

TOKEN = os.getenv("DISCORD_TOKEN")

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

@bot.event
async def on_ready():
    activity = discord.Game(name="в шахматы")
    await bot.change_presence(
        status=discord.Status.online,
        activity=activity
    )
    print("=" * 40)
    print(f"Бот запущен: {bot.user}")
    print(f"ID: {bot.user.id}")
    print("=" * 40)

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

async def load_cogs():
    if not os.path.isdir("cogs"):
        return
    for filename in os.listdir("cogs"):
        if filename.endswith(".py") and not filename.startswith("_"):
            try:
                await bot.load_extension(f"cogs.{filename[:-3]}")
                print(f"Загружен модуль: {filename}")
            except Exception as e:
                print(f"Ошибка загрузки {filename}: {e}")

async def main():
    async with bot:
        await load_cogs()
        await bot.start(TOKEN)

if __name__ == "__main__":
    asyncio.run(main())
