# cogs/music.py
# apt update
# apt install -y ffmpeg

import asyncio
import json
import os

import discord
import yt_dlp

from discord import app_commands
from discord.ext import commands


# ==========================================================
# НАСТРОЙКИ
# ==========================================================

# Текстовый канал, в котором разрешены музыкальные команды
MUSIC_CHANNEL_ID = 1530307336911196381

# Путь к JSON с сохранёнными треками
DATA_DIR = "/app/data"
MUSIC_FILE = os.path.join(DATA_DIR, "music.json")


# ==========================================================
# YT-DLP
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
# FFMPEG
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
# MUSIC COG
# ==========================================================

class Music(commands.Cog):

    def __init__(self, bot: commands.Bot):
        self.bot = bot

        # --------------------------------------------------
        # Очереди
        #
        # guild_id -> список треков
        # --------------------------------------------------

        self.queues: dict[int, list] = {}

        # --------------------------------------------------
        # Текущий трек
        #
        # guild_id -> track
        # --------------------------------------------------

        self.current: dict[int, dict] = {}

        # --------------------------------------------------
        # Флаг /music_skip
        # --------------------------------------------------

        self.skipping: dict[int, bool] = {}

        # --------------------------------------------------
        # Громкость серверов
        #
        # guild_id -> volume
        # --------------------------------------------------

        self.volumes: dict[int, float] = {}

        # --------------------------------------------------
        # Сохранённые пользователем треки
        #
        # name -> YouTube URL
        # --------------------------------------------------

        self.saved_tracks: dict[str, str] = {}

        # --------------------------------------------------
        # Блокировка работы с JSON
        # --------------------------------------------------

        self.file_lock = asyncio.Lock()

        # --------------------------------------------------
        # Создаём папку /app/data
        # --------------------------------------------------

        os.makedirs(
            DATA_DIR,
            exist_ok=True
        )

        # --------------------------------------------------
        # Загружаем сохранённые треки
        # --------------------------------------------------

        self.load_saved_tracks()

    # ======================================================
    # JSON
    # ======================================================

    def load_saved_tracks(self):
        """
        Загружает сохранённые треки из music.json.
        """

        if not os.path.exists(MUSIC_FILE):

            self.saved_tracks = {}

            self.save_saved_tracks_sync()

            print(
                f"[Music] Создан файл {MUSIC_FILE}"
            )

            return

        try:

            with open(
                MUSIC_FILE,
                "r",
                encoding="utf-8"
            ) as file:

                data = json.load(file)

            if isinstance(data, dict):

                self.saved_tracks = data

            else:

                print(
                    "[Music] ⚠️ music.json имеет "
                    "неправильный формат."
                )

                self.saved_tracks = {}

            print(
                f"[Music] Загружено сохранённых треков: "
                f"{len(self.saved_tracks)}"
            )

        except json.JSONDecodeError as e:

            print(
                f"[Music] ❌ Ошибка чтения music.json: {e}"
            )

            self.saved_tracks = {}

        except Exception as e:

            print(
                f"[Music] ❌ Ошибка загрузки music.json: "
                f"{type(e).__name__}: {e}"
            )

            self.saved_tracks = {}

    # ======================================================

    def save_saved_tracks_sync(self):
        """
        Синхронно сохраняет JSON.
        Используется при запуске Cog.
        """

        with open(
            MUSIC_FILE,
            "w",
            encoding="utf-8"
        ) as file:

            json.dump(
                self.saved_tracks,
                file,
                ensure_ascii=False,
                indent=4
            )

    # ======================================================

    async def save_saved_tracks(self):
        """
        Сохраняет сохранённые треки в JSON.
        """

        async with self.file_lock:

            loop = asyncio.get_running_loop()

            data = dict(
                self.saved_tracks
            )

            def save():

                with open(
                    MUSIC_FILE,
                    "w",
                    encoding="utf-8"
                ) as file:

                    json.dump(
                        data,
                        file,
                        ensure_ascii=False,
                        indent=4
                    )

            await loop.run_in_executor(
                None,
                save
            )

    # ======================================================
    # Проверка музыкального канала
    # ======================================================

    async def check_music_channel(
        self,
        interaction: discord.Interaction
    ) -> bool:

        if interaction.channel_id == MUSIC_CHANNEL_ID:
            return True

        await interaction.response.send_message(
            "❌ Музыкальные команды доступны "
            f"только в <#{MUSIC_CHANNEL_ID}>.",
            ephemeral=True
        )

        return False

    # ======================================================
    # Поиск сохранённого трека
    # ======================================================

    def find_saved_track(
        self,
        name: str
    ):
        """
        Ищет сохранённый трек без учёта регистра.

        Например:
        Phonk
        phonk
        PHONK

        будут считаться одним названием.
        """

        name_normalized = name.strip().casefold()

        for saved_name, url in self.saved_tracks.items():

            if saved_name.casefold() == name_normalized:

                return saved_name, url

        return None, None

    # ======================================================
    # Получение информации с YouTube
    # ======================================================

    async def get_audio_info(
        self,
        url: str
    ):

        loop = asyncio.get_running_loop()

        def extract():

            with yt_dlp.YoutubeDL(
                YTDL_OPTIONS
            ) as ydl:

                return ydl.extract_info(
                    url,
                    download=False
                )

        return await loop.run_in_executor(
            None,
            extract
        )

    # ======================================================
    # Запуск трека
    # ======================================================

    def start_track(
        self,
        guild_id: int,
        voice_client: discord.VoiceClient,
        track: dict
    ) -> bool:

        try:

            # ------------------------------------------------
            # FFmpeg
            # ------------------------------------------------

            source = discord.FFmpegPCMAudio(
                track["url"],
                **FFMPEG_OPTIONS
            )

            # ------------------------------------------------
            # Громкость
            # ------------------------------------------------

            volume = self.volumes.get(
                guild_id,
                100
            )

            source = discord.PCMVolumeTransformer(
                source,
                volume=volume / 100
            )

            # ------------------------------------------------
            # Воспроизведение
            # ------------------------------------------------

            voice_client.play(
                source,
                after=lambda error: self.on_track_finished(
                    guild_id,
                    error
                )
            )

            # ------------------------------------------------
            # Сохраняем текущий трек
            # ------------------------------------------------

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
    # Callback FFmpeg
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
        # Если был /music_skip
        # --------------------------------------------------

        if self.skipping.get(
            guild_id,
            False
        ):

            self.skipping[guild_id] = False

            return

        # --------------------------------------------------
        # Сервер
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
        # VoiceClient
        # --------------------------------------------------

        voice_client = guild.voice_client

        if voice_client is None:

            self.current.pop(
                guild_id,
                None
            )

            return

        # --------------------------------------------------
        # Следующий трек
        # --------------------------------------------------

        await self.play_next(
            guild_id,
            voice_client
        )

    # ======================================================
    # Следующий трек
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
        # Берём следующий
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
        # Если не получилось —
        # пробуем следующий
        # --------------------------------------------------

        if not success:

            await self.play_next(
                guild_id,
                voice_client
            )

    # ======================================================
    # /music_play
    # ======================================================

    @app_commands.command(
        name="music_play",
        description="Воспроизвести музыку с YouTube или сохранённый трек"
    )
    @app_commands.describe(
        query="Ссылка на YouTube или название сохранённого трека"
    )
    async def music_play(
        self,
        interaction: discord.Interaction,
        query: str
    ):

        # --------------------------------------------------
        # Проверяем канал
        # --------------------------------------------------

        if not await self.check_music_channel(
            interaction
        ):
            return

        await interaction.response.defer()

        guild = interaction.guild

        if guild is None:

            await interaction.followup.send(
                "❌ Эта команда доступна только на сервере."
            )

            return

        guild_id = guild.id

        # --------------------------------------------------
        # Проверяем VoiceClient
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
        # Определяем:
        #
        # сохранённый трек
        # или
        # ссылка YouTube
        # --------------------------------------------------

        saved_name, saved_url = self.find_saved_track(
            query
        )

        if saved_url:

            url = saved_url

            source_name = saved_name

            print(
                f"[Music] Найден сохранённый трек: "
                f"{saved_name}"
            )

        else:

            url = query

            source_name = None

        # --------------------------------------------------
        # Получаем информацию с YouTube
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

            if source_name:

                message = (
                    f"❌ Не удалось воспроизвести "
                    f"сохранённый трек `{source_name}`."
                )

            else:

                message = (
                    "❌ Не удалось получить аудио с YouTube."
                )

            await interaction.followup.send(
                message
            )

            return

        # --------------------------------------------------
        # Проверяем информацию
        # --------------------------------------------------

        if not info:

            await interaction.followup.send(
                "❌ YouTube не вернул информацию о видео."
            )

            return

        # --------------------------------------------------
        # entries
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
        # Аудио URL
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
        # Создаём трек
        # --------------------------------------------------

        track = {
            "title": info.get(
                "title",
                source_name or "Без названия"
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
        # Если ничего не играет —
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

            if source_name:

                await interaction.followup.send(
                    f"▶️ **Сейчас играет:** "
                    f"`{source_name}`\n"
                    f"🎵 `{track['title']}`"
                )

            else:

                await interaction.followup.send(
                    f"▶️ **Сейчас играет:** "
                    f"`{track['title']}`"
                )

            return

        # --------------------------------------------------
        # Если уже играет или стоит на паузе —
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

        if source_name:

            await interaction.followup.send(
                f"🎵 **Добавлено в очередь:** "
                f"`{source_name}`\n"
                f"Позиция: **{position}**"
            )

        else:

            await interaction.followup.send(
                f"🎵 **Добавлено в очередь:** "
                f"`{track['title']}`\n"
                f"Позиция: **{position}**"
            )

    # ======================================================
    # /music_pause
    # ======================================================

    @app_commands.command(
        name="music_pause",
        description="Поставить музыку на паузу"
    )
    async def music_pause(
        self,
        interaction: discord.Interaction
    ):

        if not await self.check_music_channel(
            interaction
        ):
            return

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
    # /music_resume
    # ======================================================

    @app_commands.command(
        name="music_resume",
        description="Продолжить музыку после паузы"
    )
    async def music_resume(
        self,
        interaction: discord.Interaction
    ):

        if not await self.check_music_channel(
            interaction
        ):
            return

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

        if not voice_client.is_paused():

            if voice_client.is_playing():

                await interaction.response.send_message(
                    "▶️ Музыка уже воспроизводится."
                )

            else:

                await interaction.response.send_message(
                    "❌ Сейчас музыка не стоит на паузе."
                )

            return

        voice_client.resume()

        await interaction.response.send_message(
            "▶️ Музыка продолжена."
        )

    # ======================================================
    # /music_skip
    # ======================================================

    @app_commands.command(
        name="music_skip",
        description="Пропустить текущий трек"
    )
    async def music_skip(
        self,
        interaction: discord.Interaction
    ):

        if not await self.check_music_channel(
            interaction
        ):
            return

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
        # Отмечаем skip
        # --------------------------------------------------

        self.skipping[guild_id] = True

        # --------------------------------------------------
        # Останавливаем текущий трек
        # --------------------------------------------------

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
                    f"⏭️ **Сейчас играет:** "
                    f"`{next_track['title']}`"
                )

            else:

                await interaction.response.send_message(
                    "⏭️ Трек пропущен, "
                    "но следующий трек не удалось запустить."
                )

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
    # /music_volume
    # ======================================================

    @app_commands.command(
        name="music_volume",
        description="Установить или показать громкость"
    )
    @app_commands.describe(
        volume="Громкость от 0 до 100 процентов"
    )
    async def music_volume(
        self,
        interaction: discord.Interaction,
        volume: float | None = None
    ):

        if not await self.check_music_channel(
            interaction
        ):
            return

        guild = interaction.guild

        if guild is None:

            await interaction.response.send_message(
                "❌ Эта команда доступна только на сервере."
            )

            return

        guild_id = guild.id

        # --------------------------------------------------
        # /music_volume
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
        # Проверяем значение
        # --------------------------------------------------

        if volume < 0 or volume > 100:

            await interaction.response.send_message(
                "❌ Громкость должна быть "
                "от **0 до 100**."
            )

            return

        # --------------------------------------------------
        # Сохраняем
        # --------------------------------------------------

        self.volumes[guild_id] = volume

        # --------------------------------------------------
        # Меняем текущий источник
        # --------------------------------------------------

        voice_client = guild.voice_client

        if voice_client is not None:

            source = voice_client.source

            if isinstance(
                source,
                discord.PCMVolumeTransformer
            ):

                source.volume = volume / 100

        await interaction.response.send_message(
            f"🔊 Громкость установлена: "
            f"**{volume:.0f}%**"
        )

    # ======================================================
    # /music_save
    # ======================================================

    @app_commands.command(
        name="music_save",
        description="Сохранить YouTube-трек под своим названием"
    )
    @app_commands.describe(
        url="Ссылка на видео YouTube",
        text="Название, под которым сохранить трек"
    )
    async def music_save(
        self,
        interaction: discord.Interaction,
        url: str,
        text: str
    ):

        if not await self.check_music_channel(
            interaction
        ):
            return

        # --------------------------------------------------
        # Чистим название
        # --------------------------------------------------

        name = text.strip()

        if not name:

            await interaction.response.send_message(
                "❌ Название трека не может быть пустым."
            )

            return

        # --------------------------------------------------
        # Проверяем URL
        # --------------------------------------------------

        if not (
            "youtube.com" in url.lower()
            or "youtu.be" in url.lower()
        ):

            await interaction.response.send_message(
                "❌ Для сохранения нужна ссылка на YouTube."
            )

            return

        # --------------------------------------------------
        # Проверяем существующее название
        # --------------------------------------------------

        existing_name, _ = self.find_saved_track(
            name
        )

        if existing_name:

            await interaction.response.send_message(
                f"❌ Название `{existing_name}` "
                "уже используется."
            )

            return

        # --------------------------------------------------
        # Сохраняем
        # --------------------------------------------------

        self.saved_tracks[name] = url

        try:

            await self.save_saved_tracks()

        except Exception as e:

            # Если JSON не удалось сохранить,
            # откатываем изменение в памяти.

            self.saved_tracks.pop(
                name,
                None
            )

            print(
                f"[Music] ❌ Ошибка сохранения: "
                f"{type(e).__name__}: {e}"
            )

            await interaction.response.send_message(
                "❌ Не удалось сохранить трек."
            )

            return

        await interaction.response.send_message(
            f"💾 Трек сохранён под названием "
            f"**{name}**."
        )

        print(
            f"[Music] 💾 Сохранён трек: "
            f"{name} -> {url}"
        )

    # ======================================================
    # /music_del
    # ======================================================

    @app_commands.command(
        name="music_del",
        description="Удалить сохранённый трек"
    )
    @app_commands.describe(
        text="Название сохранённого трека"
    )
    async def music_del(
        self,
        interaction: discord.Interaction,
        text: str
    ):

        if not await self.check_music_channel(
            interaction
        ):
            return

        # --------------------------------------------------
        # Ищем название
        # --------------------------------------------------

        saved_name, _ = self.find_saved_track(
            text
        )

        if not saved_name:

            await interaction.response.send_message(
                f"❌ Сохранённый трек `{text}` не найден."
            )

            return

        # --------------------------------------------------
        # Удаляем
        # --------------------------------------------------

        self.saved_tracks.pop(
            saved_name,
            None
        )

        try:

            await self.save_saved_tracks()

        except Exception as e:

            print(
                f"[Music] ❌ Ошибка удаления: "
                f"{type(e).__name__}: {e}"
            )

            await interaction.response.send_message(
                "❌ Не удалось обновить music.json."
            )

            return

        await interaction.response.send_message(
            f"🗑️ Трек **{saved_name}** удалён."
        )

        print(
            f"[Music] 🗑️ Удалён трек: "
            f"{saved_name}"
        )


# ==========================================================
# Загрузка Cog
# ==========================================================

async def setup(bot: commands.Bot):

    await bot.add_cog(
        Music(bot)
    )
