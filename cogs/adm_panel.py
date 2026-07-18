import json
import asyncio
import logging
from pathlib import Path
import discord
from discord import app_commands
from discord.ext import commands

log = logging.getLogger(__name__)

# ==========================================================
# Путь к файлу настроек
# ==========================================================
DATA_FILE = Path("/app/data/adm_panel.json")

# ==========================================================
# Пользователи с доступом к /adm_* командам
# Замени на свои реальные ID
# ==========================================================
RANK_LIST_ADMINS = {
    629953087586566164,
    111111111111111111,
    222222222222222222,
}

# ==========================================================
# Дефолтные значения для новых серверов
# ==========================================================
DEFAULTS = {
    "rank_channel_id":      None,   # ALLOWED_CHANNELS для /rank, /rankuid и т.д.
    "map_channel_id":       None,   # ALLOWED_CHANNELS для /map
    "rank_list_channel_id": None,   # канал топ-листа
    "rank_list_delay":      900,    # интервал обновления топ-листа в секундах
    "shiro_react":          True,   # реакция бота на слова
}

# ==========================================================
# Загрузка / сохранение
# ==========================================================

def load_panel() -> dict:
    if DATA_FILE.exists():
        try:
            return json.loads(DATA_FILE.read_text("utf-8"))
        except Exception:
            pass
    return {}


def save_panel(d: dict):
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    DATA_FILE.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")


def get_guild_cfg(guild_id: int | str) -> dict:
    """Возвращает конфиг сервера с дефолтами."""
    d = load_panel()
    gid = str(guild_id)
    cfg = d.get(gid, {})
    return {**DEFAULTS, **cfg}


def set_guild_value(guild_id: int | str, key: str, value):
    d = load_panel()
    gid = str(guild_id)
    if gid not in d:
        d[gid] = {}
    d[gid][key] = value
    save_panel(d)


def delete_guild_value(guild_id: int | str, key: str):
    d = load_panel()
    gid = str(guild_id)
    if gid in d and key in d[gid]:
        del d[gid][key]
        save_panel(d)


# ==========================================================
# Проверка прав
# ==========================================================

async def check_admin(interaction: discord.Interaction) -> bool:
    if interaction.user.id in RANK_LIST_ADMINS:
        return True
    await interaction.response.send_message(
        "❌ У тебя нет доступа к этой команде.", ephemeral=True
    )
    return False


# ==========================================================
# Cog
# ==========================================================

class AdmPanel(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # -------------------------------------------------------
    # /adm_help
    # -------------------------------------------------------

    @app_commands.command(name="adm_help", description="Список команд администратора")
    async def adm_help(self, interaction: discord.Interaction):
        if not await check_admin(interaction):
            return

        embed = discord.Embed(
            title="⚙️ Панель администратора",
            color=0x5865f2
        )
        embed.add_field(name="/adm_help",
            value="Показать это сообщение.", inline=False)
        embed.add_field(name="/adm_shiro_react_on",
            value="Включить реакцию бота на ключевые слова (img/gif).", inline=False)
        embed.add_field(name="/adm_shiro_react_off",
            value="Выключить реакцию бота на ключевые слова.", inline=False)
        embed.add_field(name="/adm_rank_list_id <id>",
            value="Установить ID канала для автообновляемого топ-листа. Повторный ввод того же ID — удалит настройку.", inline=False)
        embed.add_field(name="/adm_rank_list_delay <секунды>",
            value="Изменить интервал обновления топ-листа (в секундах). По умолчанию: 900.", inline=False)
        embed.add_field(name="/adm_rank_id <id>",
            value="Установить ID канала для команд /rank, /rankuid, /rankds, /unrank. Повторный ввод того же ID — удалит настройку.", inline=False)
        embed.add_field(name="/adm_map_id <id>",
            value="Установить ID канала для команды /map. Повторный ввод того же ID — удалит настройку.", inline=False)
        embed.set_footer(text="Все команды /adm_* доступны только администраторам.")

        await interaction.response.send_message(embed=embed, ephemeral=True)

    # -------------------------------------------------------
    # /adm_shiro_react_on / off
    # -------------------------------------------------------

    @app_commands.command(name="adm_shiro_react_on", description="Включить реакцию бота на ключевые слова")
    async def adm_shiro_react_on(self, interaction: discord.Interaction):
        if not await check_admin(interaction):
            return
        set_guild_value(interaction.guild_id, "shiro_react", True)
        await interaction.response.send_message("✅ Реакция бота на ключевые слова **включена**.", ephemeral=True)

    @app_commands.command(name="adm_shiro_react_off", description="Выключить реакцию бота на ключевые слова")
    async def adm_shiro_react_off(self, interaction: discord.Interaction):
        if not await check_admin(interaction):
            return
        set_guild_value(interaction.guild_id, "shiro_react", False)
        await interaction.response.send_message("⛔ Реакция бота на ключевые слова **выключена**.", ephemeral=True)

    # -------------------------------------------------------
    # /adm_rank_list_id
    # -------------------------------------------------------

    @app_commands.command(name="adm_rank_list_id", description="Установить канал для топ-листа рангов")
    @app_commands.describe(channel_id="ID канала (повторный ввод того же ID удалит настройку)")
    async def adm_rank_list_id(self, interaction: discord.Interaction, channel_id: str):
        if not await check_admin(interaction):
            return
        if not channel_id.isdigit():
            await interaction.response.send_message("❌ ID должен состоять только из цифр.", ephemeral=True)
            return
        cfg = get_guild_cfg(interaction.guild_id)
        new_id = int(channel_id)
        if cfg.get("rank_list_channel_id") == new_id:
            delete_guild_value(interaction.guild_id, "rank_list_channel_id")
            await interaction.response.send_message("🗑️ Настройка канала топ-листа **удалена**.", ephemeral=True)
        else:
            set_guild_value(interaction.guild_id, "rank_list_channel_id", new_id)
            await interaction.response.send_message(f"✅ Канал топ-листа установлен: <#{new_id}>", ephemeral=True)

    # -------------------------------------------------------
    # /adm_rank_list_delay
    # -------------------------------------------------------

    @app_commands.command(name="adm_rank_list_delay", description="Изменить интервал обновления топ-листа (в секундах)")
    @app_commands.describe(seconds="Интервал в секундах (минимум 60)")
    async def adm_rank_list_delay(self, interaction: discord.Interaction, seconds: int):
        if not await check_admin(interaction):
            return
        if seconds < 60:
            await interaction.response.send_message("❌ Минимальный интервал — 60 секунд.", ephemeral=True)
            return
        set_guild_value(interaction.guild_id, "rank_list_delay", seconds)
        # Перезапускаем задачу в rank cog если она есть
        rank_cog = self.bot.cogs.get("Rank")
        if rank_cog:
            rank_cog.restart_updater()
        await interaction.response.send_message(
            f"✅ Интервал обновления топ-листа: **{seconds} сек** ({seconds//60} мин).", ephemeral=True
        )

    # -------------------------------------------------------
    # /adm_rank_id
    # -------------------------------------------------------

    @app_commands.command(name="adm_rank_id", description="Установить канал для команд /rank, /rankuid, /rankds, /unrank")
    @app_commands.describe(channel_id="ID канала (повторный ввод того же ID удалит настройку)")
    async def adm_rank_id(self, interaction: discord.Interaction, channel_id: str):
        if not await check_admin(interaction):
            return
        if not channel_id.isdigit():
            await interaction.response.send_message("❌ ID должен состоять только из цифр.", ephemeral=True)
            return
        cfg = get_guild_cfg(interaction.guild_id)
        new_id = int(channel_id)
        if cfg.get("rank_channel_id") == new_id:
            delete_guild_value(interaction.guild_id, "rank_channel_id")
            await interaction.response.send_message("🗑️ Настройка канала для rank-команд **удалена**.", ephemeral=True)
        else:
            set_guild_value(interaction.guild_id, "rank_channel_id", new_id)
            await interaction.response.send_message(f"✅ Канал для rank-команд установлен: <#{new_id}>", ephemeral=True)

    # -------------------------------------------------------
    # /adm_map_id
    # -------------------------------------------------------

    @app_commands.command(name="adm_map_id", description="Установить канал для команды /map")
    @app_commands.describe(channel_id="ID канала (повторный ввод того же ID удалит настройку)")
    async def adm_map_id(self, interaction: discord.Interaction, channel_id: str):
        if not await check_admin(interaction):
            return
        if not channel_id.isdigit():
            await interaction.response.send_message("❌ ID должен состоять только из цифр.", ephemeral=True)
            return
        cfg = get_guild_cfg(interaction.guild_id)
        new_id = int(channel_id)
        if cfg.get("map_channel_id") == new_id:
            delete_guild_value(interaction.guild_id, "map_channel_id")
            await interaction.response.send_message("🗑️ Настройка канала для /map **удалена**.", ephemeral=True)
        else:
            set_guild_value(interaction.guild_id, "map_channel_id", new_id)
            await interaction.response.send_message(f"✅ Канал для /map установлен: <#{new_id}>", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(AdmPanel(bot))
