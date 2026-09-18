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
        logging.FileHandler(
            "/app/data/bot.log",
            encoding="utf-8"
        ),
        logging.StreamHandler()
    ]
)

log = logging.getLogger(__name__)


# ==========================================================
# Настройки
# ==========================================================

TOKEN = os.getenv("DISCORD_TOKEN")

DEBUG = os.getenv(
    "DEBUG",
    "False"
) == "True"

GUILD_ID = int(
    os.getenv(
        "GUILD_ID",
        "0"
    )
)

VOICE_CHANNEL_ID = int(
    os.getenv(
        "VOICE_CHANNEL_ID",
        "0"
    )
)


log.info(f"DEBUG = {DEBUG}")
log.info(f"GUILD_ID = {GUILD_ID}")
log.info(f"VOICE_CHANNEL_ID = {VOICE_CHANNEL_ID}")


# ==========================================================
# Intents
# ==========================================================

intents = discord.Intents.default()

intents.message_content = True
intents.members = True


# ==========================================================
# Bot
# ==========================================================

bot = commands.Bot(
    command_prefix="!",
    intents=intents,
    help_command=None
)


# ==========================================================
# Блокировка подключения к голосовому каналу
# ==========================================================
#
# Нужна для ситуации, когда одновременно срабатывают:
#
# 1. on_voice_state_update
# 2. voice_keep_alive
#
# Чтобы они не попытались подключить Широ два раза.
# ==========================================================

voice_connect_lock = asyncio.Lock()


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

    "gif4": "https://cdn.discordapp.com/attachments/1265811455308070973/1265811773374599261/68747470733a2f2f73332e616d617a6f6e6177732e636f6d2f776174747061642d6d656469612d736572766963652f53746f7279496d6167652f4445325a567653663555574b31773d3d2d37322e313632323933373937306531333638393537373937333432383732302e676966.gif",
}


# ==========================================================
# Голосовой канал
# ==========================================================

async def connect_to_voice_channel():
    """
    Подключает Широ к целевому голосовому каналу,
    только если бот вообще не находится в голосовом канале.
    """

    if VOICE_CHANNEL_ID == 0:
        return

    # ------------------------------------------------------
    # Ищем канал
    # ------------------------------------------------------

    channel = bot.get_channel(
        VOICE_CHANNEL_ID
    )

    if channel is None:

        log.warning(
            f"Голосовой канал {VOICE_CHANNEL_ID} не найден."
        )

        return

    # ------------------------------------------------------
    # Проверяем тип канала
    # ------------------------------------------------------

    if not isinstance(
        channel,
        discord.VoiceChannel
    ):

        log.warning(
            f"Канал {VOICE_CHANNEL_ID} существует, "
            f"но не является голосовым."
        )

        return

    guild = channel.guild

    # ------------------------------------------------------
    # Получаем текущее голосовое подключение
    # ------------------------------------------------------

    vc = guild.voice_client

    # ------------------------------------------------------
    # Широ уже находится в ЛЮБОМ голосовом канале
    # ------------------------------------------------------
    #
    # ВАЖНО:
    #
    # Мы больше НЕ сравниваем vc.channel.id
    # с VOICE_CHANNEL_ID.
    #
    # Поэтому если Широ переместили:
    #
    # Канал A -> Канал B
    #
    # он останется в B.
    # ------------------------------------------------------

    if vc is not None and vc.is_connected():

        log.debug(
            f"Широ уже находится в голосовом канале "
            f"'{vc.channel.name}' ({vc.channel.id}). "
            f"Перемещение не требуется."
        )

        return

    # ------------------------------------------------------
    # Широ вообще не подключён
    # ------------------------------------------------------

    async with voice_connect_lock:

        # --------------------------------------------------
        # Повторно проверяем состояние после получения lock
        #
        # Возможно, другой процесс уже успел подключиться.
        # --------------------------------------------------

        vc = guild.voice_client

        if vc is not None and vc.is_connected():

            log.debug(
                f"Широ уже подключён к "
                f"'{vc.channel.name}' ({vc.channel.id})."
            )

            return

        # --------------------------------------------------
        # Подключаемся
        # --------------------------------------------------

        try:

            log.info(
                f"Подключаюсь к голосовому каналу "
                f"'{channel.name}' ({VOICE_CHANNEL_ID})"
            )

            await channel.connect()

            log.info(
                f"Широ успешно подключился к "
                f"'{channel.name}' ({VOICE_CHANNEL_ID})"
            )

        except discord.ClientException as e:

            log.warning(
                f"Не удалось подключиться к голосовому "
                f"каналу: {e}"
            )

        except Exception as e:

            log.error(
                f"Ошибка подключения к голосовому каналу: "
                f"{type(e).__name__}: {e}"
            )


# ==========================================================
# Голосовой канал — фоновая задача
# ==========================================================

@tasks.loop(seconds=30)
async def voice_keep_alive():

    if VOICE_CHANNEL_ID == 0:
        return

    # ------------------------------------------------------
    # Получаем целевой канал
    # ------------------------------------------------------

    channel = bot.get_channel(
        VOICE_CHANNEL_ID
    )

    if channel is None:

        log.warning(
            f"Голосовой канал {VOICE_CHANNEL_ID} не найден."
        )

        return

    if not isinstance(
        channel,
        discord.VoiceChannel
    ):

        log.warning(
            f"Канал {VOICE_CHANNEL_ID} существует, "
            f"но не является голосовым."
        )

        return

    guild = channel.guild

    # ------------------------------------------------------
    # Проверяем текущее подключение
    # ------------------------------------------------------

    vc = guild.voice_client

    # ------------------------------------------------------
    # Если Широ находится в любом голосовом канале —
    # ничего не делаем.
    #
    # Это главное изменение.
    # ------------------------------------------------------

    if vc is not None and vc.is_connected():

        log.debug(
            f"Широ находится в голосовом канале "
            f"'{vc.channel.name}' ({vc.channel.id}). "
            f"Возврат в исходный канал не выполняется."
        )

        return

    # ------------------------------------------------------
    # Если Широ вообще не подключён —
    # пытаемся подключиться.
    # ------------------------------------------------------

    await connect_to_voice_channel()


# ==========================================================
# Перед запуском voice_keep_alive
# ==========================================================

@voice_keep_alive.before_loop
async def before_voice_keep_alive():

    await bot.wait_until_ready()


# ==========================================================
# Ошибка voice_keep_alive
# ==========================================================

@voice_keep_alive.error
async def voice_keep_alive_error(error):

    log.error(
        f"Ошибка в voice_keep_alive: {error}"
    )


# ==========================================================
# Синхронизация команд
# ==========================================================

_synced_once = False


# ==========================================================
# Вспомогательная функция реакций
# ==========================================================

def get_shiro_react(
    guild_id
) -> bool:

    """
    Проверяет, включена ли реакция бота
    на слова для данного сервера.
    """

    try:

        f = Path(
            "/app/data/adm_panel.json"
        )

        if f.exists():

            d = json.loads(
                f.read_text(
                    "utf-8"
                )
            )

            cfg = d.get(
                str(guild_id),
                {}
            )

            return cfg.get(
                "shiro_react",
                True
            )

    except Exception:

        pass

    return True


# ==========================================================
# on_ready
# ==========================================================

@bot.event
async def on_ready():

    global _synced_once

    log.info(
        "=" * 60
    )

    log.info(
        f"Bot User: {bot.user}"
    )

    log.info(
        f"Application ID: {bot.application_id}"
    )

    log.info(
        f"Guild ID: {GUILD_ID}"
    )

    log.info(
        f"DEBUG: {DEBUG}"
    )

    # ------------------------------------------------------
    # Синхронизация команд
    # ------------------------------------------------------

    if not _synced_once:

        log.info(
            "Команды в tree ДО sync:"
        )

        for cmd in bot.tree.get_commands():

            log.info(
                f" - {cmd.name}"
            )

        try:

            if DEBUG:

                dobj = discord.Object(
                    id=GUILD_ID
                )

                bot.tree.clear_commands(
                    guild=dobj
                )

                await asyncio.wait_for(
                    bot.tree.sync(
                        guild=dobj
                    ),
                    timeout=20
                )

                log.info(
                    f"Guild-sync выполнен для {GUILD_ID}"
                )

            # ------------------------------------------------
            # Глобальная синхронизация
            # ------------------------------------------------

            synced = await asyncio.wait_for(
                bot.tree.sync(),
                timeout=20
            )

            log.info(
                "Команды, которые Discord принял:"
            )

            for cmd in synced:

                log.info(
                    f" - {cmd.name}"
                )

            log.info(
                f"Всего синхронизировано глобально: "
                f"{len(synced)}"
            )

            # ------------------------------------------------
            # Копируем команды на сервера
            # ------------------------------------------------

            for g in bot.guilds:

                if DEBUG and g.id == GUILD_ID:
                    continue

                try:

                    bot.tree.copy_global_to(
                        guild=g
                    )

                    await asyncio.wait_for(
                        bot.tree.sync(
                            guild=g
                        ),
                        timeout=20
                    )

                    log.info(
                        f"Команды синхронизированы для: "
                        f"{g.name} ({g.id})"
                    )

                except Exception as e:

                    log.error(
                        f"Ошибка sync для "
                        f"{g.name} ({g.id}): {e}"
                    )

            _synced_once = True

            log.info(
                "Синхронизация команд завершена."
            )

        except asyncio.TimeoutError:

            log.error(
                "Sync команд завис "
                "(timeout 20 сек) — пропускаем, "
                "продолжаем запуск."
            )

        except Exception as e:

            log.error(
                f"Ошибка sync команд "
                f"(не критично, продолжаем): {e}"
            )

    else:

        log.info(
            "Reconnect — sync команд пропускается "
            "(уже выполнен)."
        )

    # ------------------------------------------------------
    # Presence
    # ------------------------------------------------------

    try:

        await bot.change_presence(
            status=discord.Status.online,
            activity=discord.Game(
                "Играет в шахматы"
            )
        )

        log.info(
            "Статус бота установлен: "
            "'Играет в шахматы'"
        )

    except Exception as e:

        log.error(
            f"Ошибка установки статуса: {e}"
        )

    # ------------------------------------------------------
    # Запускаем проверку голосового канала
    # ------------------------------------------------------

    if not voice_keep_alive.is_running():

        voice_keep_alive.start()

        log.info(
            "voice_keep_alive запущен"
        )

    else:

        log.info(
            "voice_keep_alive уже работает "
            "(reconnect)."
        )

    log.info(
        "=" * 60
    )


# ==========================================================
# on_voice_state_update
# ==========================================================

@bot.event
async def on_voice_state_update(
    member: discord.Member,
    before: discord.VoiceState,
    after: discord.VoiceState
):

    # ------------------------------------------------------
    # Нас интересует только сам Широ
    # ------------------------------------------------------

    if bot.user is None:
        return

    if member.id != bot.user.id:
        return

    # ------------------------------------------------------
    # Если after.channel НЕ None,
    # значит Широ находится в каком-то голосовом канале.
    #
    # Это может быть:
    #
    # A -> B
    # B -> C
    # и т.д.
    #
    # Ничего не делаем.
    # ------------------------------------------------------

    if after.channel is not None:

        log.info(
            f"Широ находится в голосовом канале "
            f"'{after.channel.name}' ({after.channel.id}). "
            f"Автоматического перемещения не будет."
        )

        return

    # ------------------------------------------------------
    # after.channel == None
    #
    # Значит Широ полностью вышел из голосового канала.
    #
    # Именно в этом случае возвращаем его
    # в VOICE_CHANNEL_ID.
    # ------------------------------------------------------

    log.info(
        "Широ больше не находится в голосовом канале. "
        "Запускаю автоматическое подключение."
    )

    # ------------------------------------------------------
    # Небольшая задержка.
    #
    # Она помогает Discord успеть обновить VoiceState.
    # ------------------------------------------------------

    await asyncio.sleep(1)

    await connect_to_voice_channel()


# ==========================================================
# on_guild_join
# ==========================================================

@bot.event
async def on_guild_join(
    guild: discord.Guild
):

    """
    При добавлении бота на новый сервер —
    сразу синхронизируем команды.
    """

    try:

        bot.tree.copy_global_to(
            guild=guild
        )

        await bot.tree.sync(
            guild=guild
        )

        log.info(
            f"Команды синхронизированы "
            f"для нового сервера: "
            f"{guild.name} ({guild.id})"
        )

    except Exception as e:

        log.error(
            f"Ошибка синхронизации для "
            f"нового сервера "
            f"{guild.name} ({guild.id}): {e}"
        )


# ==========================================================
# Отправка изображения
# ==========================================================

async def reply_with_image(
    message: discord.Message,
    text: str,
    image_key: str
):

    """
    Отправляет ответ с изображением через URL.
    """

    url = IMAGES.get(
        image_key
    )

    if url:

        embed = discord.Embed(
            description=text
        )

        embed.set_image(
            url=url
        )

        await message.reply(
            embed=embed
        )

    else:

        await message.reply(
            text
        )


# ==========================================================
# on_message
# ==========================================================

@bot.event
async def on_message(
    message
):

    # ------------------------------------------------------
    # Игнорируем сообщения ботов
    # ------------------------------------------------------

    if message.author.bot:
        return

    # ------------------------------------------------------
    # Обрабатываем обычные команды
    # ------------------------------------------------------

    await bot.process_commands(
        message
    )

    text = message.content.lower()

    # ------------------------------------------------------
    # Проверяем включены ли реакции
    # ------------------------------------------------------

    if (
        message.guild
        and not get_shiro_react(
            message.guild.id
        )
    ):

        return

    # ------------------------------------------------------
    # Слова
    # ------------------------------------------------------

    words_png1 = [
        "заебал",
        "надоел"
    ]

    words_png2 = [
        "мило",
        "красиво",
        "кавайно"
    ]

    words_png3 = [
        "господи",
        "боже"
    ]

    words_png4 = [
        "бесит",
        "бесишь",
        "бесят"
    ]

    words_png5 = [
        "поздравл"
    ]

    words_png6 = [
        "крутой",
        "крутая"
    ]

    words_gif1 = [
        "широ"
    ]

    words_gif2 = [
        "панцу",
        "pantsu"
    ]

    words_gif3 = [
        "мягк",
        "упруг"
    ]

    words_gif4 = [
        "приятного",
        "аппетита"
    ]

    # ------------------------------------------------------
    # Реакции
    # ------------------------------------------------------

    if any(
        word in text
        for word in words_png1
    ):

        await reply_with_image(
            message,
            "Ну серьёзно..)",
            "img1"
        )

    elif any(
        word in text
        for word in words_png2
    ):

        await reply_with_image(
            message,
            "Мило 😍",
            "img2"
        )

    elif any(
        word in text
        for word in words_png3
    ):

        await reply_with_image(
            message,
            "Давайте все вместе помолимся "
            "за наше духовное спокойствие 😇",
            "img3"
        )

    elif any(
        word in text
        for word in words_png4
    ):

        await reply_with_image(
            message,
            "Не беситесь 👿",
            "img4"
        )

    elif any(
        word in text
        for word in words_png5
    ):

        await reply_with_image(
            message,
            "Присоединяюсь к поздравлениям! 🎉",
            "img5"
        )

    elif any(
        word in text
        for word in words_png6
    ):

        await reply_with_image(
            message,
            "Даже круче, чем я?",
            "img6"
        )

    elif any(
        word in text
        for word in words_gif1
    ):

        await reply_with_image(
            message,
            "Ну кто меня разбудил, "
            "чего хотели... 😴",
            "gif1"
        )

    elif any(
        word in text
        for word in words_gif2
    ):

        await reply_with_image(
            message,
            "Да ну Вас, извращенцы! 😒",
            "gif2"
        )

    elif any(
        word in text
        for word in words_gif3
    ):

        await reply_with_image(
            message,
            "М-м-мягкие 😊",
            "gif3"
        )

    elif any(
        word in text
        for word in words_gif4
    ):

        await reply_with_image(
            message,
            "Приятного аппетита! 🍩",
            "gif4"
        )


# ==========================================================
# Загрузка Cogs
# ==========================================================

async def load_cogs():

    if not os.path.isdir(
        "cogs"
    ):

        return

    for filename in os.listdir(
        "cogs"
    ):

        if (
            filename.endswith(".py")
            and not filename.startswith("_")
        ):

            try:

                await bot.load_extension(
                    f"cogs.{filename[:-3]}"
                )

                log.info(
                    f"Загружен модуль: {filename}"
                )

            except Exception as e:

                log.error(
                    f"Ошибка загрузки "
                    f"{filename}: {e}"
                )


# ==========================================================
# Запуск
# ==========================================================

async def main():

    async with bot:

        await load_cogs()

        await bot.start(
            TOKEN
        )


# ==========================================================
# MAIN
# ==========================================================

if __name__ == "__main__":

    asyncio.run(
        main()
    )
