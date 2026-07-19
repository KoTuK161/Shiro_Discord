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
# Суперадмин — всегда имеет доступ на всех серверах
SUPERADMIN_ID = 629953087586566164

# ==========================================================
# Дефолтные значения для новых серверов
# ==========================================================
DEFAULTS = {
    "rank_channel_id":      None,   # ALLOWED_CHANNELS для /rank, /rankuid и т.д.
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

def get_guild_admins(guild_id) -> set:
    """Возвращает множество ID локальных админов сервера."""
    d    = load_panel()
    cfg  = d.get(str(guild_id), {})
    return set(cfg.get("admins", []))


async def check_admin(interaction: discord.Interaction) -> bool:
    if interaction.user.id == SUPERADMIN_ID:
        return True
    if interaction.user.id in get_guild_admins(interaction.guild_id):
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
    # /adm_id — добавить/удалить локального администратора
    # -------------------------------------------------------

    @app_commands.command(name="adm_id", description="Добавить или удалить администратора бота на этом сервере")
    @app_commands.describe(user="Пользователь Discord")
    async def adm_id(self, interaction: discord.Interaction, user: discord.Member):
        # Только суперадмин может управлять локальными админами
        if interaction.user.id != SUPERADMIN_ID:
            await interaction.response.send_message("❌ Только суперадмин может управлять администраторами.", ephemeral=True)
            return

        d   = load_panel()
        gid = str(interaction.guild_id)
        if gid not in d:
            d[gid] = {}
        admins = set(d[gid].get("admins", []))

        if user.id in admins:
            admins.discard(user.id)
            d[gid]["admins"] = list(admins)
            save_panel(d)
            await interaction.response.send_message(
                f"🗑️ {user.mention} удалён из администраторов бота на этом сервере.", ephemeral=True
            )
        else:
            admins.add(user.id)
            d[gid]["admins"] = list(admins)
            save_panel(d)
            await interaction.response.send_message(
                f"✅ {user.mention} добавлен в администраторы бота на этом сервере.", ephemeral=True
            )

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
        embed.add_field(name="/adm_id @пользователь",
            value="Добавить или удалить локального администратора бота на этом сервере. Только для суперадмина.", inline=False)
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

    @commands.Cog.listener()
    async def on_guild_join(self, guild: discord.Guild):
        """При добавлении бота на сервер — выдаём админку владельцу."""
        if not guild.owner_id:
            return
        d   = load_panel()
        gid = str(guild.id)
        if gid not in d:
            d[gid] = {}
        admins = set(d[gid].get("admins", []))
        if guild.owner_id not in admins:
            admins.add(guild.owner_id)
            d[gid]["admins"] = list(admins)
            save_panel(d)


async def setup(bot: commands.Bot):
    await bot.add_cog(AdmPanel(bot))
