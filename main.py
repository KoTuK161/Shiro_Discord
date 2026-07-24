import os
import json
import asyncio
import logging
from pathlib import Path
import discord
from discord.ext import commands, tasks

# ==========================================================
# Логирование
# ==========================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("/app/data/bot.log", encoding="utf-8"),
        logging.StreamHandler()
    ]
)
log = logging.getLogger(__name__)

# ==========================================================
# Настройки
# ==========================================================

TOKEN          = os.getenv("DISCORD_TOKEN")
DEBUG          = os.getenv("DEBUG", "False") == "True"
GUILD_ID       = int(os.getenv("GUILD_ID", "0"))
VOICE_CHANNEL_ID = int(os.getenv("VOICE_CHANNEL_ID", "0"))  # ID голосового канала

log.info(f"DEBUG = {DEBUG}")
log.info(f"GUILD_ID = {GUILD_ID}")
log.info(f"VOICE_CHANNEL_ID = {VOICE_CHANNEL_ID}")

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(
    command_prefix="!",
    intents=intents,
    help_command=None
)

# ==========================================================
# Ссылки на изображения
# ==========================================================

IMAGES = {
    "img1": "https://cdn.discordapp.com/attachments/1265754689643872359/1265754752210440255/BsP0LMGEe1M.jpg",
    "img2": "https://cdn.discordapp.com/attachments/1265754689643872359/1265800274698829835/no-game-no-life-shiro-volosy.webp",
    "img3": "https://cdn.discordapp.com/attachments/1265754689643872359/1265800301084934286/b185d6126ad720a7.jpg",
    "img4": "https://cdn.discordapp.com/attachments/1265754689643872359/1265803498851799132/1663368378_52-mykaleidoscope-ru-p-zloi-stikmen-emotsii-57.png",
    "img5": "https://cdn.discordapp.com/attachments/1265754689643872359/1265804190744186912/b65410344f0d9f9efe9b4267fba8112a.png",
    "img6": "https://cdn.discordapp.com/attachments/1265754689643872359/1265811826461904967/portada_no-game-no-life-11.jpg",
    "gif1": "https://cdn.discordapp.com/attachments/1265811455308070973/1265811764067696720/1.gif",
    "gif2": "https://cdn.discordapp.com/attachments/1265811455308070973/1265811696174370907/c18d43f5c2522738241e5ca0355c676b60b272e7_hq.gif",
    "gif3": "https://cdn.discordapp.com/attachments/1265811455308070973/1265811748317954110/5ac3cc6d4138136c.gif",
    "gif4": "https://cdn.discordapp.com/attachments/1265811455308070973/1265811773374599261/68747470733a2f2f73332e616d617a6f6e6177732e636f6d2f776174747061642d6d656469612d736572766963652f53746f7279496d6167652f4445325a567653663555754b31773d3d2d37322e313632323933373937306531333638393537373937333432383732302e676966.gif",
}

# ==========================================================
# Голосовой канал — фоновая задача
# ==========================================================

@tasks.loop(seconds=30)
async def voice_keep_alive():
    if VOICE_CHANNEL_ID == 0:
        return

    # Ищем канал только среди серверов, где он есть
    # get_channel вернёт None если канала нет ни на одном сервере бота
    channel = bot.get_channel(VOICE_CHANNEL_ID)
    if channel is None:
        # Канала с таким ID нет ни на одном из серверов бота — ничего не делаем
        return

    if not isinstance(channel, discord.VoiceChannel):
        log.warning(f"Канал {VOICE_CHANNEL_ID} существует, но не является голосовым.")
        return

    guild = channel.guild
    vc = guild.voice_client  # голосовое подключение именно на этом сервере

    if vc and vc.is_connected():
        if vc.channel.id == VOICE_CHANNEL_ID:
            # Уже в нужном канале — всё хорошо
            return
        else:
            # Подключён к другому каналу на том же сервере — переходим
            log.info(f"Перехожу в канал {channel.name} ({VOICE_CHANNEL_ID})")
            await vc.move_to(channel)
    else:
        # Не подключён — заходим
        log.info(f"Подключаюсь к голосовому каналу {channel.name} ({VOICE_CHANNEL_ID})")
        await channel.connect() #(self_deaf=True)  # бот будет с заглушёнными ушами

@voice_keep_alive.before_loop
async def before_voice_keep_alive():
    await bot.wait_until_ready()

@voice_keep_alive.error
async def voice_keep_alive_error(error):
    log.error(f"Ошибка в voice_keep_alive: {error}")

# ==========================================================
# Флаг — синхронизация команд выполняется только один раз
# за жизнь процесса, чтобы не выжигать rate-limit Discord
# при каждом reconnect/on_ready
# ==========================================================

_synced_once = False

# ==========================================================
# События
# ==========================================================


def get_shiro_react(guild_id) -> bool:
    """Проверяет включена ли реакция бота на слова для данного сервера."""
    try:
        from pathlib import Path
        f = Path("/app/data/adm_panel.json")
        if f.exists():
            d = json.loads(f.read_text("utf-8"))
            cfg = d.get(str(guild_id), {})
            return cfg.get("shiro_react", True)
    except Exception:
        pass
    return True

@bot.event
async def on_ready():
    global _synced_once
    log.info("=" * 60)
    log.info(f"Bot User: {bot.user}")
    log.info(f"Application ID: {bot.application_id}")
    log.info(f"Guild ID: {GUILD_ID}")
    log.info(f"DEBUG: {DEBUG}")

    # ----------------------------------------------------------
    # Синхронизация команд — только один раз за жизнь процесса.
    # При reconnect'ах on_ready вызывается повторно, но sync мы
    # уже не трогаем — иначе Discord выдаёт rate-limit и весь
    # блок зависает, не давая выполниться presence и voice.
    # asyncio.wait_for ограничивает ожидание 20 сек на запрос —
    # если Discord тормозит, мы идём дальше, а не висим вечно.
    # ----------------------------------------------------------
    if not _synced_once:
        log.info("Команды в tree ДО sync:")
        for cmd in bot.tree.get_commands():
            log.info(f" - {cmd.name}")

        try:
            if DEBUG:
                # В режиме DEBUG сначала чистим guild-команды, чтобы
                # изменения появлялись мгновенно (guild sync — моментальный)
                dobj = discord.Object(id=GUILD_ID)
                bot.tree.clear_commands(guild=dobj)
                await asyncio.wait_for(bot.tree.sync(guild=dobj), timeout=20)
                log.info(f"Guild-sync выполнен для {GUILD_ID}")

            # Глобальная синхронизация (появляется у всех серверов за ~1 час)
            synced = await asyncio.wait_for(bot.tree.sync(), timeout=20)
            log.info("Команды, которые Discord принял:")
            for cmd in synced:
                log.info(f" - {cmd.name}")
            log.info(f"Всего синхронизировано глобально: {len(synced)}")

            # Принудительно копируем глобальные команды на каждый сервер,
            # чтобы они стали доступны сразу, не дожидаясь ~1 часа.
            # В DEBUG пропускаем GUILD_ID — он уже синхронизирован выше.
            for g in bot.guilds:
                if DEBUG and g.id == GUILD_ID:
                    continue
                try:
                    bot.tree.copy_global_to(guild=g)
                    await asyncio.wait_for(bot.tree.sync(guild=g), timeout=20)
                    log.info(f"Команды синхронизированы для: {g.name} ({g.id})")
                except Exception as e:
                    log.error(f"Ошибка sync для {g.name} ({g.id}): {e}")

            _synced_once = True
            log.info("Синхронизация команд завершена.")

        except asyncio.TimeoutError:
            log.error("Sync команд завис (timeout 20 сек) — пропускаем, продолжаем запуск.")
        except Exception as e:
            log.error(f"Ошибка sync команд (не критично, продолжаем): {e}")
    else:
        log.info("Reconnect — sync команд пропускается (уже выполнен).")

    # ----------------------------------------------------------
    # Presence и voice выполняются ВСЕГДА — даже если sync выше
    # упал или зависнул по таймауту.
    # ----------------------------------------------------------
    try:
        await bot.change_presence(
            status=discord.Status.online,
            activity=discord.Game("Играет в шахматы")
        )
        log.info("Статус бота установлен: 'Играет в шахматы'")
    except Exception as e:
        log.error(f"Ошибка установки статуса: {e}")

    if not voice_keep_alive.is_running():
        voice_keep_alive.start()
        log.info("voice_keep_alive запущен")
    else:
        log.info("voice_keep_alive уже работает (reconnect).")

    log.info("=" * 60)


@bot.event
async def on_guild_join(guild: discord.Guild):
    """При добавлении бота на новый сервер — сразу синхронизируем команды."""
    try:
        bot.tree.copy_global_to(guild=guild)
        await bot.tree.sync(guild=guild)
        log.info(f"Команды синхронизированы для нового сервера: {guild.name} ({guild.id})")
    except Exception as e:
        log.error(f"Ошибка синхронизации для нового сервера {guild.name} ({guild.id}): {e}")


async def reply_with_image(message: discord.Message, text: str, image_key: str):
    """Отправляет ответ с изображением через URL (embed)."""
    url = IMAGES.get(image_key)
    if url:
        embed = discord.Embed(description=text)
        embed.set_image(url=url)
        await message.reply(embed=embed)
    else:
        await message.reply(text)


@bot.event
async def on_message(message):
    if message.author.bot:
        return
    await bot.process_commands(message)
    text = message.content.lower()

    # Проверяем включены ли реакции на слова для этого сервера
    if message.guild and not get_shiro_react(message.guild.id):
        return

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
        await reply_with_image(message, "Ну серьёзно..)", "img1")
    elif any(word in text for word in words_png2):
        await reply_with_image(message, "Мило 😍", "img2")
    elif any(word in text for word in words_png3):
        await reply_with_image(message, "Давайте все вместе помолимся за наше духовное спокойствие 😇", "img3")
    elif any(word in text for word in words_png4):
        await reply_with_image(message, "Не беситесь 👿", "img4")
    elif any(word in text for word in words_png5):
        await reply_with_image(message, "Присоединяюсь к поздравлениям! 🎉", "img5")
    elif any(word in text for word in words_png6):
        await reply_with_image(message, "Даже круче, чем я?", "img6")
    elif any(word in text for word in words_gif1):
        await reply_with_image(message, "Ну кто меня разбудил, чего хотели... 😴", "gif1")
    elif any(word in text for word in words_gif2):
        await reply_with_image(message, "Да ну Вас, извращенцы! 😒", "gif2")
    elif any(word in text for word in words_gif3):
        await reply_with_image(message, "М-м-мягкие 😊", "gif3")
    elif any(word in text for word in words_gif4):
        await reply_with_image(message, "Приятного аппетита! 🍩", "gif4")
    
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