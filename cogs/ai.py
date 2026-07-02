import os
import asyncio
import aiohttp

from collections import defaultdict

import discord
from discord.ext import commands

# ==========================================================
# Настройки
# ==========================================================

GROQ_API_KEY = os.getenv("GROQ_API_KEY")

MODEL = "llama-3.3-70b-versatile"

TEMPERATURE = 0.85

MAX_TOKENS = 700

MAX_HISTORY = 20

API_URL = "https://api.groq.com/openai/v1/chat/completions"

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
# История диалогов
# ==========================================================

user_history = defaultdict(list)


# ==========================================================
# Cog
# ==========================================================

class AI(commands.Cog):

    def __init__(self, bot):

        self.bot = bot

        self.session = aiohttp.ClientSession()

    def cog_unload(self):

        asyncio.create_task(self.session.close())

    # ======================================================

    async def ask_groq(
            self,
            user_id: int,
            prompt: str
    ):

        history = user_history[user_id]

        messages = [

            {
                "role": "system",
                "content": SYSTEM_PROMPT
            }

        ]

        messages.extend(history)

        messages.append(

            {
                "role": "user",
                "content": prompt
            }

        )

        payload = {

            "model": MODEL,

            "messages": messages,

            "temperature": TEMPERATURE,

            "max_tokens": MAX_TOKENS

        }

        headers = {

            "Authorization": f"Bearer {GROQ_API_KEY}",

            "Content-Type": "application/json"

        }

        async with self.session.post(

                API_URL,

                headers=headers,

                json=payload

        ) as response:
            if response.status != 200:

                text = await response.text()

                raise Exception(
                    f"Groq API Error {response.status}\n{text}"
                )

            data = await response.json()

        answer = data["choices"][0]["message"]["content"].strip()

        # ----------------------------------------
        # сохраняем историю
        # ----------------------------------------

        history.append(

            {
                "role": "user",
                "content": prompt
            }

        )

        history.append(

            {
                "role": "assistant",
                "content": answer
            }

        )

        if len(history) > MAX_HISTORY * 2:

            user_history[user_id] = history[-MAX_HISTORY * 2:]

        return answer

    # ======================================================

    async def send_long_message(

            self,

            message: discord.Message,

            text: str

    ):

        MAX = 1900

        while len(text) > MAX:

            part = text[:MAX]

            await message.reply(

                part,

                mention_author=False

            )

            text = text[MAX:]

        await message.reply(

            text,

            mention_author=False

        )

    # ======================================================

    @commands.Cog.listener()

    async def on_message(

            self,

            message: discord.Message

    ):

        if message.author.bot:

            return

        content = message.content.strip()

        lower = content.lower()

        trigger = False

        prompt = ""

        if lower.startswith("широ "):

            trigger = True

            prompt = content[5:].strip()

        elif lower.startswith("широ,"):

            trigger = True

            prompt = content[6:].strip()

        elif lower.startswith("shiro "):

            trigger = True

            prompt = content[6:].strip()

        elif lower.startswith("shiro,"):

            trigger = True

            prompt = content[7:].strip()

        if not trigger:

            return

        if prompt == "":

            await message.reply(

                "Да? 😊",

                mention_author=False

            )

            return

        async with message.channel.typing():
            try:

                answer = await self.ask_groq(

                    message.author.id,

                    prompt

                )

            except Exception as error:

                await message.reply(

                    f"⚠ Ошибка обращения к Groq API\n\n{error}",

                    mention_author=False

                )

                return

            if not answer:

                await message.reply(

                    "Не удалось получить ответ 😔",

                    mention_author=False

                )

                return

            await self.send_long_message(

                message,

                answer

            )
# ==========================================================
# Загрузка Cog
# ==========================================================

async def setup(bot: commands.Bot):

    await bot.add_cog(

        AI(bot)

    )