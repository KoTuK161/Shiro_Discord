import asyncio
import io
import json
import logging
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands
from PIL import Image, ImageDraw, ImageFont

log = logging.getLogger(__name__)

# ==========================================================
# НАСТРОЙКИ
# ==========================================================

CATEGORY_NAME = "🃏 ДУРАК 🃏"
CARDS_DIR     = Path("/app/img/cards/basic")
STATS_FILE    = Path("/app/data/durak_stats.json")
GAMES_FILE    = Path("/app/data/durak_games.json")

CARD_W        = 140   # ширина карты на столе
CARD_H        = 200   # высота карты на столе
CARD_OVERLAP  = 45    # перекрытие карт в руке
PADDING       = 30    # отступы
HAND_OFFSET   = 10    # смещение карт в руке
HAND_NUM_OFFSET = 120  # отступ номера карты над картой в руке

# Цвета стола
COLOR_TABLE   = ( 53, 101,  77)   # зелёный стол
COLOR_BORDER  = ( 30,  60,  45)
COLOR_TEXT    = (255, 255, 255)
COLOR_HINT    = (255, 220,  80)
COLOR_ATTACK  = (255,  80,  80)
COLOR_DEFEND  = ( 80, 200, 255)

# ==========================================================
# Карты
# ==========================================================

SUITS      = ["clubs", "diamonds", "hearts", "spades"]
SUIT_SYM    = {"clubs": "♣", "diamonds": "♦", "hearts": "♥", "spades": "♠"}
# ASCII-замены для PIL (fallback-шрифты не знают Unicode-символы мастей)
SUIT_LETTER = {"clubs": "C", "diamonds": "D", "hearts": "H", "spades": "S"}
RANKS_36   = ["6", "7", "8", "9", "10", "jack", "queen", "king", "ace"]
RANKS_52   = ["2", "3", "4", "5", "6", "7", "8", "9", "10", "jack", "queen", "king", "ace"]

RANK_VALUE_36 = {r: i for i, r in enumerate(RANKS_36)}
RANK_VALUE_52 = {r: i for i, r in enumerate(RANKS_52)}

RANK_DISPLAY = {
    "2": "2", "3": "3", "4": "4", "5": "5",
    "6": "6", "7": "7", "8": "8", "9": "9", "10": "10",
    "jack": "J", "queen": "Q", "king": "K", "ace": "A",
}


@dataclass(frozen=True)
class Card:
    rank: str   # "6", "jack", "ace" и т.д.
    suit: str   # "clubs", "diamonds", "hearts", "spades"

    def filename(self) -> str:
        rank = self.rank + "_of_" if self.rank != self.rank else self.rank
        return f"{self.rank}_of_{self.suit}.png"

    def display(self) -> str:
        return f"{RANK_DISPLAY[self.rank]}{SUIT_SYM[self.suit]}"

    def display_img(self) -> str:
        """ASCII-safe display для PIL (буква масти вместо символа)."""
        return f"{RANK_DISPLAY[self.rank]}{SUIT_LETTER[self.suit]}"

    def beats(self, other: "Card", trump: str, rank_values: dict) -> bool:
        """Может ли эта карта побить другую."""
        if self.suit == trump and other.suit != trump:
            return True
        if self.suit == other.suit:
            return rank_values[self.rank] > rank_values[other.rank]
        return False


def make_deck(deck_size: int) -> list[Card]:
    ranks = RANKS_36 if deck_size == 36 else RANKS_52
    deck  = [Card(r, s) for r in ranks for s in SUITS]
    random.shuffle(deck)
    return deck


# ==========================================================
# Кэш изображений карт
# ==========================================================

_card_cache:  dict[str, Image.Image] = {}
_back_cache:  Optional[Image.Image]  = None


def _load_card_img(filename: str) -> Optional[Image.Image]:
    if filename in _card_cache:
        return _card_cache[filename]
    path = CARDS_DIR / filename
    if not path.exists():
        log.warning(f"[durak] Карта не найдена: {path}")
        return None
    img = Image.open(path).convert("RGBA").resize((CARD_W, CARD_H), Image.LANCZOS)
    _card_cache[filename] = img
    return img


def _load_back() -> Optional[Image.Image]:
    global _back_cache
    if _back_cache:
        return _back_cache
    path = CARDS_DIR / "back.png"
    if not path.exists():
        return None
    _back_cache = Image.open(path).convert("RGBA").resize((CARD_W, CARD_H), Image.LANCZOS)
    return _back_cache


def _font(size: int = 18):
    try:
        return ImageFont.truetype(
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", size
        )
    except Exception:
        return ImageFont.load_default()


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


def _default_stats() -> dict:
    return {
        "bot": {"wins": 0, "losses": 0, "draws": 0},
        "pvp": {"wins": 0, "losses": 0, "draws": 0},
    }


def get_player_stats(user_id: int) -> dict:
    return load_stats().get(str(user_id), _default_stats())


def record_result(user_id: int, mode: str, result: str):
    d   = load_stats()
    uid = str(user_id)
    if uid not in d:
        d[uid] = _default_stats()
    d[uid][mode][result] += 1
    save_stats(d)


# ==========================================================
# Сохранение партий
# ==========================================================

def _card_to_dict(c: Card) -> dict:
    return {"rank": c.rank, "suit": c.suit}


def _card_from_dict(d: dict) -> Card:
    return Card(d["rank"], d["suit"])


def save_games(games: dict):
    GAMES_FILE.parent.mkdir(parents=True, exist_ok=True)
    data = {}
    for chan_id, g in games.items():
        data[str(chan_id)] = {
            "deck":         [_card_to_dict(c) for c in g.deck],
            "trump":        g.trump,
            "trump_card":   _card_to_dict(g.trump_card) if g.trump_card else None,
            "hands":        {str(uid): [_card_to_dict(c) for c in h] for uid, h in g.hands.items()},
            "table_attack": [_card_to_dict(c) for c in g.table_attack],
            "table_defend": [(_card_to_dict(c) if c else None) for c in g.table_defend],
            "players":      g.players,
            "bot_players":  g.bot_players,
            "attacker_idx": g.attacker_idx,
            "defender_idx": g.defender_idx,
            "channel_id":   g.channel_id,
            "guild_id":     g.guild_id,
            "mode":         g.mode,
            "deck_size":    g.deck_size,
            "passed":       g.passed,
            "losers":       g.losers,
            "finished":     g.finished,
        }
    GAMES_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def load_saved_games() -> dict:
    if GAMES_FILE.exists():
        try:
            return json.loads(GAMES_FILE.read_text("utf-8"))
        except Exception:
            pass
    return {}


def delete_saved_game(chan_id: int):
    data = load_saved_games()
    if str(chan_id) in data:
        del data[str(chan_id)]
        GAMES_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


# ==========================================================
# Структура игры
# ==========================================================

@dataclass
class DurakGame:
    deck:         list[Card]
    trump:        str                      # масть козыря
    trump_card:   Optional[Card]           # нижняя карта колоды (козырь)
    hands:        dict[int, list[Card]]    # user_id -> карты
    table_attack: list[Card]               # карты атаки на столе
    table_defend: list[Optional[Card]]     # карты защиты (None = не отбита)
    players:      list[int]                # user_id по порядку (боты = отрицательные ID)
    bot_players:  list[int]                # ID ботов
    attacker_idx: int                      # индекс атакующего в players
    defender_idx: int                      # индекс защищающегося в players
    channel_id:   int
    guild_id:     int
    mode:         str                      # "classic" | "transfer"
    deck_size:    int                      # 36 | 52
    passed:       list[int]               # игроки которые пасуют в переводном
    losers:       list[int]               # выбывшие (дураки)
    finished:     bool = False

    @property
    def rank_values(self) -> dict:
        return RANK_VALUE_36 if self.deck_size == 36 else RANK_VALUE_52

    @property
    def attacker_id(self) -> int:
        return self.players[self.attacker_idx]

    @property
    def defender_id(self) -> int:
        return self.players[self.defender_idx]

    def active_players(self) -> list[int]:
        return [p for p in self.players if p not in self.losers]

    def is_bot(self, uid: int) -> bool:
        return uid in self.bot_players

    def next_player_idx(self, idx: int, skip: int = 1) -> int:
        active = self.active_players()
        if not active:
            return idx
        current = self.players[idx]
        if current not in active:
            current = active[0]
        pos = active.index(current)
        return self.players.index(active[(pos + skip) % len(active)])


# Хранилище: channel_id -> DurakGame
active_games: dict[int, DurakGame] = {}


# ==========================================================
# Рендер стола
# ==========================================================

def render_table(game: DurakGame, viewer_id: int) -> discord.File:
    """
    Рисует PNG:
    - сверху: карты соперников (рубашкой), количество карт, имена (заглушки — ID)
    - в центре: стол (атака и защита), колода, козырь
    - снизу: рука текущего игрока (viewer_id)
    """
    hand      = game.hands.get(viewer_id, [])
    n_table   = max(len(game.table_attack), 1)
    table_w   = n_table * (CARD_W + PADDING) + PADDING
    hand_w    = PADDING + max(len(hand), 1) * (CARD_W + 16) + PADDING
    img_w     = max(table_w, hand_w, 800)
    img_h     = CARD_H * 4 + PADDING * 6 + 60 + HAND_NUM_OFFSET + 60  # opponents / table / deck row / own hand + number labels + hand title

    img  = Image.new("RGB", (img_w, img_h), COLOR_TABLE)
    draw = ImageDraw.Draw(img)
    fn       = _font(28)   # надписи (имена соперников, Table:, Trump:)
    fn_s     = _font(24)   # подписи карт на столе, Deck:
    fn_num   = _font(32)   # номера карт в руке
    fn_label = _font(30)   # Your hand: [ROLE]
    back = _load_back()

    active = game.active_players()

    # ----------------------------------------------------------
    # Соперники сверху
    # ----------------------------------------------------------
    opponents = [p for p in active if p != viewer_id]
    opp_x = PADDING
    for opp in opponents:
        opp_hand  = game.hands.get(opp, [])
        role      = "[ATK]" if opp == game.attacker_id else ("[DEF]" if opp == game.defender_id else "")
        name_label = "Bot" if game.is_bot(opp) else "Player"
        name_text  = f"{role} {name_label} ({len(opp_hand)})".strip()
        draw.text((opp_x, PADDING), name_text, fill=COLOR_HINT, font=fn)
        for i, _ in enumerate(opp_hand[:10]):
            x = opp_x + i * (CARD_OVERLAP // 2)
            y = PADDING + 36
            if back:
                img.paste(back, (x, y), back)
            else:
                draw.rectangle([x, y, x + CARD_W, y + CARD_H], fill=(60, 60, 60))
        opp_x += max(len(opp_hand) * (CARD_OVERLAP // 2) + CARD_W + PADDING * 2, 160)

    # ----------------------------------------------------------
    # Стол (атака + защита)
    # ----------------------------------------------------------
    table_y = CARD_H + PADDING * 3 + 36
    draw.text((PADDING, table_y - 36), "Table:", fill=COLOR_TEXT, font=fn)

    for i, atk_card in enumerate(game.table_attack):
        x = PADDING + i * (CARD_W + PADDING)

        # Карта атаки
        atk_img = _load_card_img(atk_card.filename())
        if atk_img:
            img.paste(atk_img, (x, table_y), atk_img)
        draw.text((x + 2, table_y + CARD_H + 2), atk_card.display_img(),
                  fill=COLOR_ATTACK, font=fn_s)

        # Карта защиты (если есть)
        def_card = game.table_defend[i] if i < len(game.table_defend) else None
        if def_card:
            def_img = _load_card_img(def_card.filename())
            if def_img:
                img.paste(def_img, (x + 15, table_y + 15), def_img)
            draw.text((x + 17, table_y + CARD_H + 17), def_card.display_img(),
                      fill=COLOR_DEFEND, font=fn_s)

    # ----------------------------------------------------------
    # Колода и козырь
    # ----------------------------------------------------------
    deck_x = img_w - CARD_W - PADDING * 2
    deck_y = table_y
    if game.deck:
        if back:
            img.paste(back, (deck_x, deck_y), back)
        draw.text((deck_x, deck_y + CARD_H + 4),
                  f"Deck: {len(game.deck)}", fill=COLOR_TEXT, font=fn_s)
    if game.trump_card:
        trump_img = _load_card_img(game.trump_card.filename())
        if trump_img:
            img.paste(trump_img, (deck_x - CARD_W - 5, deck_y), trump_img)
        draw.text((deck_x - CARD_W - 5, deck_y + CARD_H + 4),
                  f"Trump: {SUIT_LETTER[game.trump]}", fill=COLOR_HINT, font=fn)

    # ----------------------------------------------------------
    # Рука игрока снизу
    # ----------------------------------------------------------
    hand_y    = img_h - CARD_H - PADDING
    if viewer_id == game.attacker_id:
        role_self = "[ATTACK]"
    elif viewer_id == game.defender_id:
        role_self = "[DEFEND]"
    else:
        role_self = "[WAIT]"
    draw.text((PADDING, hand_y - HAND_NUM_OFFSET - 40), f"Your hand: {role_self}",
              fill=COLOR_HINT, font=fn_label)

    for i, card in enumerate(hand):
        x      = PADDING + i * (CARD_W + 16)
        card_i = _load_card_img(card.filename())
        if card_i:
            img.paste(card_i, (x, hand_y), card_i)
        # Номер карты для ввода хода
        draw.text((x + CARD_W // 2, hand_y - HAND_NUM_OFFSET // 2), str(i + 1),
                  fill=COLOR_HINT, font=fn_num, anchor="mm")

    # Сохраняем
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return discord.File(buf, filename="durak.png")


# ==========================================================
# Вспомогательные функции
# ==========================================================

def deal_cards(game: DurakGame, count: int = 6):
    """Добирает карты до 6 в руке начиная с атакующего."""
    order = []
    active = game.active_players()
    if not active:
        return
    start = game.attacker_idx
    for i in range(len(game.players)):
        pid = game.players[(start + i) % len(game.players)]
        if pid in active:
            order.append(pid)

    for pid in order:
        while len(game.hands[pid]) < count and game.deck:
            game.hands[pid].append(game.deck.pop(0))


def check_win_condition(game: DurakGame) -> list[int]:
    """Возвращает список новых выбывших (без карт и колода пуста)."""
    new_losers = []
    if game.deck:
        return new_losers
    for pid in game.active_players():
        if len(game.hands[pid]) == 0:
            new_losers.append(pid)
    return new_losers


def end_turn(game: DurakGame, defender_took: bool):
    """
    Завершает ход:
    - defender_took=True  → защитник берёт карты со стола
    - defender_took=False → карты в отбой
    """
    if defender_took:
        for c in game.table_attack:
            game.hands[game.defender_id].append(c)
        for c in game.table_defend:
            if c:
                game.hands[game.defender_id].append(c)
    # Очищаем стол
    game.table_attack.clear()
    game.table_defend.clear()
    game.passed.clear()

    # Добираем карты
    deal_cards(game)

    # Проверяем выбывших
    new_out = check_win_condition(game)
    for pid in new_out:
        if pid not in game.losers:
            game.losers.append(pid)

    active = game.active_players()
    if len(active) <= 1:
        game.finished = True
        return

    # Следующий атакующий
    if defender_took:
        # Защитник пропускает ход
        next_att = game.next_player_idx(game.defender_idx)
    else:
        next_att = game.defender_idx

    # Убеждаемся что next_att — активный игрок
    while game.players[next_att] not in active:
        next_att = (next_att + 1) % len(game.players)

    game.attacker_idx = next_att
    game.defender_idx = game.next_player_idx(next_att)


def build_status_embed(game: DurakGame, title: str = None, description: str = None) -> discord.Embed:
    active  = game.active_players()
    attacker = game.attacker_id
    defender = game.defender_id
    mode_str = "Переводной" if game.mode == "transfer" else "Классический"

    embed = discord.Embed(
        title=title or f"🃏 Дурак ({mode_str})",
        color=0x2d6b44
    )

    players_info = []
    for pid in game.players:
        if pid in game.losers:
            role = "💀 Дурак"
        elif pid == attacker:
            role = "⚔️ Атакует"
        elif pid == defender:
            role = "🛡️ Защищается"
        else:
            role = "⏳ Ждёт"
        name  = "🤖 Бот" if game.is_bot(pid) else f"<@{pid}>"
        cards = len(game.hands.get(pid, []))
        players_info.append(f"{role} {name} — {cards} карт")

    embed.add_field(name="Игроки", value="\n".join(players_info), inline=False)
    embed.add_field(
        name="Стол",
        value=f"Карт в атаке: {len(game.table_attack)} | Козырь: {SUIT_SYM[game.trump]}",
        inline=False
    )
    embed.add_field(name="Колода", value=f"{len(game.deck)} карт", inline=True)

    if description:
        embed.add_field(name="", value=description, inline=False)

    hint = []
    if game.table_attack:
        hint.append("Чтобы отбить карту: напиши номер своей карты и номер атакующей — например `1 2`")
        if game.mode == "transfer":
            hint.append("Чтобы перевести: напиши номер карты и `п` — например `3 п`")
        hint.append("Чтобы взять карты: напиши `взять`")
    else:
        hint.append("Чтобы походить: напиши номер карты — например `3`")
        hint.append("Чтобы закончить атаку: напиши `стоп`")
    embed.set_footer(text=" | ".join(hint) + " | сдаюсь — выйти из игры")
    return embed


# ==========================================================
# ИИ бота
# ==========================================================

def bot_attack(game: DurakGame, bot_id: int) -> Optional[Card]:
    """Бот выбирает карту для атаки или подкидывания. Возвращает None если хочет завершить."""
    hand = game.hands[bot_id]
    if not hand:
        return None

    # Если стол пустой — ходим наименьшей некозырной картой
    if not game.table_attack:
        non_trump = [c for c in hand if c.suit != game.trump]
        pool      = non_trump if non_trump else hand
        return min(pool, key=lambda c: game.rank_values[c.rank])

    # Все карты отбиты — решаем подкидывать или нет
    all_def = all(
        (i < len(game.table_defend) and game.table_defend[i])
        for i in range(len(game.table_attack))
    )
    if all_def:
        # Подкидываем только если есть совпадающий ранг и не слишком много карт на столе
        if len(game.table_attack) >= 4:
            return None  # не подкидываем — завершаем
        ranks_on_table = {c.rank for c in game.table_attack} | {
            c.rank for c in game.table_defend if c}
        matching = [c for c in hand if c.rank in ranks_on_table and c.suit != game.trump]
        if matching:
            return min(matching, key=lambda c: game.rank_values[c.rank])
        return None  # нечего подкидывать — завершаем

    # Подкидываем карту того же ранга что уже есть на столе
    ranks_on_table = {c.rank for c in game.table_attack} | {
        c.rank for c in game.table_defend if c}
    matching = [c for c in hand if c.rank in ranks_on_table]
    if matching:
        return min(matching, key=lambda c: game.rank_values[c.rank])
    return None


def bot_defend(game: DurakGame, bot_id: int) -> Optional[tuple[int, int]]:
    """
    Бот пытается отбить первую неотбитую карту.
    Возвращает (индекс_своей_карты, индекс_атакующей) или None если берёт.
    """
    hand = game.hands[bot_id]
    for i, atk in enumerate(game.table_attack):
        if i < len(game.table_defend) and game.table_defend[i]:
            continue  # уже отбита
        # Ищем подходящую карту
        candidates = [
            (j, c) for j, c in enumerate(hand)
            if c.beats(atk, game.trump, game.rank_values)
        ]
        if not candidates:
            return None  # нечем бить — берём
        # Выбираем минимальную подходящую
        j, _ = min(candidates, key=lambda x: (
            x[1].suit != game.trump,  # сначала некозырные
            -game.rank_values[x[1].rank]
        ))
        return (j, i)
    return None


# ==========================================================
# Управление каналами
# ==========================================================

async def get_or_create_category(guild: discord.Guild) -> discord.CategoryChannel:
    for cat in guild.categories:
        if cat.name == CATEGORY_NAME:
            return cat
    return await guild.create_category(CATEGORY_NAME)


async def create_game_channel(
    guild:    discord.Guild,
    category: discord.CategoryChannel,
    creator:  discord.Member,
    players:  list[discord.Member],
) -> discord.TextChannel:
    name = f"🃏-дурак-{creator.display_name}".lower().replace(" ", "-")[:80]
    overwrites = {
        guild.default_role: discord.PermissionOverwrite(
            read_messages=False,
            send_messages=False,
        ),
        guild.me: discord.PermissionOverwrite(
            read_messages=True,
            send_messages=True,
            manage_messages=True,
            manage_channels=True,
        ),
    }
    for m in players:
        overwrites[m] = discord.PermissionOverwrite(
            read_messages=True,
            send_messages=True,
        )
    return await guild.create_text_channel(name, category=category, overwrites=overwrites)


async def cleanup_game(bot: commands.Bot, game: DurakGame):
    delete_saved_game(game.channel_id)
    if game.channel_id in active_games:
        del active_games[game.channel_id]

    channel = bot.get_channel(game.channel_id)
    if not channel:
        return
    category = channel.category
    try:
        await channel.delete(reason="Партия в дурака завершена")
    except Exception as e:
        log.error(f"[durak] Ошибка удаления канала: {e}")
        return

    if category and category.name == CATEGORY_NAME:
        await asyncio.sleep(1)
        try:
            fresh = bot.get_channel(category.id)
            if fresh and len(fresh.channels) == 0:
                await fresh.delete(reason="Все партии завершены")
        except Exception as e:
            log.error(f"[durak] Ошибка удаления категории: {e}")


# ==========================================================
# Отправка состояния каждому игроку
# ==========================================================

async def send_game_state(
    bot:         commands.Bot,
    game:        DurakGame,
    title:       str  = None,
    description: str  = None,
    channel:     discord.TextChannel = None,
):
    """Отправляет embed + индивидуальное PNG каждому живому игроку."""
    embed = build_status_embed(game, title=title, description=description)

    if channel is None:
        channel = bot.get_channel(game.channel_id)
    if channel is None:
        return

    for pid in game.active_players():
        if game.is_bot(pid):
            continue
        board_file = render_table(game, pid)
        try:
            await channel.send(
                content=f"<@{pid}>",
                embed=embed,
                file=board_file
            )
        except Exception as e:
            log.error(f"[durak] Ошибка отправки состояния игроку {pid}: {e}")


# ==========================================================
# Обработка хода бота
# ==========================================================

async def process_bot_turn(bot: commands.Bot, game: DurakGame, channel: discord.TextChannel):
    """Выполняет ход бота если сейчас его очередь."""
    await asyncio.sleep(1.5)

    bot_id = game.attacker_id if game.is_bot(game.attacker_id) else (
             game.defender_id if game.is_bot(game.defender_id) else None)

    if bot_id is None:
        return

    if game.is_bot(game.attacker_id):
        # Бот атакует
        card = bot_attack(game, game.attacker_id)
        if card and len(game.table_attack) < 6:
            idx = game.hands[game.attacker_id].index(card)
            game.hands[game.attacker_id].pop(idx)
            game.table_attack.append(card)
            game.table_defend.append(None)
            save_games(active_games)
            await send_game_state(bot, game, description=f"🤖 Бот атакует: **{card.display()}**",
                                  channel=channel)
            # После хода бота — ход защитника
            if game.is_bot(game.defender_id):
                await process_bot_turn(bot, game, channel)
        else:
            # Бот завершает атаку
            end_turn(game, defender_took=False)
            save_games(active_games)
            if game.finished:
                await finish_game(bot, game, channel)
                return
            await send_game_state(bot, game, description="🤖 Бот завершил атаку.", channel=channel)
            if game.is_bot(game.attacker_id):
                await process_bot_turn(bot, game, channel)

    elif game.is_bot(game.defender_id):
        # Бот защищается
        result = bot_defend(game, game.defender_id)
        if result is None:
            # Бот берёт
            end_turn(game, defender_took=True)
            save_games(active_games)
            if game.finished:
                await finish_game(bot, game, channel)
                return
            await send_game_state(bot, game, description="🤖 Бот взял карты.", channel=channel)
            if game.is_bot(game.attacker_id):
                await process_bot_turn(bot, game, channel)
        else:
            my_idx, atk_idx = result
            def_card = game.hands[game.defender_id].pop(my_idx)
            while len(game.table_defend) <= atk_idx:
                game.table_defend.append(None)
            game.table_defend[atk_idx] = def_card
            save_games(active_games)

            # Проверяем отбиты ли все карты
            all_defended = all(game.table_defend[i] for i in range(len(game.table_attack)))
            desc = f"🤖 Бот отбил: **{def_card.display()}**"
            if all_defended:
                desc += "\n🤖 Все карты отбиты. Атакующий может подкинуть или закончить."
            await send_game_state(bot, game, description=desc, channel=channel)


async def finish_game(bot: commands.Bot, game: DurakGame, channel: discord.TextChannel):
    """Завершает партию, записывает статистику, удаляет канал."""
    active = game.active_players()
    mode   = "bot" if game.bot_players else "pvp"

    if len(active) == 1:
        loser_id = active[0]
        game.losers.append(loser_id)
        winners = [p for p in game.players if p not in game.losers and not game.is_bot(p)]
        losers  = [p for p in game.players if p in game.losers and not game.is_bot(p)]

        for uid in winners:
            record_result(uid, mode, "wins")
        for uid in losers:
            record_result(uid, mode, "losses")

        loser_mention = "🤖 Бот" if game.is_bot(loser_id) else f"<@{loser_id}>"
        desc = f"🃏 **Дурак** — {loser_mention}!\n"
        if winners:
            desc += "🏆 Победители: " + " ".join(f"<@{w}>" for w in winners)
    else:
        desc = "🤝 Ничья — все вышли одновременно!"
        for uid in [p for p in game.players if not game.is_bot(p)]:
            record_result(uid, mode, "draws")

    embed = discord.Embed(title="🏁 Игра завершена!", description=desc, color=0x2d6b44)
    try:
        await channel.send(embed=embed)
    except Exception:
        pass

    await asyncio.sleep(5)
    await cleanup_game(bot, game)


# ==========================================================
# Cog
# ==========================================================

class Durak(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self):
        saved = load_saved_games()
        for chan_id_str, data in saved.items():
            try:
                deck  = [_card_from_dict(c) for c in data["deck"]]
                tc    = _card_from_dict(data["trump_card"]) if data.get("trump_card") else None
                hands = {int(k): [_card_from_dict(c) for c in v]
                         for k, v in data["hands"].items()}
                td    = [(_card_from_dict(c) if c else None)
                         for c in data["table_defend"]]
                game  = DurakGame(
                    deck         = deck,
                    trump        = data["trump"],
                    trump_card   = tc,
                    hands        = hands,
                    table_attack = [_card_from_dict(c) for c in data["table_attack"]],
                    table_defend = td,
                    players      = data["players"],
                    bot_players  = data.get("bot_players", []),
                    attacker_idx = data["attacker_idx"],
                    defender_idx = data["defender_idx"],
                    channel_id   = data["channel_id"],
                    guild_id     = data["guild_id"],
                    mode         = data.get("mode", "classic"),
                    deck_size    = data.get("deck_size", 36),
                    passed       = data.get("passed", []),
                    losers       = data.get("losers", []),
                    finished     = data.get("finished", False),
                )
                active_games[int(chan_id_str)] = game
                log.info(f"[durak] Восстановлена партия в канале {chan_id_str}")
            except Exception as e:
                log.error(f"[durak] Не удалось восстановить партию {chan_id_str}: {e}")

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

        uid    = message.author.id
        active = game.active_players()
        if uid not in active:
            try:
                await message.delete()
            except Exception:
                pass
            return

        text = message.content.strip().lower()

        # Сдаться
        if text == "сдаюсь":
            try:
                await message.delete()
            except Exception:
                pass
            game.losers.append(uid)
            active = game.active_players()
            if len(active) <= 1:
                game.finished = True
                await finish_game(self.bot, game, message.channel)
                return
            # Если сдался атакующий или защитник — переназначаем роли
            if uid == game.attacker_id or uid == game.defender_id:
                end_turn(game, defender_took=False)
            save_games(active_games)
            await send_game_state(
                self.bot, game,
                description=f"🏳️ <@{uid}> сдался и выбывает из игры.",
                channel=message.channel
            )
            if game.is_bot(game.attacker_id):
                await process_bot_turn(self.bot, game, message.channel)
            return

        # Защитник берёт карты
        if text == "взять" and uid == game.defender_id:
            try:
                await message.delete()
            except Exception:
                pass
            end_turn(game, defender_took=True)
            save_games(active_games)
            if game.finished:
                await finish_game(self.bot, game, message.channel)
                return
            await send_game_state(self.bot, game,
                                   description=f"<@{uid}> берёт карты.", channel=message.channel)
            if game.is_bot(game.attacker_id):
                await process_bot_turn(self.bot, game, message.channel)
            return

        # Атакующий завершает атаку
        if text == "стоп" and uid == game.attacker_id:
            all_def = all(
                (i < len(game.table_defend) and game.table_defend[i])
                for i in range(len(game.table_attack))
            )
            if game.table_attack and all_def:
                try:
                    await message.delete()
                except Exception:
                    pass
                end_turn(game, defender_took=False)
                save_games(active_games)
                if game.finished:
                    await finish_game(self.bot, game, message.channel)
                    return
                await send_game_state(self.bot, game,
                                       description=f"<@{uid}> завершает атаку.",
                                       channel=message.channel)
                if game.is_bot(game.attacker_id):
                    await process_bot_turn(self.bot, game, message.channel)
                return

        # Атака: одно число
        if uid == game.attacker_id and text.isdigit():
            idx = int(text) - 1
            hand = game.hands[uid]
            if idx < 0 or idx >= len(hand):
                await message.delete()
                await message.channel.send(
                    f"<@{uid}> Неверный номер карты.", delete_after=3)
                return

            card = hand[idx]
            # Проверяем: карта должна совпадать по рангу с картами на столе
            if game.table_attack:
                ranks = {c.rank for c in game.table_attack} | {
                    c.rank for c in game.table_defend if c}
                if card.rank not in ranks:
                    await message.delete()
                    await message.channel.send(
                        f"<@{uid}> Можно подкидывать только карты рангов: "
                        f"{', '.join(RANK_DISPLAY[r] for r in ranks)}", delete_after=5)
                    return

            if len(game.table_attack) >= 6:
                await message.delete()
                await message.channel.send(
                    f"<@{uid}> На столе максимум 6 карт.", delete_after=3)
                return

            try:
                await message.delete()
            except Exception:
                pass

            hand.pop(idx)
            game.table_attack.append(card)
            game.table_defend.append(None)
            save_games(active_games)
            await send_game_state(self.bot, game,
                                   description=f"<@{uid}> атакует: **{card.display()}**",
                                   channel=message.channel)
            if game.is_bot(game.defender_id):
                await process_bot_turn(self.bot, game, message.channel)
            return

        # Защита: "номер_своей номер_атакующей"
        if uid == game.defender_id:
            parts = text.split()

            # Переводной дурак: перевод "3 п"
            if game.mode == "transfer" and len(parts) == 2 and parts[1] == "п":
                if not parts[0].isdigit():
                    await message.delete()
                    return
                my_idx = int(parts[0]) - 1
                hand   = game.hands[uid]
                if my_idx < 0 or my_idx >= len(hand):
                    await message.delete()
                    return
                card = hand[my_idx]
                # Перевод возможен только если ранг совпадает
                if not game.table_attack or card.rank != game.table_attack[0].rank:
                    await message.delete()
                    await message.channel.send(
                        f"<@{uid}> Перевод возможен только картой того же ранга.",
                        delete_after=4)
                    return
                next_def = game.players[game.next_player_idx(game.defender_idx)]
                try:
                    await message.delete()
                except Exception:
                    pass
                hand.pop(my_idx)
                game.table_attack.append(card)
                game.table_defend.append(None)
                # Меняем защитника
                game.defender_idx = game.next_player_idx(game.defender_idx)
                save_games(active_games)
                await send_game_state(
                    self.bot, game,
                    description=f"<@{uid}> переводит: **{card.display()}** → <@{next_def}>",
                    channel=message.channel)
                if game.is_bot(game.defender_id):
                    await process_bot_turn(self.bot, game, message.channel)
                return

            # Обычная защита: "1 2"
            if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
                my_idx  = int(parts[0]) - 1
                atk_idx = int(parts[1]) - 1
                hand    = game.hands[uid]

                if my_idx < 0 or my_idx >= len(hand):
                    await message.delete()
                    await message.channel.send(
                        f"<@{uid}> Неверный номер карты.", delete_after=3)
                    return
                if atk_idx < 0 or atk_idx >= len(game.table_attack):
                    await message.delete()
                    await message.channel.send(
                        f"<@{uid}> Неверный номер атакующей карты.", delete_after=3)
                    return
                if atk_idx < len(game.table_defend) and game.table_defend[atk_idx]:
                    await message.delete()
                    await message.channel.send(
                        f"<@{uid}> Эта карта уже отбита.", delete_after=3)
                    return

                def_card = hand[my_idx]
                atk_card = game.table_attack[atk_idx]

                if not def_card.beats(atk_card, game.trump, game.rank_values):
                    await message.delete()
                    await message.channel.send(
                        f"<@{uid}> **{def_card.display()}** не бьёт **{atk_card.display()}**.",
                        delete_after=4)
                    return

                try:
                    await message.delete()
                except Exception:
                    pass

                hand.pop(my_idx)
                while len(game.table_defend) <= atk_idx:
                    game.table_defend.append(None)
                game.table_defend[atk_idx] = def_card
                save_games(active_games)

                all_def = all(
                    (i < len(game.table_defend) and game.table_defend[i])
                    for i in range(len(game.table_attack))
                )
                desc = f"<@{uid}> отбивает: **{def_card.display()}**"
                if all_def:
                    desc += "\n✅ Все карты отбиты. Атакующий может подкинуть (`номер`) или закончить (`стоп`)."
                await send_game_state(self.bot, game, description=desc, channel=message.channel)

                # Если атакующий — бот, даём ему решить подкидывать или нет
                if all_def and game.is_bot(game.attacker_id):
                    await process_bot_turn(self.bot, game, message.channel)
                return

        # Неизвестная команда — удаляем
        try:
            await message.delete()
        except Exception:
            pass

    # -------------------------------------------------------
    # /durak
    # -------------------------------------------------------

    @app_commands.command(name="durak", description="Карточная игра Дурак")
    @app_commands.describe(
        action="start / stats",
        mode="classic — классический, transfer — переводной",
        deck="36 или 52 карты",
        players="Упомяните игроков через пробел (без упоминаний — против бота)",
    )
    @app_commands.choices(
        action=[
            app_commands.Choice(name="start", value="start"),
            app_commands.Choice(name="stats", value="stats"),
        ],
        mode=[
            app_commands.Choice(name="Классический", value="classic"),
            app_commands.Choice(name="Переводной",   value="transfer"),
        ],
        deck=[
            app_commands.Choice(name="36 карт", value="36"),
            app_commands.Choice(name="52 карты", value="52"),
        ],
    )
    async def durak_cmd(
        self,
        interaction: discord.Interaction,
        action: str,
        mode:    str = "classic",
        deck:    str = "36",
        players: str = None,
    ):
        if action == "start":
            await self._start(interaction, mode, int(deck), players)
        elif action == "stats":
            await self._stats(interaction)

    # -------------------------------------------------------
    # Старт
    # -------------------------------------------------------

    async def _start(
        self,
        interaction: discord.Interaction,
        mode:        str,
        deck_size:   int,
        players_str: Optional[str],
    ):
        guild = interaction.guild
        user  = interaction.user

        # Проверяем нет ли уже активной игры у пользователя
        for g in active_games.values():
            if user.id in g.players and g.guild_id == guild.id:
                await interaction.response.send_message(
                    "❌ У тебя уже есть активная игра.", ephemeral=True)
                return

        await interaction.response.defer(ephemeral=True)

        # Парсим игроков
        human_members = [user]
        bot_players   = []
        vs_bot        = True

        if players_str:
            mentions = [m.strip() for m in players_str.split() if m.strip().startswith("<@")]
            for mention in mentions:
                uid = int(mention.strip("<@!>"))
                if uid == user.id:
                    continue
                member = guild.get_member(uid)
                if member and not member.bot:
                    human_members.append(member)
                    vs_bot = False

        if len(human_members) > 6:
            await interaction.followup.send("❌ Максимум 6 игроков.", ephemeral=True)
            return

        # Добавляем ботов если нужно (минимум 2 игрока)
        n_bots = max(0, 2 - len(human_members)) if vs_bot else 0
        for i in range(n_bots):
            bot_id = -(i + 1)  # отрицательные ID для ботов
            bot_players.append(bot_id)

        all_players = [m.id for m in human_members] + bot_players
        random.shuffle(all_players)

        # Создаём колоду
        deck = make_deck(deck_size)

        # Определяем козырь
        trump_card = deck[-1]
        trump      = trump_card.suit

        # Раздаём карты
        hands: dict[int, list[Card]] = {pid: [] for pid in all_players}
        for _ in range(6):
            for pid in all_players:
                if deck:
                    hands[pid].append(deck.pop(0))

        # Кладём козырную карту обратно в конец
        deck.append(trump_card)

        # Определяем первого атакующего — у кого наименьший козырь
        first_attacker = 0
        min_trump_val  = 999
        for i, pid in enumerate(all_players):
            for card in hands[pid]:
                if card.suit == trump:
                    val = RANK_VALUE_36[card.rank] if deck_size == 36 else RANK_VALUE_52[card.rank]
                    if val < min_trump_val:
                        min_trump_val  = val
                        first_attacker = i

        defender_idx = (first_attacker + 1) % len(all_players)

        # Создаём категорию и канал
        try:
            category = await get_or_create_category(guild)
            channel  = await create_game_channel(guild, category, user, human_members)
        except discord.Forbidden:
            await interaction.followup.send(
                "❌ Нет прав для создания каналов.", ephemeral=True)
            return

        game = DurakGame(
            deck         = deck,
            trump        = trump,
            trump_card   = trump_card,
            hands        = hands,
            table_attack = [],
            table_defend = [],
            players      = all_players,
            bot_players  = bot_players,
            attacker_idx = first_attacker,
            defender_idx = defender_idx,
            channel_id   = channel.id,
            guild_id     = guild.id,
            mode         = mode,
            deck_size    = deck_size,
            passed       = [],
            losers       = [],
        )
        active_games[channel.id] = game
        save_games(active_games)

        mode_str = "Переводной" if mode == "transfer" else "Классический"
        desc     = (
            f"Режим: **{mode_str}** | Колода: **{deck_size} карт** | "
            f"Козырь: **{SUIT_SYM[trump]}**\n"
            f"Атакует: <@{game.attacker_id}> | "
            f"Защищается: <@{game.defender_id}>"
        )
        await send_game_state(
            self.bot, game,
            title=f"🃏 Дурак — новая партия!",
            description=desc,
            channel=channel,
        )
        await interaction.followup.send(f"✅ Игра начата в {channel.mention}", ephemeral=True)

        # Если первым ходит бот
        if game.is_bot(game.attacker_id):
            await process_bot_turn(self.bot, game, channel)

    # -------------------------------------------------------
    # Статистика
    # -------------------------------------------------------

    async def _stats(self, interaction: discord.Interaction):
        stats = get_player_stats(interaction.user.id)
        b     = stats.get("bot", {"wins": 0, "losses": 0, "draws": 0})
        p     = stats.get("pvp", {"wins": 0, "losses": 0, "draws": 0})

        embed = discord.Embed(
            title=f"📊 Статистика {interaction.user.display_name}",
            color=0x2d6b44
        )
        embed.add_field(
            name="🤖 Игры против бота",
            value=(
                f"> Побед: **{b['wins']}**\n"
                f"> Поражений: **{b['losses']}**\n"
                f"> Ничья: **{b['draws']}**"
            ),
            inline=False
        )
        embed.add_field(
            name="⚔️ Игры против игроков",
            value=(
                f"> Побед: **{p['wins']}**\n"
                f"> Поражений: **{p['losses']}**\n"
                f"> Ничья: **{p['draws']}**"
            ),
            inline=False
        )
        embed.set_thumbnail(url=interaction.user.display_avatar.url)
        await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(Durak(bot))