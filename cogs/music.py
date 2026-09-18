# cogs/music.py

import asyncio
import discord
import yt_dlp

from discord import app_commands
from discord.ext import commands


# =========================
# Настройки yt-dlp
# =========================

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


# =========================
# Музыкальный Cog
# =========================

class Music(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

        # Очередь для каждого сервера
        self.queues = {}

        # Данные текущего трека
        self.current = {}

        # Блокировки, чтобы два /play одновременно
        # не сломали очередь
        self.locks = {}

    # =========================
    # Получение информации YouTube
    # =========================

    async def get_audio_info(self, url: str):
        loop = asyncio.get_running_loop()

        def extract():
            with yt_dlp.YoutubeDL(YTDL_OPTIONS) as ydl:
                return ydl.extract_info(url, download=False)

        return await loop.run_in_executor(None, extract)

    # =========================
    # Воспроизведение трека
    # =========================

    async def play_next(self, guild_id: int, voice_client: discord.VoiceClient):
        queue = self.queues.setdefault(guild_id, [])

        if not queue:
            self.current.pop(guild_id, None)
            return

        track = queue.pop(0)

        self.current[guild_id] = track

        audio_url = track["url"]
        title = track["title"]

        try:
            source = discord.FFmpegPCMAudio(
                audio_url,
                **FFMPEG_OPTIONS
            )

            # Создаём Future, который завершится,
            # когда FFmpeg закончит воспроизведение
            finished = self.bot.loop.create_future()

            def after(error):
                if error:
                    print(
                        f"[Music] Ошибка воспроизведения "
                        f"{guild_id}: {error}"
                    )

                # callback FFmpeg работает не обязательно
                # внутри asyncio loop, поэтому используем
                # call_soon_threadsafe
                if not finished.done():
                    self.bot.loop.call_soon_threadsafe(
                        finished.set_result,
                        error
                    )

            voice_client.play(source, after=after)

            print(f"[Music] Воспроизведение: {title}")

            await finished

            # Если /skip уже вызвал остановку,
            # не запускаем следующий трек здесь.
            if getattr(voice_client, "_music_skip", False):
                voice_client._music_skip = False
                return

            # Если бот всё ещё подключён —
            # запускаем следующий трек
            if voice_client.is_connected():
                await self.play_next(guild_id, voice_client)

        except Exception as e:
            print(f"[Music] Ошибка: {e}")

            # Пытаемся перейти к следующему треку
            if voice_client.is_connected():
                await self.play_next(guild_id, voice_client)

    # =========================
    # /play
    # =========================

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

        guild_id = interaction.guild.id

        # Проверяем, что бот находится в голосовом канале
        voice_client = interaction.guild.voice_client

        if voice_client is None or not voice_client.is_connected():
            await interaction.followup.send(
                "❌ Я не нахожусь в голосовом канале."
            )
            return

        # Получаем информацию о видео
        try:
            info = await self.get_audio_info(url)

        except Exception as e:
            print(f"[Music] Ошибка yt-dlp: {e}")

            await interaction.followup.send(
                "❌ Не удалось получить аудио с YouTube."
            )
            return

        if not info:
            await interaction.followup.send(
                "❌ YouTube не вернул информацию о видео."
            )
            return

        # Иногда yt-dlp возвращает entries
        if "entries" in info:
            entries = info.get("entries")

            if not entries:
                await interaction.followup.send(
                    "❌ Видео не найдено."
                )
                return

            info = entries[0]

        track = {
            "title": info.get("title", "Без названия"),
            "url": info.get("url"),
            "webpage_url": info.get("webpage_url", url),
            "duration": info.get("duration"),
        }

        if not track["url"]:
            await interaction.followup.send(
                "❌ Не удалось получить прямой аудиопоток."
            )
            return

        # Добавляем в очередь
        queue = self.queues.setdefault(guild_id, [])
        queue.append(track)

        # Если сейчас ничего не играет —
        # начинаем воспроизведение
        if not voice_client.is_playing() and not voice_client.is_paused():
            asyncio.create_task(
                self.play_next(guild_id, voice_client)
            )

            await interaction.followup.send(
                f"▶️ **Сейчас играет:** `{track['title']}`"
            )

        else:
            position = len(queue)

            await interaction.followup.send(
                f"🎵 Добавлено в очередь: `{track['title']}`\n"
                f"Позиция в очереди: **{position}**"
            )

    # =========================
    # /pause
    # =========================

    @app_commands.command(
        name="pause",
        description="Поставить музыку на паузу"
    )
    async def pause(
        self,
        interaction: discord.Interaction
    ):
        voice_client = interaction.guild.voice_client

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

    # =========================
    # /skip
    # =========================

    @app_commands.command(
        name="skip",
        description="Пропустить текущий трек"
    )
    async def skip(
        self,
        interaction: discord.Interaction
    ):
        voice_client = interaction.guild.voice_client

        if voice_client is None:
            await interaction.response.send_message(
                "❌ Я не нахожусь в голосовом канале."
            )
            return

        if not voice_client.is_playing() and not voice_client.is_paused():
            await interaction.response.send_message(
                "❌ Сейчас ничего не играет."
            )
            return

        # Ставим флаг, чтобы текущий play_next
        # не запустил следующий трек самостоятельно
        voice_client._music_skip = True

        voice_client.stop()

        # Небольшая задержка, чтобы callback успел завершить Future
        await asyncio.sleep(0.1)

        guild_id = interaction.guild.id
        queue = self.queues.setdefault(guild_id, [])

        if queue:
            await interaction.response.send_message(
                f"⏭️ Трек пропущен. Следующий: "
                f"`{queue[0]['title']}`"
            )

            asyncio.create_task(
                self.play_next(guild_id, voice_client)
            )

        else:
            self.current.pop(guild_id, None)

            await interaction.response.send_message(
                "⏭️ Трек пропущен. Очередь пуста."
            )


# =========================
# Загрузка Cog
# =========================

async def setup(bot: commands.Bot):
    await bot.add_cog(Music(bot))
