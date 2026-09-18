# cogs/music.py

import asyncio
import discord
import yt_dlp

from discord import app_commands
from discord.ext import commands


# ==========================================================
# Настройки yt-dlp
# ==========================================================

YTDL_OPTIONS = {
    "format": "bestaudio/best",
    "noplaylist": True,
    "quiet": True,
    "no_warnings": True,
    "default_search": "auto",
    "extract_flat": False,
}

FFMPEG_OPTIONS = {
    "before_options": (
        "-reconnect 1 "
        "-reconnect_streamed 1 "
        "-reconnect_delay_max 5"
    ),
    "options": "-vn",
}


# ==========================================================
# Music Cog
# ==========================================================

class Music(commands.Cog):

    def __init__(self, bot: commands.Bot):
        self.bot = bot

        # Очередь:
        # guild_id -> список треков
        self.queues: dict[int, list] = {}

        # Текущий трек:
        # guild_id -> track
        self.current: dict[int, dict] = {}

        # Флаг пропуска:
        # guild_id -> bool
        self.skipping: dict[int, bool] = {}

        # Запущенная задача ожидания окончания трека:
        # guild_id -> asyncio.Task
        self.play_tasks: dict[int, asyncio.Task] = {}

    # ======================================================
    # Получение информации с YouTube
    # ======================================================

    async def get_audio_info(self, url: str):

        loop = asyncio.get_running_loop()

        def extract():
            with yt_dlp.YoutubeDL(YTDL_OPTIONS) as ydl:
                return ydl.extract_info(
                    url,
                    download=False
                )

        return await loop.run_in_executor(
            None,
            extract
        )

    # ======================================================
    # Запуск конкретного трека
    # ======================================================

    def start_track(
        self,
        guild_id: int,
        voice_client: discord.VoiceClient,
        track: dict
    ) -> bool:

        try:
            source = discord.FFmpegPCMAudio(
                track["url"],
                **FFMPEG_OPTIONS
            )

            voice_client.play(
                source,
                after=lambda error: self.on_track_finished(
                    guild_id,
                    error
                )
            )

            self.current[guild_id] = track

            print(
                f"[Music] ▶️ Запущен: "
                f"{track['title']}"
            )

            return True

        except Exception as e:

            print(
                f"[Music] ❌ Ошибка запуска "
                f"'{track['title']}': {e}"
            )

            return False

    # ======================================================
    # Callback после окончания трека
    # ======================================================

    def on_track_finished(
        self,
        guild_id: int,
        error
    ):

        if error:
            print(
                f"[Music] Ошибка воспроизведения "
                f"guild={guild_id}: {error}"
            )

        # Callback FFmpeg выполняется в другом потоке.
        # Возвращаемся в asyncio loop.
        self.bot.loop.call_soon_threadsafe(
            lambda: asyncio.create_task(
                self.handle_track_finished(guild_id)
            )
        )

    # ======================================================
    # Обработка окончания трека
    # ======================================================

    async def handle_track_finished(
        self,
        guild_id: int
    ):

        # Если это был /skip —
        # следующий трек уже будет запущен самим skip.
        if self.skipping.get(guild_id, False):
            self.skipping[guild_id] = False
            return

        voice_client = self.bot.get_guild(guild_id)

        if voice_client is None:
            self.current.pop(guild_id, None)
            return

        voice_client = voice_client.voice_client

        if voice_client is None:
            self.current.pop(guild_id, None)
            return

        await self.play_next(
            guild_id,
            voice_client
        )

    # ======================================================
    # Запуск следующего трека
    # ======================================================

    async def play_next(
        self,
        guild_id: int,
        voice_client: discord.VoiceClient
    ):

        queue = self.queues.setdefault(
            guild_id,
            []
        )

        if not queue:
            self.current.pop(
                guild_id,
                None
            )

            print(
                f"[Music] Очередь пуста "
                f"guild={guild_id}"
            )

            return

        track = queue.pop(0)

        success = self.start_track(
            guild_id,
            voice_client,
            track
        )

        if not success:

            # Если трек не запустился,
            # пробуем следующий.
            await self.play_next(
                guild_id,
                voice_client
            )

    # ======================================================
    # /play
    # ======================================================

    @app_commands.command(
        name="play",
        description="Воспроизвести музыку с YouTube"
    )
    @app_commands.describe(
        url="Ссылка на видео YouTube"
    )
    async def play(
        self,
        interaction: discord.Interaction,
        url: str
    ):

        await interaction.response.defer()

        guild = interaction.guild

        if guild is None:
            await interaction.followup.send(
                "❌ Эта команда доступна только на сервере."
            )
            return

        guild_id = guild.id

        # --------------------------------------------------
        # Проверяем голосовое подключение
        # --------------------------------------------------

        voice_client = guild.voice_client

        if (
            voice_client is None
            or not voice_client.is_connected()
        ):
            await interaction.followup.send(
                "❌ Я не нахожусь в голосовом канале."
            )
            return

        # --------------------------------------------------
        # Получаем данные YouTube
        # --------------------------------------------------

        try:

            info = await self.get_audio_info(
                url
            )

        except Exception as e:

            print(
                f"[Music] ❌ Ошибка yt-dlp:\n{e}"
            )

            await interaction.followup.send(
                "❌ Не удалось получить аудио с YouTube.\n"
                "Подробности смотри в консоли бота."
            )

            return

        if not info:

            await interaction.followup.send(
                "❌ YouTube не вернул информацию о видео."
            )

            return

        # --------------------------------------------------
        # Если yt-dlp вернул entries
        # --------------------------------------------------

        if "entries" in info:

            entries = info.get(
                "entries"
            )

            if not entries:

                await interaction.followup.send(
                    "❌ Видео не найдено."
                )

                return

            info = entries[0]

        # --------------------------------------------------
        # Формируем трек
        # --------------------------------------------------

        audio_url = info.get(
            "url"
        )

        if not audio_url:

            await interaction.followup.send(
                "❌ Не удалось получить аудиопоток."
            )

            return

        track = {
            "title": info.get(
                "title",
                "Без названия"
            ),

            "url": audio_url,

            "webpage_url": info.get(
                "webpage_url",
                url
            ),

            "duration": info.get(
                "duration"
            ),
        }

        # --------------------------------------------------
        # Если сейчас ничего не играет —
        # запускаем сразу
        # --------------------------------------------------

        if (
            not voice_client.is_playing()
            and not voice_client.is_paused()
        ):

            success = self.start_track(
                guild_id,
                voice_client,
                track
            )

            if not success:

                await interaction.followup.send(
                    "❌ Не удалось запустить воспроизведение."
                )

                return

            # ВАЖНО:
            # здесь start_track уже вызвал
            # voice_client.play()
            #
            # Поэтому только теперь говорим,
            # что трек действительно запущен.

            await interaction.followup.send(
                f"▶️ **Сейчас играет:** "
                f"`{track['title']}`"
            )

            return

        # --------------------------------------------------
        # Если музыка уже играет —
        # добавляем в очередь
        # --------------------------------------------------

        queue = self.queues.setdefault(
            guild_id,
            []
        )

        queue.append(
            track
        )

        position = len(queue)

        await interaction.followup.send(
            f"🎵 **Добавлено в очередь:** "
            f"`{track['title']}`\n"
            f"Позиция: **{position}**"
        )

    # ======================================================
    # /pause
    # ======================================================

    @app_commands.command(
        name="pause",
        description="Поставить музыку на паузу"
    )
    async def pause(
        self,
        interaction: discord.Interaction
    ):

        guild = interaction.guild

        if guild is None:
            await interaction.response.send_message(
                "❌ Эта команда доступна только на сервере."
            )
            return

        voice_client = guild.voice_client

        if voice_client is None:
            await interaction.response.send_message(
                "❌ Я не нахожусь в голосовом канале."
            )
            return

        if voice_client.is_paused():

            await interaction.response.send_message(
                "⏸️ Музыка уже стоит на паузе."
            )

            return

        if not voice_client.is_playing():

            await interaction.response.send_message(
                "❌ Сейчас ничего не играет."
            )

            return

        voice_client.pause()

        await interaction.response.send_message(
            "⏸️ Музыка поставлена на паузу."
        )

    # ======================================================
    # /skip
    # ======================================================

    @app_commands.command(
        name="skip",
        description="Пропустить текущий трек"
    )
    async def skip(
        self,
        interaction: discord.Interaction
    ):

        guild = interaction.guild

        if guild is None:
            await interaction.response.send_message(
                "❌ Эта команда доступна только на сервере."
            )
            return

        guild_id = guild.id

        voice_client = guild.voice_client

        if voice_client is None:
            await interaction.response.send_message(
                "❌ Я не нахожусь в голосовом канале."
            )
            return

        if (
            not voice_client.is_playing()
            and not voice_client.is_paused()
        ):

            await interaction.response.send_message(
                "❌ Сейчас ничего не играет."
            )

            return

        # --------------------------------------------------
        # Отмечаем, что трек пропускается
        # --------------------------------------------------

        self.skipping[guild_id] = True

        # Останавливаем текущий трек.
        #
        # Это вызовет callback FFmpeg,
        # но handle_track_finished увидит
        # skipping=True и НЕ запустит следующий.
        voice_client.stop()

        # --------------------------------------------------
        # Запускаем следующий трек
        # --------------------------------------------------

        queue = self.queues.setdefault(
            guild_id,
            []
        )

        if queue:

            next_track = queue.pop(0)

            success = self.start_track(
                guild_id,
                voice_client,
                next_track
            )

            self.skipping[guild_id] = False

            if success:

                await interaction.response.send_message(
                    f"⏭️ **Пропущено. Сейчас играет:** "
                    f"`{next_track['title']}`"
                )

            else:

                await interaction.response.send_message(
                    "⏭️ Трек пропущен, "
                    "но следующий трек не удалось запустить."
                )

        else:

            self.current.pop(
                guild_id,
                None
            )

            self.skipping[guild_id] = False

            await interaction.response.send_message(
                "⏭️ Трек пропущен. Очередь пуста."
            )


# ==========================================================
# Загрузка Cog
# ==========================================================

async def setup(bot: commands.Bot):

    await bot.add_cog(
        Music(bot)
    )
