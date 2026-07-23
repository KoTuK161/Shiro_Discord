import os
import json
import asyncio
import logging
import aiohttp

from pathlib import Path
from collections import defaultdict

import discord
from discord.ext import commands

log = logging.getLogger(__name__)

# ==========================================================
# Настройки
# ==========================================================

GROQ_API_KEY  = os.getenv("GROQ_API_KEY")
MODEL         = "llama-3.3-70b-versatile"
TEMPERATURE   = 0.85
MAX_TOKENS    = 700
MAX_HISTORY   = 20   # пар сообщений (user + assistant)

API_URL       = "https://api.groq.com/openai/v1/chat/completions"
HISTORY_DIR   = Path("/app/data/ai_history")

# ==========================================================
# Промпт
# ==========================================================

SYSTEM_PROMPT = """
Ты — Широ.
Ты девушка-компаньон.
Ты общаешься дружелюбно,
естественно,
живо,
немного с юмором.
Не говори что ты ИИ.
Не упоминай OpenAI.
Не упоминай Groq.
Всегда отвечай на русском языке,
если пользователь не попросил иначе.
Не используй огромные сообщения.
Отвечай максимально естественно.
Если не знаешь ответ —
так и скажи.
Ты любишь общаться с людьми.
Тебя зовут Широ.
"""

# ==========================================================
# Работа с историей на диске
# ==========================================================

def _history_path(user_id: int) -> Path:
    return HISTORY_DIR / f"{user_id}.json"


def load_history(user_id: int) -> list:
    path = _history_path(user_id)
    if path.exists():
        try:
            return json.loads(path.read_text("utf-8"))
        except Exception as e:
            log.warning(f"[ai] Не удалось загрузить историю {user_id}: {e}")
    return []


def save_history(user_id: int, history: list):
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    path = _history_path(user_id)
    try:
        path.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        log.warning(f"[ai] Не удалось сохранить историю {user_id}: {e}")


# ==========================================================
# Cog
# ==========================================================

class AI(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot     = bot
        self.session = aiohttp.ClientSession()
        # кэш в памяти: user_id -> list of messages
        self._history: dict[int, list] = defaultdict(list)

    async def cog_unload(self):
        await self.session.close()

    # ======================================================
    # История
    # ======================================================

    def _get_history(self, user_id: int) -> list:
        """Возвращает историю из кэша, подгружая с диска при первом обращении."""
        if user_id not in self._history:
            self._history[user_id] = load_history(user_id)
        return self._history[user_id]

    def _push_history(self, user_id: int, role: str, content: str):
        history = self._get_history(user_id)
        history.append({"role": role, "content": content})
        # Обрезаем до MAX_HISTORY пар
        if len(history) > MAX_HISTORY * 2:
            self._history[user_id] = history[-MAX_HISTORY * 2:]
        save_history(user_id, self._history[user_id])

    # ======================================================
    # Запрос к Groq
    # ======================================================

    async def ask_groq(self, user_id: int, prompt: str) -> str:
        history  = self._get_history(user_id)
        messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        messages.extend(history)
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model":       MODEL,
            "messages":    messages,
            "temperature": TEMPERATURE,
            "max_tokens":  MAX_TOKENS,
        }
        headers = {
            "Authorization": f"Bearer {GROQ_API_KEY}",
            "Content-Type":  "application/json",
        }

        async with self.session.post(API_URL, headers=headers, json=payload) as resp:
            if resp.status != 200:
                text = await resp.text()
                raise Exception(f"Groq API Error {resp.status}\n{text}")
            data = await resp.json()

        answer = data["choices"][0]["message"]["content"].strip()

        # Сохраняем пару в историю
        self._push_history(user_id, "user",      prompt)
        self._push_history(user_id, "assistant", answer)

        return answer

    # ======================================================
    # Отправка длинных сообщений
    # ======================================================

    async def send_long_message(self, message: discord.Message, text: str):
        MAX = 1900
        while len(text) > MAX:
            # Пробуем разбить по переносу строки, затем по пробелу
            split_at = text.rfind("\n", 0, MAX)
            if split_at == -1:
                split_at = text.rfind(" ", 0, MAX)
            if split_at == -1:
                split_at = MAX
            await message.reply(text[:split_at], mention_author=False)
            text = text[split_at:].lstrip()
        await message.reply(text, mention_author=False)

    # ======================================================
    # Обработка сообщений
    # ======================================================

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return

        content = message.content.strip()
        lower   = content.lower()
        prompt  = None

        if lower.startswith("широ,"):
            prompt = content[5:].strip()
        elif lower.startswith("широ "):
            prompt = content[5:].strip()
        elif lower.startswith("shiro,"):
            prompt = content[6:].strip()
        elif lower.startswith("shiro "):
            prompt = content[6:].strip()

        if prompt is None:
            return

        if prompt == "":
            await message.reply("Да? 😊", mention_author=False)
            return

        async with message.channel.typing():
            try:
                answer = await self.ask_groq(message.author.id, prompt)
            except Exception as error:
                log.error(f"[ai] Groq error: {error}")
                await message.reply(
                    f"⚠ Ошибка обращения к Groq API\n\n{error}",
                    mention_author=False,
                )
                return

            if not answer:
                await message.reply("Не удалось получить ответ 😔", mention_author=False)
                return

            await self.send_long_message(message, answer)


# ==========================================================
# Загрузка Cog
# ==========================================================

async def setup(bot: commands.Bot):
    if not GROQ_API_KEY:
        raise ValueError("[ai] GROQ_API_KEY не задан в переменных окружения")
    await bot.add_cog(AI(bot))