import asyncio
import json
import logging
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import chess
import discord
from discord import app_commands
from discord.ext import commands

log = logging.getLogger(__name__)

# ==========================================================
# НАСТРОЙКИ
# ==========================================================

CATEGORY_NAME = "♛ ШАХМАТЫ ♛"

DIFFICULTY_LEVELS = {
    "easy":   1,   # глубина поиска minimax
    "medium": 2,
    "hard":   3,
}

STATS_FILE = Path("/app/data/chess_stats.json")
GAMES_FILE = Path("/app/data/chess_games.json")

# ==========================================================
# Эмодзи фигур
# ==========================================================

PIECES = {
    (chess.KING,   chess.WHITE): "♔",
    (chess.QUEEN,  chess.WHITE): "♕",
    (chess.ROOK,   chess.WHITE): "♖",
    (chess.BISHOP, chess.WHITE): "♗",
    (chess.KNIGHT, chess.WHITE): "♘",
    (chess.PAWN,   chess.WHITE): "♙",
    (chess.KING,   chess.BLACK): "♚",
    (chess.QUEEN,  chess.BLACK): "♛",
    (chess.ROOK,   chess.BLACK): "♜",
    (chess.BISHOP, chess.BLACK): "♝",
    (chess.KNIGHT, chess.BLACK): "♞",
    (chess.PAWN,   chess.BLACK): "♟",
}

# ==========================================================
# Статистика
# ==========================================================

def load_stats() -> dict:
    if STATS_FILE.exists():
        try:
            return json.loads(STATS_FILE.read_text("utf-8"))
        except Exception:
            pass
    return {}


def save_stats(d: dict):
    STATS_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATS_FILE.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")


def get_player_stats(user_id: int) -> dict:
    d = load_stats()
    return d.get(str(user_id), {
        "bot": {"wins": 0, "draws": 0, "losses": 0},
        "pvp": {"wins": 0, "draws": 0, "losses": 0},
    })


def record_result(user_id: int, mode: str, result: str):
    """mode: 'bot' | 'pvp'. result: 'win' | 'draw' | 'loss'"""
    d   = load_stats()
    uid = str(user_id)
    if uid not in d:
        d[uid] = {
            "bot": {"wins": 0, "draws": 0, "losses": 0},
            "pvp": {"wins": 0, "draws": 0, "losses": 0},
        }
    key = {"win": "wins", "draw": "draws", "loss": "losses"}[result]
    d[uid][mode][key] += 1
    save_stats(d)


# ==========================================================
# Сохранение / восстановление активных партий
# ==========================================================

def load_saved_games() -> dict:
    if GAMES_FILE.exists():
        try:
            return json.loads(GAMES_FILE.read_text("utf-8"))
        except Exception:
            pass
    return {}


def save_games(games: dict):
    GAMES_FILE.parent.mkdir(parents=True, exist_ok=True)
    data = {}
    for chan_id, game in games.items():
        data[str(chan_id)] = {
            "fen":        game.board.fen(),
            "white_id":   game.white_id,
            "black_id":   game.black_id,
            "difficulty": game.difficulty,
            "vs_bot":     game.vs_bot,
            "channel_id": game.channel_id,
            "guild_id":   game.guild_id,
            "last_move":  game.last_move.uci() if game.last_move else None,
        }
    GAMES_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def delete_saved_game(chan_id: int):
    data = load_saved_games()
    key  = str(chan_id)
    if key in data:
        del data[key]
        GAMES_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


# ==========================================================
# Структура игры
# ==========================================================

@dataclass
class ChessGame:
    board:      chess.Board
    white_id:   int
    guild_id:   int
    black_id:   Optional[int]       = None
    channel_id: Optional[int]       = None
    difficulty: str                 = "medium"
    vs_bot:     bool                = True
    last_move:  Optional[chess.Move] = None


# Хранилище: channel_id -> ChessGame
active_games: dict[int, ChessGame] = {}


# ==========================================================
# Рендер доски — PNG через Pillow
# ==========================================================

import io
from PIL import Image, ImageDraw, ImageFont

PIECES_DIR  = Path("/app/pieces")   # папка с PNG фигурами
CELL_SIZE   = 80                    # размер клетки в пикселях
BORDER      = 40                    # отступ для координат
BOARD_SIZE  = CELL_SIZE * 8 + BORDER * 2

# Цвета доски
COLOR_LIGHT     = (240, 217, 181)   # светлая клетка
COLOR_DARK      = (181, 136,  99)   # тёмная клетка
COLOR_HIGHLIGHT = (205, 210,  60)   # подсветка последнего хода
COLOR_BORDER    = ( 99,  71,  50)   # рамка / фон координат
COLOR_TEXT      = (255, 255, 255)   # цвет координат

# Маппинг python-chess → имя файла фигуры
PIECE_FILE = {
    (chess.KING,   chess.WHITE): "wK",
    (chess.QUEEN,  chess.WHITE): "wQ",
    (chess.ROOK,   chess.WHITE): "wR",
    (chess.BISHOP, chess.WHITE): "wB",
    (chess.KNIGHT, chess.WHITE): "wN",
    (chess.PAWN,   chess.WHITE): "wP",
    (chess.KING,   chess.BLACK): "bK",
    (chess.QUEEN,  chess.BLACK): "bQ",
    (chess.ROOK,   chess.BLACK): "bR",
    (chess.BISHOP, chess.BLACK): "bB",
    (chess.KNIGHT, chess.BLACK): "bN",
    (chess.PAWN,   chess.BLACK): "bP",
}

# Кэш загруженных фигур
_piece_cache: dict[str, Image.Image] = {}


def _load_piece(name: str) -> Optional[Image.Image]:
    if name in _piece_cache:
        return _piece_cache[name]
    path = PIECES_DIR / f"{name}.png"
    if not path.exists():
        log.warning(f"[chess] Файл фигуры не найден: {path}")
        return None
    img = Image.open(path).convert("RGBA").resize((CELL_SIZE, CELL_SIZE), Image.LANCZOS)
    _piece_cache[name] = img
    return img


def render_board_image(board: chess.Board, last_move: Optional[chess.Move] = None) -> discord.File:
    """Генерирует PNG изображение доски и возвращает discord.File."""
    highlight = set()
    if last_move:
        highlight.add(last_move.from_square)
        highlight.add(last_move.to_square)

    img  = Image.new("RGB", (BOARD_SIZE, BOARD_SIZE), COLOR_BORDER)
    draw = ImageDraw.Draw(img)

    # Пробуем загрузить шрифт, fallback на дефолтный
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 20)
    except Exception:
        font = ImageFont.load_default()

    # Рисуем клетки
    for rank in range(8):
        for file in range(8):
            sq = chess.square(file, rank)
            x  = BORDER + file * CELL_SIZE
            y  = BORDER + (7 - rank) * CELL_SIZE

            if sq in highlight:
                color = COLOR_HIGHLIGHT
            elif (rank + file) % 2 == 0:
                color = COLOR_DARK
            else:
                color = COLOR_LIGHT

            draw.rectangle([x, y, x + CELL_SIZE, y + CELL_SIZE], fill=color)

    # Рисуем фигуры
    for rank in range(8):
        for file in range(8):
            sq    = chess.square(file, rank)
            piece = board.piece_at(sq)
            if not piece:
                continue
            name     = PIECE_FILE.get((piece.piece_type, piece.color))
            piece_img = _load_piece(name) if name else None
            if piece_img:
                x = BORDER + file * CELL_SIZE
                y = BORDER + (7 - rank) * CELL_SIZE
                img.paste(piece_img, (x, y), piece_img)

    # Координаты — буквы снизу
    files_letters = "abcdefgh"
    for file in range(8):
        x = BORDER + file * CELL_SIZE + CELL_SIZE // 2
        draw.text((x, BOARD_SIZE - BORDER // 2 - 8), files_letters[file],
                  fill=COLOR_TEXT, font=font, anchor="mm")
        draw.text((x, BORDER // 2 - 2), files_letters[file],
                  fill=COLOR_TEXT, font=font, anchor="mm")

    # Координаты — цифры слева
    for rank in range(8):
        y = BORDER + (7 - rank) * CELL_SIZE + CELL_SIZE // 2
        draw.text((BORDER // 2, y), str(rank + 1),
                  fill=COLOR_TEXT, font=font, anchor="mm")
        draw.text((BOARD_SIZE - BORDER // 2, y), str(rank + 1),
                  fill=COLOR_TEXT, font=font, anchor="mm")

    # Сохраняем в буфер
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return discord.File(buf, filename="board.png")


def build_embed(
    game: ChessGame,
    title: str = None,
    description: str = None,
) -> tuple[discord.Embed, discord.File]:
    """Возвращает (embed, file) — embed ссылается на attachment://board.png."""
    turn    = "Белые" if game.board.turn == chess.WHITE else "Чёрные"
    turn_id = game.white_id if game.board.turn == chess.WHITE else game.black_id

    if game.vs_bot and game.board.turn == chess.BLACK:
        turn_str = f"{turn} (🤖 бот)"
    else:
        turn_str = f"{turn} (<@{turn_id}>)"

    color = 0xf0d9b5 if game.board.turn == chess.WHITE else 0xb58863
    embed = discord.Embed(title=title or "♟️ Шахматы", color=color)
    embed.set_image(url="attachment://board.png")

    info = [f"**Ход:** {turn_str}"]
    if game.last_move:
        info.append(f"**Последний ход:** `{game.last_move.uci()}`")
    if game.board.is_check():
        info.append("⚠️ **Шах!**")
    if not game.vs_bot:
        info.append(f"**Белые:** <@{game.white_id}>  |  **Чёрные:** <@{game.black_id}>")
    else:
        info.append(f"**Сложность:** {game.difficulty}")

    embed.add_field(name="Статус", value="\n".join(info), inline=False)
    if description:
        embed.add_field(name="Сообщение", value=description, inline=False)
    embed.set_footer(text="/chess move e2e4 — сделать ход  |  /chess resign — сдаться")

    board_file = render_board_image(game.board, game.last_move)
    return embed, board_file


# ==========================================================
# Встроенный ИИ (Minimax + Alpha-Beta)
# ==========================================================

# Ценность фигур
PIECE_VALUES = {
    chess.PAWN:   100,
    chess.KNIGHT: 320,
    chess.BISHOP: 330,
    chess.ROOK:   500,
    chess.QUEEN:  900,
    chess.KING:   20000,
}

# Бонусные таблицы позиций для белых (для чёрных — зеркально)
PAWN_TABLE = [
     0,  0,  0,  0,  0,  0,  0,  0,
    50, 50, 50, 50, 50, 50, 50, 50,
    10, 10, 20, 30, 30, 20, 10, 10,
     5,  5, 10, 25, 25, 10,  5,  5,
     0,  0,  0, 20, 20,  0,  0,  0,
     5, -5,-10,  0,  0,-10, -5,  5,
     5, 10, 10,-20,-20, 10, 10,  5,
     0,  0,  0,  0,  0,  0,  0,  0,
]
KNIGHT_TABLE = [
    -50,-40,-30,-30,-30,-30,-40,-50,
    -40,-20,  0,  0,  0,  0,-20,-40,
    -30,  0, 10, 15, 15, 10,  0,-30,
    -30,  5, 15, 20, 20, 15,  5,-30,
    -30,  0, 15, 20, 20, 15,  0,-30,
    -30,  5, 10, 15, 15, 10,  5,-30,
    -40,-20,  0,  5,  5,  0,-20,-40,
    -50,-40,-30,-30,-30,-30,-40,-50,
]
BISHOP_TABLE = [
    -20,-10,-10,-10,-10,-10,-10,-20,
    -10,  0,  0,  0,  0,  0,  0,-10,
    -10,  0,  5, 10, 10,  5,  0,-10,
    -10,  5,  5, 10, 10,  5,  5,-10,
    -10,  0, 10, 10, 10, 10,  0,-10,
    -10, 10, 10, 10, 10, 10, 10,-10,
    -10,  5,  0,  0,  0,  0,  5,-10,
    -20,-10,-10,-10,-10,-10,-10,-20,
]
ROOK_TABLE = [
     0,  0,  0,  0,  0,  0,  0,  0,
     5, 10, 10, 10, 10, 10, 10,  5,
    -5,  0,  0,  0,  0,  0,  0, -5,
    -5,  0,  0,  0,  0,  0,  0, -5,
    -5,  0,  0,  0,  0,  0,  0, -5,
    -5,  0,  0,  0,  0,  0,  0, -5,
    -5,  0,  0,  0,  0,  0,  0, -5,
     0,  0,  0,  5,  5,  0,  0,  0,
]
QUEEN_TABLE = [
    -20,-10,-10, -5, -5,-10,-10,-20,
    -10,  0,  0,  0,  0,  0,  0,-10,
    -10,  0,  5,  5,  5,  5,  0,-10,
     -5,  0,  5,  5,  5,  5,  0, -5,
      0,  0,  5,  5,  5,  5,  0, -5,
    -10,  5,  5,  5,  5,  5,  0,-10,
    -10,  0,  5,  0,  0,  0,  0,-10,
    -20,-10,-10, -5, -5,-10,-10,-20,
]
KING_TABLE = [
    -30,-40,-40,-50,-50,-40,-40,-30,
    -30,-40,-40,-50,-50,-40,-40,-30,
    -30,-40,-40,-50,-50,-40,-40,-30,
    -30,-40,-40,-50,-50,-40,-40,-30,
    -20,-30,-30,-40,-40,-30,-30,-20,
    -10,-20,-20,-20,-20,-20,-20,-10,
     20, 20,  0,  0,  0,  0, 20, 20,
     20, 30, 10,  0,  0, 10, 30, 20,
]

PIECE_TABLES = {
    chess.PAWN:   PAWN_TABLE,
    chess.KNIGHT: KNIGHT_TABLE,
    chess.BISHOP: BISHOP_TABLE,
    chess.ROOK:   ROOK_TABLE,
    chess.QUEEN:  QUEEN_TABLE,
    chess.KING:   KING_TABLE,
}


def evaluate_board(board: chess.Board) -> int:
    """Оценивает позицию. Положительное — хорошо для белых."""
    if board.is_checkmate():
        return -99999 if board.turn == chess.WHITE else 99999
    if board.is_stalemate() or board.is_insufficient_material():
        return 0

    score = 0
    for sq in chess.SQUARES:
        piece = board.piece_at(sq)
        if not piece:
            continue
        value = PIECE_VALUES.get(piece.piece_type, 0)
        table = PIECE_TABLES.get(piece.piece_type, [])
        if table:
            # Для белых — прямой индекс (a1=0), для чёрных — зеркально
            if piece.color == chess.WHITE:
                idx = (7 - chess.square_rank(sq)) * 8 + chess.square_file(sq)
            else:
                idx = chess.square_rank(sq) * 8 + chess.square_file(sq)
            pos_bonus = table[idx] if idx < len(table) else 0
        else:
            pos_bonus = 0

        if piece.color == chess.WHITE:
            score += value + pos_bonus
        else:
            score -= value + pos_bonus

    return score


def minimax(board: chess.Board, depth: int, alpha: int, beta: int, maximizing: bool) -> int:
    if depth == 0 or board.is_game_over():
        return evaluate_board(board)

    moves = list(board.legal_moves)
    # Сначала проверяем взятия — улучшает отсечение
    moves.sort(key=lambda m: board.is_capture(m), reverse=True)

    if maximizing:
        max_eval = -99999
        for move in moves:
            board.push(move)
            val = minimax(board, depth - 1, alpha, beta, False)
            board.pop()
            max_eval = max(max_eval, val)
            alpha = max(alpha, val)
            if beta <= alpha:
                break
        return max_eval
    else:
        min_eval = 99999
        for move in moves:
            board.push(move)
            val = minimax(board, depth - 1, alpha, beta, True)
            board.pop()
            min_eval = min(min_eval, val)
            beta = min(beta, val)
            if beta <= alpha:
                break
        return min_eval


async def ai_move(game: ChessGame) -> Optional[chess.Move]:
    """Выбирает лучший ход через minimax в отдельном потоке."""
    depth = DIFFICULTY_LEVELS.get(game.difficulty, 2)
    board = game.board.copy()

    def _find_best_move():
        moves     = list(board.legal_moves)
        if not moves:
            return None
        best_move  = None
        best_score = 99999  # бот играет чёрными — минимизирует
        random.shuffle(moves)  # рандомизация при равных оценках
        for move in moves:
            board.push(move)
            score = minimax(board, depth - 1, -99999, 99999, True)
            board.pop()
            if score < best_score:
                best_score = score
                best_move  = move
        return best_move

    loop = asyncio.get_event_loop()
    try:
        move = await loop.run_in_executor(None, _find_best_move)
        return move
    except Exception as e:
        log.error(f"[chess] Ошибка ИИ: {e}")
        moves = list(game.board.legal_moves)
        return random.choice(moves) if moves else None


# ==========================================================
# Результат партии
# ==========================================================

def get_game_result_text(board: chess.Board) -> str:
    if board.is_checkmate():
        winner = "Чёрные" if board.turn == chess.WHITE else "Белые"
        return f"♟️ **Мат! Победили {winner}!**"
    if board.is_stalemate():
        return "🤝 **Пат! Ничья.**"
    if board.is_insufficient_material():
        return "🤝 **Ничья — недостаточно материала.**"
    if board.is_seventyfive_moves():
        return "🤝 **Ничья — правило 75 ходов.**"
    if board.is_fivefold_repetition():
        return "🤝 **Ничья — пятикратное повторение.**"
    return "🏳️ **Игра завершена.**"


def get_result_outcome(board: chess.Board, player_color: chess.Color) -> str:
    """Возвращает 'win' / 'draw' / 'loss' для игрока с player_color."""
    if board.is_checkmate():
        return "loss" if player_color == board.turn else "win"
    return "draw"


# ==========================================================
# Управление каналом / категорией
# ==========================================================

async def get_or_create_category(guild: discord.Guild) -> discord.CategoryChannel:
    for cat in guild.categories:
        if cat.name == CATEGORY_NAME:
            return cat
    cat = await guild.create_category(CATEGORY_NAME)
    log.info(f"[chess] Создана категория '{CATEGORY_NAME}' на {guild.name}")
    return cat


async def create_game_channel(
    guild:      discord.Guild,
    category:   discord.CategoryChannel,
    white:      discord.Member,
    black_name: str,
) -> discord.TextChannel:
    name = f"♟-{white.display_name}-vs-{black_name}".lower().replace(" ", "-")[:100]
    overwrites = {
        guild.default_role: discord.PermissionOverwrite(
            read_messages=True,
            send_messages=False,
        ),
        white: discord.PermissionOverwrite(
            read_messages=True,
            send_messages=True,
        ),
        guild.me: discord.PermissionOverwrite(
            read_messages=True,
            send_messages=True,
            manage_messages=True,
            manage_channels=True,
        ),
    }
    channel = await guild.create_text_channel(name, category=category, overwrites=overwrites)
    log.info(f"[chess] Создан канал {channel.name} ({channel.id})")
    return channel


async def cleanup_game(bot: commands.Bot, game: ChessGame):
    """Удаляет канал партии и категорию если она пуста."""
    delete_saved_game(game.channel_id)
    if game.channel_id in active_games:
        del active_games[game.channel_id]

    channel = bot.get_channel(game.channel_id)
    if not channel:
        return

    category = channel.category
    try:
        await channel.delete(reason="Шахматная партия завершена")
        log.info(f"[chess] Канал {game.channel_id} удалён")
    except Exception as e:
        log.error(f"[chess] Ошибка удаления канала: {e}")
        return

    # Удаляем категорию если каналов не осталось
    if category and category.name == CATEGORY_NAME:
        await asyncio.sleep(1)
        try:
            fresh_cat = bot.get_channel(category.id)
            if fresh_cat and len(fresh_cat.channels) == 0:
                await fresh_cat.delete(reason="Все шахматные партии завершены")
                log.info(f"[chess] Категория '{CATEGORY_NAME}' удалена")
        except Exception as e:
            log.error(f"[chess] Ошибка удаления категории: {e}")


# ==========================================================
# Cog
# ==========================================================

class Chess(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self):
        """Восстанавливаем активные партии из файла при запуске."""
        saved = load_saved_games()
        for chan_id_str, data in saved.items():
            try:
                board = chess.Board(data["fen"])
                lm    = chess.Move.from_uci(data["last_move"]) if data.get("last_move") else None
                game  = ChessGame(
                    board      = board,
                    white_id   = data["white_id"],
                    black_id   = data.get("black_id"),
                    guild_id   = data["guild_id"],
                    difficulty = data.get("difficulty", "medium"),
                    vs_bot     = data.get("vs_bot", True),
                    channel_id = data.get("channel_id"),
                    last_move  = lm,
                )
                active_games[int(chan_id_str)] = game
                log.info(f"[chess] Восстановлена партия в канале {chan_id_str}")
            except Exception as e:
                log.error(f"[chess] Не удалось восстановить партию {chan_id_str}: {e}")

    # -------------------------------------------------------
    # Удаление чужих сообщений
    # -------------------------------------------------------

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return
        game = active_games.get(message.channel.id)
        if not game:
            return
        allowed = {game.white_id}
        if game.black_id:
            allowed.add(game.black_id)
        if message.author.id not in allowed:
            try:
                await message.delete()
            except (discord.Forbidden, discord.HTTPException):
                pass

    # -------------------------------------------------------
    # /chess
    # -------------------------------------------------------

    @app_commands.command(name="chess", description="Шахматы — старт, ход, сдаться, статистика")
    @app_commands.describe(
        action="Действие: start / move / resign / stats",
        value="Для start: easy/medium/hard или @игрок. Для move: ход в формате e2e4"
    )
    @app_commands.choices(action=[
        app_commands.Choice(name="start",  value="start"),
        app_commands.Choice(name="move",   value="move"),
        app_commands.Choice(name="resign", value="resign"),
        app_commands.Choice(name="stats",  value="stats"),
    ])
    async def chess_cmd(
        self,
        interaction: discord.Interaction,
        action: str,
        value: str = None,
    ):
        if action == "start":
            await self._start(interaction, value)
        elif action == "move":
            await self._move(interaction, value)
        elif action == "resign":
            await self._resign(interaction)
        elif action == "stats":
            await self._stats(interaction)

    # -------------------------------------------------------
    # Старт
    # -------------------------------------------------------

    async def _start(self, interaction: discord.Interaction, value: str = None):
        guild = interaction.guild
        user  = interaction.user

        # Проверяем нет ли уже игры у этого пользователя
        for g in active_games.values():
            if user.id in (g.white_id, g.black_id) and g.guild_id == guild.id:
                await interaction.response.send_message(
                    "❌ У тебя уже есть активная партия. Завершите её командой `/chess resign`.",
                    ephemeral=True
                )
                return

        await interaction.response.defer(ephemeral=True)

        vs_bot     = True
        difficulty = "medium"
        black_id   = None
        opponent_member: Optional[discord.Member] = None

        if value and value.startswith("<@"):
            uid = int(value.strip("<@!>"))
            if uid == user.id:
                await interaction.followup.send("❌ Нельзя играть с самим собой.", ephemeral=True)
                return
            opponent_member = guild.get_member(uid)
            if not opponent_member or opponent_member.bot:
                await interaction.followup.send("❌ Укажите реального игрока.", ephemeral=True)
                return
            for g in active_games.values():
                if opponent_member.id in (g.white_id, g.black_id) and g.guild_id == guild.id:
                    await interaction.followup.send(
                        f"❌ У <@{opponent_member.id}> уже есть активная партия.",
                        ephemeral=True
                    )
                    return
            vs_bot   = False
            black_id = uid
        else:
            if value and value.lower() in DIFFICULTY_LEVELS:
                difficulty = value.lower()

        # Создаём категорию и канал
        try:
            category   = await get_or_create_category(guild)
            black_name = "бот" if vs_bot else opponent_member.display_name
            channel    = await create_game_channel(guild, category, user, black_name)
            if not vs_bot:
                await channel.set_permissions(
                    opponent_member,
                    read_messages=True,
                    send_messages=True
                )
        except discord.Forbidden:
            await interaction.followup.send(
                "❌ Нет прав для создания каналов. Выдайте боту право **Управление каналами**.",
                ephemeral=True
            )
            return

        game = ChessGame(
            board      = chess.Board(),
            white_id   = user.id,
            black_id   = black_id,
            guild_id   = guild.id,
            difficulty = difficulty,
            vs_bot     = vs_bot,
            channel_id = channel.id,
        )
        active_games[channel.id] = game
        save_games(active_games)

        if vs_bot:
            desc = f"<@{user.id}> играет **белыми** против 🤖 бота.\nСложность: **{difficulty}**"
        else:
            desc = f"<@{user.id}> (белые) ⚔️ <@{black_id}> (чёрные)"

        embed, board_file = build_embed(game, title="♟️ Новая партия!", description=desc)
        await channel.send(embed=embed, file=board_file)
        await interaction.followup.send(f"✅ Партия начата в {channel.mention}", ephemeral=True)

    # -------------------------------------------------------
    # Ход
    # -------------------------------------------------------

    async def _move(self, interaction: discord.Interaction, value: str = None):
        chan_id = interaction.channel_id
        game    = active_games.get(chan_id)

        if not game:
            await interaction.response.send_message(
                "❌ В этом канале нет активной игры.", ephemeral=True
            )
            return

        if not value:
            await interaction.response.send_message(
                "❌ Укажите ход, например: `e2e4`.", ephemeral=True
            )
            return

        user_id = interaction.user.id

        if game.board.turn == chess.WHITE and user_id != game.white_id:
            await interaction.response.send_message("❌ Сейчас не ваш ход.", ephemeral=True)
            return
        if game.board.turn == chess.BLACK:
            if game.vs_bot:
                await interaction.response.send_message("❌ Сейчас ход бота.", ephemeral=True)
                return
            if user_id != game.black_id:
                await interaction.response.send_message("❌ Сейчас не ваш ход.", ephemeral=True)
                return

        try:
            move = chess.Move.from_uci(value.lower().strip())
        except ValueError:
            await interaction.response.send_message(
                "❌ Неверный формат. Используйте UCI, например `e2e4`.", ephemeral=True
            )
            return

        if move not in game.board.legal_moves:
            await interaction.response.send_message("❌ Недопустимый ход.", ephemeral=True)
            return

        player_color = game.board.turn
        game.board.push(move)
        game.last_move = move
        save_games(active_games)

        if game.board.is_game_over():
            await self._finish_game(interaction, game, player_color, resigned=False)
            return

        if game.vs_bot:
            await interaction.response.defer()
            bot_move = await ai_move(game)
            if bot_move:
                game.board.push(bot_move)
                game.last_move = bot_move
                save_games(active_games)

            if game.board.is_game_over():
                await self._finish_game(
                    interaction, game, chess.WHITE, resigned=False, followup=True
                )
                return

            embed, board_file = build_embed(game)
            await interaction.followup.send(embed=embed, file=board_file)
        else:
            next_id           = game.black_id if game.board.turn == chess.BLACK else game.white_id
            embed, board_file = build_embed(game, description=f"Ход <@{next_id}>")
            await interaction.response.send_message(embed=embed, file=board_file)

    # -------------------------------------------------------
    # Завершение партии
    # -------------------------------------------------------

    async def _finish_game(
        self,
        interaction:    discord.Interaction,
        game:           ChessGame,
        player_color:   chess.Color,
        resigned:       bool,
        followup:       bool = False,
        resign_user_id: int  = None,
    ):
        if resigned:
            loser_id  = resign_user_id
            winner_id = game.black_id if loser_id == game.white_id else game.white_id
            if game.vs_bot and winner_id is None:
                result_text = f"🏳️ <@{loser_id}> сдался. Победил 🤖 бот!"
            else:
                result_text = f"🏳️ <@{loser_id}> сдался. Победил <@{winner_id}>!"
            mode = "bot" if game.vs_bot else "pvp"
            record_result(loser_id, mode, "loss")
            if not game.vs_bot and winner_id:
                record_result(winner_id, mode, "win")
        else:
            result_text = get_game_result_text(game.board)
            mode        = "bot" if game.vs_bot else "pvp"
            outcome     = get_result_outcome(game.board, chess.WHITE)
            record_result(game.white_id, mode, outcome)
            if not game.vs_bot and game.black_id:
                black_outcome = {"win": "loss", "loss": "win", "draw": "draw"}[outcome]
                record_result(game.black_id, mode, black_outcome)

        embed, board_file = build_embed(game, title="🏁 Игра завершена!", description=result_text)

        if followup:
            await interaction.followup.send(embed=embed, file=board_file)
        else:
            await interaction.response.send_message(embed=embed, file=board_file)

        await asyncio.sleep(5)
        await cleanup_game(self.bot, game)

    # -------------------------------------------------------
    # Сдаться
    # -------------------------------------------------------

    async def _resign(self, interaction: discord.Interaction):
        chan_id = interaction.channel_id
        game    = active_games.get(chan_id)

        if not game:
            await interaction.response.send_message(
                "❌ В этом канале нет активной игры.", ephemeral=True
            )
            return

        user_id = interaction.user.id
        if user_id not in (game.white_id, game.black_id):
            await interaction.response.send_message(
                "❌ Вы не участник этой игры.", ephemeral=True
            )
            return

        await self._finish_game(
            interaction, game,
            player_color   = chess.WHITE if user_id == game.white_id else chess.BLACK,
            resigned       = True,
            resign_user_id = user_id,
        )

    # -------------------------------------------------------
    # Статистика
    # -------------------------------------------------------

    async def _stats(self, interaction: discord.Interaction):
        stats = get_player_stats(interaction.user.id)
        b     = stats.get("bot", {"wins": 0, "draws": 0, "losses": 0})
        p     = stats.get("pvp", {"wins": 0, "draws": 0, "losses": 0})

        embed = discord.Embed(
            title=f"📊 Статистика {interaction.user.display_name}",
            color=0x5865f2
        )
        embed.add_field(
            name="🤖 Игры против бота",
            value=(
                f"> Побед: **{b['wins']}**\n"
                f"> Ничья: **{b['draws']}**\n"
                f"> Поражений: **{b['losses']}**"
            ),
            inline=False
        )
        embed.add_field(
            name="⚔️ Игры против игроков",
            value=(
                f"> Побед: **{p['wins']}**\n"
                f"> Ничья: **{p['draws']}**\n"
                f"> Поражений: **{p['losses']}**"
            ),
            inline=False
        )
        embed.set_thumbnail(url=interaction.user.display_avatar.url)
        await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(Chess(bot))
