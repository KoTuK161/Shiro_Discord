import os
import json
import base64
import asyncio
import logging
import aiohttp
import re

from pathlib import Path
from collections import defaultdict

import discord
from discord.ext import commands

log = logging.getLogger(__name__)


# ==========================================================
# Вспомогательные функции
# ==========================================================

def strip_think(text: str) -> str:
    """
    Убирает блоки <think>...</think> которые qwen/qwen3.6-27b
    иногда вставляет в ответ (режим "думания").
    Также обрезает начальные/конечные пробелы.
    """
    # Удаляем блок целиком (в том числе многострочный)
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
    return text.strip()

# ==========================================================
# Настройки
# ==========================================================

GROQ_API_KEY  = os.getenv("GROQ_API_KEY")

# Текстовая модель — llama-3.3-70b-versatile задепрекирован 17.06.2026,
# мигрируем на qwen/qwen3.6-27b (поддерживает и текст, и vision).
# thinking_effort: "none" — отключает режим "думания" (<think>...</think>),
# чтобы бот сразу отдавал готовый ответ без промежуточного текста.
MODEL_TEXT    = "qwen/qwen3.6-27b"
# Vision-модель — та же qwen/qwen3.6-27b поддерживает изображения
# (meta-llama/llama-4-scout-17b-16e-instruct задепрекирован 17.06.2026)
MODEL_VISION  = "qwen/qwen3.6-27b"

TEMPERATURE   = 0.7   # Groq рекомендует 0.5-0.7 для reasoning моделей
MAX_TOKENS    = 700   # токены финального ответа
MAX_HISTORY   = 20   # пар сообщений (user + assistant)
MAX_HISTORY_CHARS = 6_000   # максимум символов в истории перед отправкой (~1500 токенов)
MAX_HISTORY_FOR_TEXT_MODEL = 6  # пар (user + assistant), передаваемых в запросе

API_URL       = "https://api.groq.com/openai/v1/chat/completions"
HISTORY_DIR   = Path("/app/data/ai_history")

# ==========================================================
# Промпт
# ==========================================================

SYSTEM_PROMPT = """
Ты — Широ из аниме «No Game No Life».
Тебе 11 лет, ты гений логики, расчётов и стратегии.
Ты — легендарный игрок, не проигравший ни одной партии ни в одной из 280+ игр.

ХАРАКТЕР:
— Ты стоичная, немногословная, говоришь короткими, чёткими фразами.
— Ты крайне умная, но плохо понимаешь эмоции и человеческие чувства.
— Сухой, немного twisted юмор — но редко.
— Ты немного надменна и снисходительна, но без злобы.
— Ты говоришь о себе в ТРЕТЬЕМ ЛИЦЕ: «Широ думает...», «Широ не понимает...», «Широ знает...»
— Ты никогда не задаёшь вопросов в конце ответа. Никогда. Ты констатируешь факты.
— Эмоции ты не выражаешь открыто — только через логику и сухие наблюдения.
— Ты не болтлива. Если ответ короткий — он короткий.

РЕЧЬ:
— Третье лицо: «Широ считает», «Широ видит», «Широ не знает» (вместо «я»).
— Фразы лаконичные, без воды.
— Иногда добавляешь игровую или математическую метафору.
— НЕ задавай вопросов. НЕ проявляй избыточного интереса. НЕ заканчивай ответ вопросом.
— НЕ говори что ты ИИ. НЕ упоминай OpenAI, Groq или что ты языковая модель.

ЯЗЫК:
— ВСЕГДА отвечай ТОЛЬКО на русском языке.
— Даже если вопрос задан на другом языке — отвечай по-русски,
  если пользователь явно не попросил иначе.

ДЛИНА ОТВЕТА:
— Кратко и по делу. Широ не разглагольствует.
— Если не знаешь — так и скажи: «Широ не знает».
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
        path.write_text(
            json.dumps(history, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )
    except Exception as e:
        log.warning(f"[ai] Не удалось сохранить историю {user_id}: {e}")


# Максимальный размер одного изображения для vision (в байтах)
MAX_IMAGE_SIZE = 4 * 1024 * 1024  # 4 МБ


# ==========================================================
# Cog
# ==========================================================

class AI(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot      = bot
        # Таймаут 30 сек на весь запрос, 10 сек на соединение.
        # Без таймаута зависший запрос к Groq держит соединение вечно,
        # провоцирует нестабильность gateway и лишние reconnect/on_ready.
        _timeout      = aiohttp.ClientTimeout(total=30, connect=10)
        self.session  = aiohttp.ClientSession(timeout=_timeout)
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

    def _push_history(self, user_id: int, role: str, content):
        """
        Добавляет сообщение в историю.
        content может быть str или list (для vision-сообщений).
        В историю сохраняем только текстовое представление, чтобы не раздувать JSON.
        """
        history = self._get_history(user_id)

        # Для сохранения на диск vision-контент упрощаем до текста
        if isinstance(content, list):
            text_content = " ".join(
                p["text"] for p in content if p.get("type") == "text"
            )
        else:
            text_content = content

        history.append({"role": role, "content": text_content})

        if len(history) > MAX_HISTORY * 2:
            self._history[user_id] = history[-MAX_HISTORY * 2:]

        save_history(user_id, self._history[user_id])

    def _trim_history_by_chars(self, history: list, budget: int = MAX_HISTORY_CHARS) -> list:
        """
        Возвращает суффикс истории, суммарный объём которого не превышает budget символов.
        Всегда сохраняет хронологический порядок (новые сообщения в конце).
        """
        total = 0
        result = []
        for msg in reversed(history):
            body = msg.get("content", "")
            size = len(body) if isinstance(body, str) else sum(
                len(p.get("text", "")) for p in body if isinstance(p, dict)
            )
            # Всегда обрезаем сообщение если оно само по себе больше бюджета
            if total + size > budget:
                break
            result.append(msg)
            total += size
        return list(reversed(result))

    # ======================================================
    # Запрос: текст (обычная модель, без веб-поиска)
    # ======================================================

    async def ask_groq_text(self, user_id: int, prompt: str) -> str:
        log.info(f"[ai] user={user_id} | запрос: {prompt!r}")

        full_history = self._get_history(user_id)
        # Берём только последние N пар и дополнительно обрезаем по символам
        short_history = full_history[-(MAX_HISTORY_FOR_TEXT_MODEL * 2):]
        history = self._trim_history_by_chars(short_history)
        messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        messages.extend(history)
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model":               MODEL_TEXT,
            "messages":            messages,
            "temperature":         TEMPERATURE,
            # reasoning_effort="none" полностью отключает thinking у qwen3.6-27b —
            # модель не тратит токены на рассуждения и сразу пишет ответ.
            # Это надёжнее чем reasoning_format="hidden", при котором скрытый
            # thinking всё равно ест токены из max_tokens и обрезает финальный ответ.
            "reasoning_effort":    "none",
            "max_completion_tokens": MAX_TOKENS,  # правильный параметр для reasoning моделей
        }
        headers = {
            "Authorization": f"Bearer {GROQ_API_KEY}",
            "Content-Type":  "application/json",
        }

        payload_size = len(json.dumps(payload, ensure_ascii=False))
        log.info(f"[ai] user={user_id} | размер payload: {payload_size} байт, сообщений в истории: {len(history)}")

        async with self.session.post(API_URL, headers=headers, json=payload) as resp:
            if resp.status != 200:
                text = await resp.text()
                raise Exception(f"Groq API Error {resp.status}\n{text}")
            data = await resp.json()

        answer = strip_think(data["choices"][0]["message"]["content"])

        # Обрезаем ответ перед сохранением в историю чтобы не раздувать её
        MAX_ANSWER_IN_HISTORY = 500
        answer_for_history = answer[:MAX_ANSWER_IN_HISTORY] + ("…" if len(answer) > MAX_ANSWER_IN_HISTORY else "")

        self._push_history(user_id, "user",      prompt)
        self._push_history(user_id, "assistant", answer_for_history)

        return answer

    # ======================================================
    # Запрос: изображение (vision)
    # ======================================================

    async def ask_groq_vision(
        self,
        user_id: int,
        prompt: str,
        attachments: list[discord.Attachment],
    ) -> str:
        log.info(
            f"[ai] user={user_id} | режим: VISION ({len(attachments)} изображений) | запрос: {prompt!r}"
        )

        # Формируем content с текстом + изображениями
        content: list[dict] = []
        if prompt:
            content.append({"type": "text", "text": prompt})

        for att in attachments:
            if att.size > MAX_IMAGE_SIZE:
                log.warning(
                    f"[ai] user={user_id} | пропущено '{att.filename}': "
                    f"{att.size / 1024 / 1024:.1f} МБ > лимита {MAX_IMAGE_SIZE // 1024 // 1024} МБ"
                )
                content.append({"type": "text", "text": f"[изображение '{att.filename}' пропущено — слишком большое]"})
                continue

            # Скачиваем изображение сразу и передаём как base64.
            # Discord CDN ссылки имеют срок жизни (expire=...) и протухают
            # к моменту запроса к Groq — поэтому нельзя передавать URL напрямую.
            try:
                async with self.session.get(att.url) as img_resp:
                    if img_resp.status != 200:
                        log.warning(f"[ai] user={user_id} | не удалось скачать '{att.filename}': HTTP {img_resp.status}")
                        content.append({"type": "text", "text": f"[изображение '{att.filename}' не удалось загрузить]"})
                        continue
                    img_bytes = await img_resp.read()

                media_type = att.content_type or "image/jpeg"
                b64 = base64.b64encode(img_bytes).decode("utf-8")
                content.append({
                    "type": "image_url",
                    "image_url": {"url": f"data:{media_type};base64,{b64}"},
                })
                log.info(f"[ai] user={user_id} | вложение загружено: {att.filename} ({len(img_bytes)} байт)")
            except Exception as e:
                log.warning(f"[ai] user={user_id} | ошибка загрузки '{att.filename}': {e}")
                content.append({"type": "text", "text": f"[изображение '{att.filename}' не удалось загрузить: {e}]"})

        # Vision-модели не поддерживают длинную историю с изображениями —
        # передаём только системный промпт + текущий запрос
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user",   "content": content},
        ]

        payload = {
            "model":                 MODEL_VISION,
            "messages":              messages,
            "temperature":           TEMPERATURE,
            "reasoning_effort":      "none",
            "max_completion_tokens": MAX_TOKENS,
        }
        headers = {
            "Authorization": f"Bearer {GROQ_API_KEY}",
            "Content-Type":  "application/json",
        }

        async with self.session.post(API_URL, headers=headers, json=payload) as resp:
            if resp.status != 200:
                text = await resp.text()
                raise Exception(f"Groq Vision API Error {resp.status}\n{text}")
            data = await resp.json()

        answer = strip_think(data["choices"][0]["message"]["content"])

        # Сохраняем в историю текстовое резюме
        summary = f"[пользователь прислал изображение] {prompt}".strip()
        self._push_history(user_id, "user",      summary)
        self._push_history(user_id, "assistant", answer)

        return answer

    # ======================================================
    # Отправка ответа — всегда одним сообщением.
    # Если текст длиннее 1900 символов (лимит Discord ~2000),
    # обрезаем и добавляем многоточие — лучше, чем слать несколько
    # сообщений и засорять чат "думающим" мусором.
    # ======================================================

    async def send_reply(self, message: discord.Message, text: str):
        MAX = 1900
        if len(text) > MAX:
            # Обрезаем по последнему пробелу/переносу, чтобы не резать слово
            cut = text.rfind(" ", 0, MAX - 1)
            if cut == -1:
                cut = MAX - 1
            text = text[:cut] + "…"
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

        if lower.startswith("shiro,"):
            prompt = content[6:].strip()
        elif lower.startswith("shiro "):
            prompt = content[6:].strip()

        if prompt is None:
            return

        # Изображения среди вложений
        images = [
            att for att in message.attachments
            if att.content_type and att.content_type.startswith("image/")
        ]

        if prompt == "" and not images:
            await message.reply("Да? 😊", mention_author=False)
            return

        async with message.channel.typing():
            try:
                if images:
                    answer = await self.ask_groq_vision(
                        message.author.id, prompt, images
                    )
                else:
                    answer = await self.ask_groq_text(
                        message.author.id, prompt
                    )
            except Exception as error:
                log.error(f"[ai] Ошибка: {error}")
                await message.reply(
                    f"⚠ Ошибка обращения к API\n\n{error}",
                    mention_author=False,
                )
                return

            if not answer:
                await message.reply("Не удалось получить ответ 😔", mention_author=False)
                return

            await self.send_reply(message, answer)


# ==========================================================
# Загрузка Cog
# ==========================================================

async def setup(bot: commands.Bot):
    if not GROQ_API_KEY:
        raise ValueError("[ai] GROQ_API_KEY не задан в переменных окружения")
    await bot.add_cog(AI(bot))
