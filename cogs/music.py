# cogs/music.py
# apt update
# apt install -y ffmpeg

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


# ==========================================================
# Настройки FFmpeg
# ==========================================================

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

        # Очередь треков для каждого сервера
        #
        # guild_id -> [track, track, track]
        self.queues: dict[int, list] = {}

        # Текущий трек
        #
        # guild_id -> track
        self.current: dict[int, dict] = {}

        # Флаг пропуска текущего трека
        #
        # guild_id -> True / False
        self.skipping: dict[int, bool] = {}

        # Громкость для каждого сервера
        #
        # Значение хранится в процентах:
        # 100 = 100%
        # 50  = 50%
        # 0   = 0%
        self.volumes: dict[int, float] = {}

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

            # ------------------------------------------------
            # Создаём FFmpeg источник
            # ------------------------------------------------

            source = discord.FFmpegPCMAudio(
                track["url"],
                **FFMPEG_OPTIONS
            )

            # ------------------------------------------------
            # Получаем громкость сервера
            #
            # Если значение ещё не задавали,
            # используется 100%.
            # ------------------------------------------------

            volume = self.volumes.get(
                guild_id,
                100
            )

            # Переводим проценты в диапазон 0.0 - 1.0
            source = discord.PCMVolumeTransformer(
                source,
                volume=volume / 100
            )

            # ------------------------------------------------
            # Запускаем воспроизведение
            # ------------------------------------------------

            voice_client.play(
                source,
                after=lambda error: self.on_track_finished(
                    guild_id,
                    error
                )
            )

            # Сохраняем текущий трек
            self.current[guild_id] = track

            print(
                f"[Music] ▶️ Запущен: "
                f"{track['title']} "
                f"(громкость {volume:.0f}%)"
            )

            return True

        except Exception as e:

            print(
                f"[Music] ❌ Ошибка запуска "
                f"'{track.get('title', 'Unknown')}': "
                f"{type(e).__name__}: {e}"
            )

            import traceback

            traceback.print_exc()

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
                f"[Music] ❌ Ошибка воспроизведения "
                f"guild={guild_id}: {error}"
            )

        # Callback FFmpeg может выполняться
        # в отдельном потоке.
        #
        # Поэтому возвращаемся в asyncio loop.

        self.bot.loop.call_soon_threadsafe(
            lambda: asyncio.create_task(
                self.handle_track_finished(
                    guild_id
                )
            )
        )

    # ======================================================
    # Обработка окончания трека
    # ======================================================

    async def handle_track_finished(
        self,
        guild_id: int
    ):

        # --------------------------------------------------
        # Если трек был пропущен через /skip,
        # /skip самостоятельно запустит следующий.
        # --------------------------------------------------

        if self.skipping.get(
            guild_id,
            False
        ):

            self.skipping[guild_id] = False

            return

        # --------------------------------------------------
        # Получаем сервер
        # --------------------------------------------------

        guild = self.bot.get_guild(
            guild_id
        )

        if guild is None:

            self.current.pop(
                guild_id,
                None
            )

            return

        # --------------------------------------------------
        # Получаем VoiceClient
        # --------------------------------------------------

        voice_client = guild.voice_client

        if voice_client is None:

            self.current.pop(
                guild_id,
                None
            )

            return

        # --------------------------------------------------
        # Запускаем следующий трек
        # --------------------------------------------------

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

        # --------------------------------------------------
        # Очередь пуста
        # --------------------------------------------------

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

        # --------------------------------------------------
        # Берём первый трек из очереди
        # --------------------------------------------------

        track = queue.pop(0)

        # --------------------------------------------------
        # Запускаем
        # --------------------------------------------------

        success = self.start_track(
            guild_id,
            voice_client,
            track
        )

        # --------------------------------------------------
        # Если запуск не удался —
        # пробуем следующий трек
        # --------------------------------------------------

        if not success:

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

        # --------------------------------------------------
        # Проверяем сервер
        # --------------------------------------------------

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
        # Получаем информацию о YouTube-видео
        # --------------------------------------------------

        try:

            info = await self.get_audio_info(
                url
            )

        except Exception as e:

            print(
                f"[Music] ❌ Ошибка yt-dlp:"
            )

            print(
                f"{type(e).__name__}: {e}"
            )

            import traceback

            traceback.print_exc()

            await interaction.followup.send(
                "❌ Не удалось получить аудио с YouTube."
            )

            return

        # --------------------------------------------------
        # Проверяем результат
        # --------------------------------------------------

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
        # Получаем URL аудиопотока
        # --------------------------------------------------

        audio_url = info.get(
            "url"
        )

        if not audio_url:

            await interaction.followup.send(
                "❌ Не удалось получить аудиопоток."
            )

            return

        # --------------------------------------------------
        # Создаём объект трека
        # --------------------------------------------------

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

        # --------------------------------------------------
        # Уже на паузе
        # --------------------------------------------------

        if voice_client.is_paused():

            await interaction.response.send_message(
                "⏸️ Музыка уже стоит на паузе."
            )

            return

        # --------------------------------------------------
        # Ничего не играет
        # --------------------------------------------------

        if not voice_client.is_playing():

            await interaction.response.send_message(
                "❌ Сейчас ничего не играет."
            )

            return

        # --------------------------------------------------
        # Ставим на паузу
        # --------------------------------------------------

        voice_client.pause()

        await interaction.response.send_message(
            "⏸️ Музыка поставлена на паузу."
        )

    # ======================================================
    # /resume
    # ======================================================

    @app_commands.command(
        name="resume",
        description="Продолжить воспроизведение после паузы"
    )
    async def resume(
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

        # --------------------------------------------------
        # Проверяем паузу
        # --------------------------------------------------

        if not voice_client.is_paused():

            if voice_client.is_playing():

                await interaction.response.send_message(
                    "▶️ Музыка уже воспроизводится."
                )

            else:

                await interaction.response.send_message(
                    "❌ Сейчас ничего не стоит на паузе."
                )

            return

        # --------------------------------------------------
        # Продолжаем
        # --------------------------------------------------

        voice_client.resume()

        await interaction.response.send_message(
            "▶️ Музыка продолжена."
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

        # --------------------------------------------------
        # Проверяем воспроизведение
        # --------------------------------------------------

        if (
            not voice_client.is_playing()
            and not voice_client.is_paused()
        ):

            await interaction.response.send_message(
                "❌ Сейчас ничего не играет."
            )

            return

        # --------------------------------------------------
        # Сообщаем обработчику окончания,
        # что это был /skip
        # --------------------------------------------------

        self.skipping[guild_id] = True

        # Останавливаем текущий трек.
        #
        # Это вызовет on_track_finished(),
        # но тот увидит skipping=True
        # и не запустит следующий.
        voice_client.stop()

        # --------------------------------------------------
        # Получаем очередь
        # --------------------------------------------------

        queue = self.queues.setdefault(
            guild_id,
            []
        )

        # --------------------------------------------------
        # Есть следующий трек
        # --------------------------------------------------

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

                # Если следующий не запустился,
                # пробуем продолжить очередь.

                await self.play_next(
                    guild_id,
                    voice_client
                )

            return

        # --------------------------------------------------
        # Очередь пуста
        # --------------------------------------------------

        self.current.pop(
            guild_id,
            None
        )

        self.skipping[guild_id] = False

        await interaction.response.send_message(
            "⏭️ Трек пропущен. Очередь пуста."
        )

    # ======================================================
    # /volume
    # ======================================================

    @app_commands.command(
        name="volume",
        description="Установить или показать громкость"
    )
    @app_commands.describe(
        volume="Громкость от 0 до 100 процентов"
    )
    async def volume(
        self,
        interaction: discord.Interaction,
        volume: float | None = None
    ):

        guild = interaction.guild

        if guild is None:

            await interaction.response.send_message(
                "❌ Эта команда доступна только на сервере."
            )

            return

        guild_id = guild.id

        # --------------------------------------------------
        # /volume без значения
        # --------------------------------------------------

        if volume is None:

            current_volume = self.volumes.get(
                guild_id,
                100
            )

            await interaction.response.send_message(
                f"🔊 Текущая громкость: "
                f"**{current_volume:.0f}%**"
            )

            return

        # --------------------------------------------------
        # Проверяем диапазон
        # --------------------------------------------------

        if volume < 0 or volume > 100:

            await interaction.response.send_message(
                "❌ Громкость должна быть "
                "от **0 до 100**."
            )

            return

        # --------------------------------------------------
        # Сохраняем громкость
        # --------------------------------------------------

        self.volumes[guild_id] = volume

        # --------------------------------------------------
        # Если сейчас что-то играет —
        # меняем громкость сразу
        # --------------------------------------------------

        voice_client = guild.voice_client

        if voice_client is not None:

            source = voice_client.source

            if isinstance(
                source,
                discord.PCMVolumeTransformer
            ):

                source.volume = volume / 100

        # --------------------------------------------------
        # Ответ
        # --------------------------------------------------

        await interaction.response.send_message(
            f"🔊 Громкость установлена: "
            f"**{volume:.0f}%**"
        )


# ==========================================================
# Загрузка Cog
# ==========================================================

async def setup(bot: commands.Bot):

    await bot.add_cog(
        Music(bot)
    )
