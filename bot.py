import asyncio
import logging
import sqlite3
import os
from datetime import datetime
from typing import Optional
from pathlib import Path

from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    Message, CallbackQuery, ReplyKeyboardRemove,
    KeyboardButton, InlineKeyboardButton
)
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder

# ==================== НАСТРОЙКИ ====================
TOKEN = os.getenv("BOT_TOKEN")
if not TOKEN:
    raise ValueError("BOT_TOKEN не установлен! Добавь переменную окружения BOT_TOKEN")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ==================== БАЗА ДАННЫХ ====================
def get_db_path():
    """Путь к базе. На Railway Volume монтируем в /data"""
    data_dir = Path("/data")
    if data_dir.exists() and data_dir.is_dir():
        data_dir.mkdir(parents=True, exist_ok=True)
        return str(data_dir / "drinkmatch.db")
    # Локально или если volume ещё не подключён
    Path("data").mkdir(exist_ok=True)
    return "data/drinkmatch.db"

def get_conn():
    conn = sqlite3.connect(get_db_path())
    conn.row_factory = sqlite3.Row
    return conn


# ==================== НОРМАЛИЗАЦИЯ ГОРОДОВ ====================
CITY_ALIASES = {
    # Казахстан
    "астана": "астана", "astana": "астана", "нур-султан": "астана", "nursultan": "астана",
    "алматы": "алматы", "almaty": "алматы", "алма-ата": "алматы",
    "шымкент": "шымкент", "shymkent": "шымкент", "чимкент": "шымкент",
    "караганда": "караганда", "karaganda": "караганда", "қарағанды": "караганда",
    "актобе": "актобе", "aktobe": "актобе",
    "тараз": "тараз", "taraz": "тараз",
    "павлодар": "павлодар", "pavlodar": "павлодар",
    "усть-каменогорск": "усть-каменогорск", "oskemen": "усть-каменогорск", "өскемен": "усть-каменогорск",
    "семей": "семей", "semey": "семей",
    "атырау": "атырау", "atyrau": "атырау",
    "костанай": "костанай", "kostanay": "костанай",
    "кызылорда": "кызылорда", "kyzylorda": "кызылорда",
    "уральск": "уральск", "oral": "уральск", "орал": "уральск",
    "петропавловск": "петропавловск", "petropavl": "петропавловск",
    # Россия
    "москва": "москва", "moscow": "москва", "мск": "москва",
    "санкт-петербург": "санкт-петербург", "питер": "санкт-петербург", "spb": "санкт-петербург",
    "спб": "санкт-петербург", "saint petersburg": "санкт-петербург", "st petersburg": "санкт-петербург",
    "новосибирск": "новосибирск", "novosibirsk": "новосибирск",
    "екатеринбург": "екатеринбург", "yekaterinburg": "екатеринбург", "екб": "екатеринбург",
    "казань": "казань", "kazan": "казань",
    "нижний новгород": "нижний новгород", "нновгород": "нижний новгород",
    "челябинск": "челябинск", "chelyabinsk": "челябинск",
    "самара": "самара", "samara": "самара",
    "омск": "омск", "omsk": "омск",
    "ростов-на-дону": "ростов-на-дону", "ростов": "ростов-на-дону",
    "уфа": "уфа", "ufa": "уфа",
    "красноярск": "красноярск", "krasnoyarsk": "красноярск",
    "воронеж": "воронеж", "voronezh": "воронеж",
    "пермь": "пермь", "perm": "пермь",
    "волгоград": "волгоград", "volgograd": "волгоград",
    "краснодар": "краснодар", "krasnodar": "краснодар",
    # Другие
    "минск": "минск", "minsk": "минск",
    "киев": "киев", "kyiv": "киев", "київ": "киев",
    "ташкент": "ташкент", "tashkent": "ташкент",
    "бишкек": "бишкек", "bishkek": "бишкек",
    "тбилиси": "тбилиси", "tbilisi": "тбилиси",
    "ереван": "ереван", "yerevan": "ереван",
    "баку": "баку", "baku": "баку",
}

def normalize_city(city: str) -> str:
    if not city:
        return ""
    c = city.strip().lower().replace("ё", "е")
    # убираем лишние пробелы и дефисы для поиска
    c_clean = " ".join(c.split())
    return CITY_ALIASES.get(c_clean, c_clean)


def count_users() -> int:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM users WHERE is_active = 1")
    n = cur.fetchone()[0]
    conn.close()
    return n


def init_db():
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        username TEXT,
        full_name TEXT,
        gender TEXT,
        age INTEGER,
        city TEXT,
        looking_for TEXT,
        alcohol TEXT,
        smoking TEXT,
        interests TEXT,
        bio TEXT,
        photo_id TEXT,
        height INTEGER,
        lat REAL,
        lon REAL,
        is_active INTEGER DEFAULT 1,
        created_at TEXT
    )
    """)
    # Мягкая миграция для старых баз
    for col, typ in [("lat", "REAL"), ("lon", "REAL"), ("height", "INTEGER")]:
        try:
            cur.execute(f"ALTER TABLE users ADD COLUMN {col} {typ}")
        except Exception:
            pass

    cur.execute("""
    CREATE TABLE IF NOT EXISTS likes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        from_user INTEGER,
        to_user INTEGER,
        created_at TEXT,
        UNIQUE(from_user, to_user)
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS matches (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user1 INTEGER,
        user2 INTEGER,
        created_at TEXT,
        UNIQUE(user1, user2)
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS blocks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        from_user INTEGER,
        to_user INTEGER,
        created_at TEXT,
        UNIQUE(from_user, to_user)
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        from_user INTEGER,
        to_user INTEGER,
        text TEXT,
        created_at TEXT,
        is_read INTEGER DEFAULT 0
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS chat_sessions (
        user_id INTEGER PRIMARY KEY,
        partner_id INTEGER
    )
    """)

    conn.commit()
    conn.close()


# ==================== ХЕЛПЕРЫ БД ====================
def get_user(user_id: int) -> Optional[dict]:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else None


def save_user(data: dict):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
    INSERT OR REPLACE INTO users 
    (user_id, username, full_name, gender, age, city, looking_for, alcohol, smoking, interests, bio, photo_id, height, lat, lon, is_active, created_at)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
    """, (
        data["user_id"], data.get("username"), data.get("full_name"),
        data["gender"], data["age"], data["city"], data["looking_for"],
        data["alcohol"], data["smoking"], data["interests"], data["bio"],
        data.get("photo_id"), data.get("height"), data.get("lat"), data.get("lon"),
        datetime.now().isoformat()
    ))
    conn.commit()
    conn.close()


def update_user_field(user_id: int, field: str, value):
    allowed = {"gender", "age", "city", "looking_for", "alcohol", "smoking", "interests", "bio", "photo_id", "username", "full_name", "lat", "lon", "height"}
    if field not in allowed:
        return
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(f"UPDATE users SET {field} = ? WHERE user_id = ?", (value, user_id))
    conn.commit()
    conn.close()


def delete_user(user_id: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM users WHERE user_id = ?", (user_id,))
    cur.execute("DELETE FROM likes WHERE from_user = ? OR to_user = ?", (user_id, user_id))
    cur.execute("DELETE FROM matches WHERE user1 = ? OR user2 = ?", (user_id, user_id))
    cur.execute("DELETE FROM blocks WHERE from_user = ? OR to_user = ?", (user_id, user_id))
    cur.execute("DELETE FROM messages WHERE from_user = ? OR to_user = ?", (user_id, user_id))
    cur.execute("DELETE FROM chat_sessions WHERE user_id = ? OR partner_id = ?", (user_id, user_id))
    conn.commit()
    conn.close()


def add_like(from_user: int, to_user: int) -> bool:
    """Возвращает True если получился матч"""
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute(
            "INSERT OR IGNORE INTO likes (from_user, to_user, created_at) VALUES (?, ?, ?)",
            (from_user, to_user, datetime.now().isoformat())
        )
    except:
        pass

    cur.execute("SELECT 1 FROM likes WHERE from_user = ? AND to_user = ?", (to_user, from_user))
    is_match = cur.fetchone() is not None

    if is_match:
        u1, u2 = sorted([from_user, to_user])
        cur.execute(
            "INSERT OR IGNORE INTO matches (user1, user2, created_at) VALUES (?, ?, ?)",
            (u1, u2, datetime.now().isoformat())
        )

    conn.commit()
    conn.close()
    return is_match


def are_matched(user1: int, user2: int) -> bool:
    u1, u2 = sorted([user1, user2])
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM matches WHERE user1 = ? AND user2 = ?", (u1, u2))
    row = cur.fetchone()
    conn.close()
    return row is not None


def is_blocked(from_user: int, to_user: int) -> bool:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM blocks WHERE from_user = ? AND to_user = ?", (from_user, to_user))
    row = cur.fetchone()
    conn.close()
    return row is not None


def add_block(from_user: int, to_user: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "INSERT OR IGNORE INTO blocks (from_user, to_user, created_at) VALUES (?, ?, ?)",
        (from_user, to_user, datetime.now().isoformat())
    )
    # Удаляем матч если был
    u1, u2 = sorted([from_user, to_user])
    cur.execute("DELETE FROM matches WHERE user1 = ? AND user2 = ?", (u1, u2))
    cur.execute("DELETE FROM chat_sessions WHERE (user_id = ? AND partner_id = ?) OR (user_id = ? AND partner_id = ?)",
                (from_user, to_user, to_user, from_user))
    conn.commit()
    conn.close()


def save_message(from_user: int, to_user: int, text: str):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO messages (from_user, to_user, text, created_at) VALUES (?, ?, ?, ?)",
        (from_user, to_user, text, datetime.now().isoformat())
    )
    conn.commit()
    conn.close()


def set_chat_partner(user_id: int, partner_id: Optional[int]):
    conn = get_conn()
    cur = conn.cursor()
    if partner_id is None:
        cur.execute("DELETE FROM chat_sessions WHERE user_id = ?", (user_id,))
    else:
        cur.execute(
            "INSERT OR REPLACE INTO chat_sessions (user_id, partner_id) VALUES (?, ?)",
            (user_id, partner_id)
        )
    conn.commit()
    conn.close()


def get_chat_partner(user_id: int) -> Optional[int]:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT partner_id FROM chat_sessions WHERE user_id = ?", (user_id,))
    row = cur.fetchone()
    conn.close()
    return row["partner_id"] if row else None


def get_candidates(user_id: int, limit: int = 30, relax_gender: bool = False, relax_city: bool = False) -> list:
    me = get_user(user_id)
    if not me:
        return []

    conn = get_conn()
    cur = conn.cursor()

    my_city = normalize_city(me.get("city") or "")
    looking = me.get("looking_for") or "всех"
    my_gender = me.get("gender") or ""

    # Фильтр по полу кандидата (кого я ищу)
    gender_filter = ""
    if not relax_gender:
        if looking == "парней":
            gender_filter = "AND gender = 'парень'"
        elif looking == "девушек":
            gender_filter = "AND gender = 'девушка'"

    # Фильтр: кандидат должен искать мой пол (или всех)
    looking_me = ""
    if not relax_gender:
        if my_gender == "парень":
            looking_me = "AND (looking_for = 'парней' OR looking_for = 'всех')"
        elif my_gender == "девушка":
            looking_me = "AND (looking_for = 'девушек' OR looking_for = 'всех')"

    # Город
    city_filter = ""
    params = [user_id]
    if not relax_city and my_city:
        city_filter = "AND city = ?"
        params.append(my_city)

    params.extend([user_id, user_id, user_id, limit])

    cur.execute(f"""
        SELECT * FROM users 
        WHERE user_id != ? 
          AND is_active = 1
          {city_filter}
          {gender_filter}
          {looking_me}
          AND user_id NOT IN (SELECT to_user FROM likes WHERE from_user = ?)
          AND user_id NOT IN (SELECT to_user FROM blocks WHERE from_user = ?)
          AND user_id NOT IN (SELECT from_user FROM blocks WHERE to_user = ?)
        ORDER BY RANDOM()
        LIMIT ?
    """, params)

    rows = cur.fetchall()
    conn.close()
    return [dict(r) for r in rows]



def calc_compatibility(me: dict, other: dict) -> int:
    """
    Считаем совместимость 0–100.
    Алкоголь, курение, общие интересы и разница в возрасте.
    """
    score = 0

    # --- Алкоголь (макс 30) ---
    a1 = (me.get("alcohol") or "").lower()
    a2 = (other.get("alcohol") or "").lower()
    if a1 == a2:
        score += 30          # полное совпадение
    elif "всё" in a1 or "всё" in a2:
        score += 22          # один из них пьёт всё
    else:
        score += 8           # разные предпочтения

    # --- Курение (макс 25) ---
    s1 = (me.get("smoking") or "").lower()
    s2 = (other.get("smoking") or "").lower()
    if s1 == s2:
        score += 25
    elif "всё" in s1 or "всё" in s2:
        score += 18
    elif "не курю" in s1 and "не курю" not in s2:
        score += 5           # один курит, другой нет — слабо
    elif "не курю" in s2 and "не курю" not in s1:
        score += 5
    else:
        score += 12

    # --- Интересы (макс 30) ---
    my_ints = set(i.strip().lower() for i in (me.get("interests") or "").split(",") if i.strip())
    other_ints = set(i.strip().lower() for i in (other.get("interests") or "").split(",") if i.strip())
    if my_ints and other_ints:
        common = my_ints & other_ints
        # Чем больше общих интересов — тем выше
        ratio = len(common) / max(len(my_ints | other_ints), 1)
        score += int(ratio * 30)
        # Бонус за каждый общий интерес
        score += min(len(common) * 4, 15)
    else:
        score += 5

    # --- Возраст (макс 15, штраф за большую разницу) ---
    try:
        age_diff = abs(int(me.get("age", 25)) - int(other.get("age", 25)))
        if age_diff <= 2:
            score += 15
        elif age_diff <= 5:
            score += 10
        elif age_diff <= 10:
            score += 5
        else:
            score += 0
    except Exception:
        score += 5

    return max(15, min(score, 98))  # не даём 0 и 100



def haversine_km(lat1, lon1, lat2, lon2) -> float:
    """Расстояние в км между двумя точками"""
    from math import radians, sin, cos, sqrt, atan2
    if None in (lat1, lon1, lat2, lon2):
        return None
    R = 6371.0
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat/2)**2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon/2)**2
    c = 2 * atan2(sqrt(a), sqrt(1-a))
    return round(R * c, 1)


def format_distance(me: dict, other: dict) -> str:
    dist = haversine_km(me.get("lat"), me.get("lon"), other.get("lat"), other.get("lon"))
    if dist is None:
        return ""
    if dist < 1:
        return " · рядом"
    return f" · ~{dist} км"


def get_matches_list(user_id: int) -> list:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT * FROM matches 
        WHERE user1 = ? OR user2 = ?
        ORDER BY created_at DESC
    """, (user_id, user_id))
    rows = cur.fetchall()
    conn.close()

    result = []
    for row in rows:
        other_id = row["user2"] if row["user1"] == user_id else row["user1"]
        if is_blocked(user_id, other_id) or is_blocked(other_id, user_id):
            continue
        other = get_user(other_id)
        if other:
            result.append(other)
    return result


# ==================== СОСТОЯНИЯ ====================
class Reg(StatesGroup):
    gender = State()
    age = State()
    height = State()
    city = State()
    location = State()
    looking_for = State()
    alcohol = State()
    smoking = State()
    interests = State()
    bio = State()
    photo = State()


class Edit(StatesGroup):
    choosing = State()
    gender = State()
    age = State()
    height = State()
    city = State()
    looking_for = State()
    alcohol = State()
    smoking = State()
    interests = State()
    bio = State()
    photo = State()
    location = State()


class Search(StatesGroup):
    viewing = State()


class Chat(StatesGroup):
    talking = State()


# ==================== КЛАВИАТУРЫ ====================
def gender_kb():
    b = ReplyKeyboardBuilder()
    b.add(KeyboardButton(text="Парень"), KeyboardButton(text="Девушка"))
    b.adjust(2)
    return b.as_markup(resize_keyboard=True)

def looking_kb():
    b = ReplyKeyboardBuilder()
    b.add(KeyboardButton(text="Парней"), KeyboardButton(text="Девушек"), KeyboardButton(text="Всех"))
    b.adjust(3)
    return b.as_markup(resize_keyboard=True)

def alcohol_kb():
    b = ReplyKeyboardBuilder()
    b.add(KeyboardButton(text="Пиво"), KeyboardButton(text="Вино"),
          KeyboardButton(text="Крепкий"), KeyboardButton(text="Коктейли"),
          KeyboardButton(text="Пью всё"))
    b.adjust(2)
    return b.as_markup(resize_keyboard=True)

def smoking_kb():
    b = ReplyKeyboardBuilder()
    b.add(KeyboardButton(text="Сигареты"), KeyboardButton(text="Электронки"),
          KeyboardButton(text="Курю всё"), KeyboardButton(text="Не курю"))
    b.adjust(2)
    return b.as_markup(resize_keyboard=True)

def main_menu_kb():
    b = ReplyKeyboardBuilder()
    b.add(KeyboardButton(text="🔍 Искать"),
          KeyboardButton(text="👤 Мой профиль"),
          KeyboardButton(text="❤️ Мои матчи"),
          KeyboardButton(text="✏️ Редактировать"),
          KeyboardButton(text="💬 Чаты"),
          KeyboardButton(text="🗑 Удалить анкету"))
    b.adjust(2)
    return b.as_markup(resize_keyboard=True)

def stats_text() -> str:
    total = count_users()
    return f"🟢 Бот онлайн\n👥 Зарегистрировано: <b>{total}</b>"

async def send_main_menu(message: Message, extra: str = ""):
    """Показать меню с актуальной статистикой"""
    text = stats_text()
    if extra:
        text = extra.strip() + "\n\n" + text
    await message.answer(text, reply_markup=main_menu_kb(), parse_mode="HTML")


def chat_kb():
    """Клавиатура когда пользователь в режиме переписки"""
    b = ReplyKeyboardBuilder()
    b.add(KeyboardButton(text="🚪 Выйти из чата"))
    b.add(KeyboardButton(text="🔍 Искать"),
          KeyboardButton(text="💬 Чаты"),
          KeyboardButton(text="❤️ Мои матчи"))
    b.adjust(1, 3)
    return b.as_markup(resize_keyboard=True)

def profile_actions_kb(target_id: int):
    b = InlineKeyboardBuilder()
    b.add(InlineKeyboardButton(text="➕ Плюсвайб", callback_data=f"like_{target_id}"),
          InlineKeyboardButton(text="💨 Пшнх", callback_data=f"next_{target_id}"))
    return b.as_markup()

def match_actions_kb(partner_id: int):
    b = InlineKeyboardBuilder()
    b.add(InlineKeyboardButton(text="💬 Написать в боте", callback_data=f"chat_{partner_id}"),
          InlineKeyboardButton(text="🚫 Заблокировать", callback_data=f"block_{partner_id}"))
    return b.as_markup()

def edit_menu_kb():
    b = InlineKeyboardBuilder()
    b.add(
        InlineKeyboardButton(text="Пол", callback_data="edit_gender"),
        InlineKeyboardButton(text="Возраст", callback_data="edit_age"),
        InlineKeyboardButton(text="Рост", callback_data="edit_height"),
        InlineKeyboardButton(text="Город", callback_data="edit_city"),
        InlineKeyboardButton(text="Кого ищу", callback_data="edit_looking"),
        InlineKeyboardButton(text="Алкоголь", callback_data="edit_alcohol"),
        InlineKeyboardButton(text="Курение", callback_data="edit_smoking"),
        InlineKeyboardButton(text="Интересы", callback_data="edit_interests"),
        InlineKeyboardButton(text="О себе", callback_data="edit_bio"),
        InlineKeyboardButton(text="Фото", callback_data="edit_photo"),
        InlineKeyboardButton(text="📍 Геолокация", callback_data="edit_location"),
        InlineKeyboardButton(text="« Назад", callback_data="edit_back"),
    )
    b.adjust(2)
    return b.as_markup()

def confirm_delete_kb():
    b = InlineKeyboardBuilder()
    b.add(InlineKeyboardButton(text="Да, удалить", callback_data="delete_yes"),
          InlineKeyboardButton(text="Нет", callback_data="delete_no"))
    return b.as_markup()


# ==================== РОУТЕР ====================
router = Router()


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    set_chat_partner(message.from_user.id, None)

    user = get_user(message.from_user.id)
    if user:
        # Обновляем username на всякий случай
        update_user_field(message.from_user.id, "username", message.from_user.username)
        update_user_field(message.from_user.id, "full_name", message.from_user.full_name)

        total = count_users()
        await message.answer(
            f"С возвращением, {user['full_name'] or message.from_user.first_name}! 🍻\n\n"
            f"🟢 Бот онлайн\n"
            f"👥 Зарегистрировано: <b>{total}</b>\n\n"
            "Используй меню ниже:",
            reply_markup=main_menu_kb(),
            parse_mode="HTML"
        )
    else:
        total = count_users()
        await message.answer(
            "Привет! Это <b>DrinkMatch</b> 🍻\n\n"
            f"🟢 Бот онлайн\n"
            f"👥 Уже зарегистрировано: <b>{total}</b>\n\n"
            "Бот для поиска людей, с кем можно выпить.\n"
            "Давай создадим твою анкету.\n\n"
            "Укажи свой пол:",
            reply_markup=gender_kb(),
            parse_mode="HTML"
        )
        await state.set_state(Reg.gender)


# ==================== РЕГИСТРАЦИЯ ====================
@router.message(Reg.gender)
async def reg_gender(message: Message, state: FSMContext):
    text = message.text.lower()
    if text not in ["парень", "девушка"]:
        await message.answer("Выбери кнопку: Парень или Девушка")
        return
    await state.update_data(gender=text)
    await message.answer("Сколько тебе лет? (напиши число)", reply_markup=ReplyKeyboardRemove())
    await state.set_state(Reg.age)


@router.message(Reg.age)
async def reg_age(message: Message, state: FSMContext):
    if not message.text.isdigit():
        await message.answer("Напиши возраст цифрой, например: 25")
        return
    age = int(message.text)
    if age < 18 or age > 80:
        await message.answer("Возраст должен быть от 18 до 80")
        return
    await state.update_data(age=age)
    await message.answer("Какой у тебя рост? (в см, например: 175)")
    await state.set_state(Reg.height)


@router.message(Reg.height)
async def reg_height(message: Message, state: FSMContext):
    if not message.text.isdigit():
        await message.answer("Напиши рост числом в см, например: 175")
        return
    height = int(message.text)
    if height < 140 or height > 230:
        await message.answer("Укажи реальный рост (от 140 до 230 см)")
        return
    await state.update_data(height=height)
    await message.answer("В каком городе ты находишься?")
    await state.set_state(Reg.city)


@router.message(Reg.city)
async def reg_city(message: Message, state: FSMContext):
    city = normalize_city(message.text.strip())
    await state.update_data(city=city)
    from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
    loc_kb = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📍 Отправить геолокацию", request_location=True)],
            [KeyboardButton(text="Пропустить")]
        ],
        resize_keyboard=True
    )
    await message.answer(
        "Отправь свою геолокацию — так другие будут видеть расстояние до тебя.\n"
        "Можно пропустить.",
        reply_markup=loc_kb
    )
    await state.set_state(Reg.location)


@router.message(Reg.location, F.location)
async def reg_location(message: Message, state: FSMContext):
    await state.update_data(lat=message.location.latitude, lon=message.location.longitude)
    await message.answer("Геолокация сохранена ✅", reply_markup=ReplyKeyboardRemove())
    await message.answer("Кого ты ищешь?", reply_markup=looking_kb())
    await state.set_state(Reg.looking_for)


@router.message(Reg.location)
async def reg_location_skip(message: Message, state: FSMContext):
    await state.update_data(lat=None, lon=None)
    await message.answer("Геолокацию можно добавить позже в настройках.", reply_markup=ReplyKeyboardRemove())
    await message.answer("Кого ты ищешь?", reply_markup=looking_kb())
    await state.set_state(Reg.looking_for)


@router.message(Reg.looking_for)
async def reg_looking(message: Message, state: FSMContext):
    text = message.text.lower()
    if text not in ["парней", "девушек", "всех"]:
        await message.answer("Выбери кнопку")
        return
    await state.update_data(looking_for=text)
    await message.answer("Что ты обычно пьёшь?", reply_markup=alcohol_kb())
    await state.set_state(Reg.alcohol)


@router.message(Reg.alcohol)
async def reg_alcohol(message: Message, state: FSMContext):
    allowed = ["пиво", "вино", "крепкий", "коктейли", "пью всё"]
    if message.text.lower() not in allowed:
        await message.answer("Выбери из кнопок")
        return
    await state.update_data(alcohol=message.text)
    await message.answer("Что насчёт курения?", reply_markup=smoking_kb())
    await state.set_state(Reg.smoking)


@router.message(Reg.smoking)
async def reg_smoking(message: Message, state: FSMContext):
    allowed = ["сигареты", "электронки", "курю всё", "не курю"]
    if message.text.lower() not in allowed:
        await message.answer("Выбери из кнопок")
        return
    await state.update_data(smoking=message.text)
    await message.answer(
        "Напиши свои интересы через запятую.\n"
        "Например: футбол, рок, настолки, путешествия",
        reply_markup=ReplyKeyboardRemove()
    )
    await state.set_state(Reg.interests)


@router.message(Reg.interests)
async def reg_interests(message: Message, state: FSMContext):
    await state.update_data(interests=message.text.strip())
    await message.answer("Напиши короткое описание о себе (2–4 предложения):")
    await state.set_state(Reg.bio)


@router.message(Reg.bio)
async def reg_bio(message: Message, state: FSMContext):
    bio = message.text.strip()
    if len(bio) < 10:
        await message.answer("Слишком коротко, напиши чуть подробнее")
        return
    await state.update_data(bio=bio)
    await message.answer(
        "Теперь отправь <b>фото с лицом</b>.\n\n"
        "Важно: фото должно быть чётким, лицо хорошо видно.\n"
        "Фото без лица, скрины, мемы и чужие фото — не принимаются.",
        parse_mode="HTML"
    )
    await state.set_state(Reg.photo)


@router.message(Reg.photo, F.photo)
async def reg_photo(message: Message, state: FSMContext):
    # Простая проверка: принимаем только фото.
    # Настоящая нейросетевая верификация лица требует платных API или тяжёлых библиотек.
    # Здесь мы требуем фото и предупреждаем пользователя.
    photo_id = message.photo[-1].file_id
    data = await state.get_data()

    user_data = {
        "user_id": message.from_user.id,
        "username": message.from_user.username,
        "full_name": message.from_user.full_name,
        "gender": data["gender"],
        "age": data["age"],
        "height": data.get("height"),
        "city": data["city"],
        "looking_for": data["looking_for"],
        "alcohol": data["alcohol"],
        "smoking": data["smoking"],
        "interests": data["interests"],
        "bio": data["bio"],
        "photo_id": photo_id,
        "lat": data.get("lat"),
        "lon": data.get("lon"),
    }
    save_user(user_data)

    total = count_users()
    await message.answer(
        "Анкета создана! 🎉\n\n"
        f"👥 Всего в боте: <b>{total}</b>\n"
        "Теперь ты можешь искать людей.",
        reply_markup=main_menu_kb(),
        parse_mode="HTML"
    )
    await state.clear()


@router.message(Reg.photo)
async def reg_photo_wrong(message: Message):
    await message.answer("Пришли именно фотографию (не файл и не видео). Фото должно быть с лицом.")


# ==================== ГЛАВНОЕ МЕНЮ ====================
@router.message(F.text == "🔍 Искать")
async def start_search(message: Message, state: FSMContext, relax_gender: bool = False, relax_city: bool = False, user_id: int = None):
    # user_id нужен когда вызываем из callback (там message.from_user — это бот)
    uid = user_id or message.from_user.id
    set_chat_partner(uid, None)
    await state.clear()

    user = get_user(uid)
    if not user:
        await message.answer("Сначала создай анкету через /start")
        return

    # Пробуем строгий поиск → потом расширяем
    candidates = get_candidates(uid, relax_gender=relax_gender, relax_city=relax_city)

    if not candidates and not relax_gender and not relax_city:
        # Никого в городе с нужным полом — предлагаем искать всех
        b = InlineKeyboardBuilder()
        b.add(InlineKeyboardButton(text="Искать всех в моём городе", callback_data="search_relax_gender"))
        b.add(InlineKeyboardButton(text="🌍 Другие города и страны", callback_data="search_relax_city"))
        b.adjust(1)
        await message.answer(
            "В твоём городе пока нет подходящих анкет по выбранному полу.\n\n"
            "Что сделать?",
            reply_markup=b.as_markup()
        )
        return

    if not candidates and relax_gender and not relax_city:
        b = InlineKeyboardBuilder()
        b.add(InlineKeyboardButton(text="🌍 Другие города и страны", callback_data="search_relax_city"))
        b.add(InlineKeyboardButton(text="Позже", callback_data="search_cancel"))
        b.adjust(1)
        await message.answer(
            "В твоём городе больше никого нет.\n"
            "Искать в других городах и странах?",
            reply_markup=b.as_markup()
        )
        return

    if not candidates:
        await message.answer(
            "Пока нет подходящих анкет.\n"
            "Попробуй позже или позови друзей 🍻",
            reply_markup=main_menu_kb()
        )
        return

    valid_ids = [c["user_id"] for c in candidates if get_user(c["user_id"])]
    if not valid_ids:
        await message.answer("Пока нет анкет. Попробуй позже.", reply_markup=main_menu_kb())
        return

    mode = []
    if relax_gender:
        mode.append("все полы")
    if relax_city:
        mode.append("другие города и страны")
    mode_text = f" ({', '.join(mode)})" if mode else ""

    await message.answer(f"Нашёл {len(valid_ids)} анкет{mode_text} 🔍")
    await state.set_state(Search.viewing)
    await state.update_data(candidates=valid_ids, index=0, relax_gender=relax_gender, relax_city=relax_city)
    await show_next_profile(message, state)



@router.callback_query(F.data == "search_relax_gender")
async def search_relax_gender(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    try:
        await callback.message.edit_text("Ищем всех в твоём городе...")
    except Exception:
        await callback.message.answer("Ищем всех в твоём городе...")
    await start_search(callback.message, state, relax_gender=True, relax_city=False, user_id=callback.from_user.id)


@router.callback_query(F.data == "search_relax_city")
async def search_relax_city(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    try:
        await callback.message.edit_text("Ищем в других городах и странах...")
    except Exception:
        await callback.message.answer("Ищем в других городах и странах...")
    await start_search(callback.message, state, relax_gender=True, relax_city=True, user_id=callback.from_user.id)


@router.callback_query(F.data == "search_cancel")
async def search_cancel(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await send_main_menu(callback.message, "Ок, заходи позже 🍻")
    await state.clear()


async def show_next_profile(message: Message, state: FSMContext):
    data = await state.get_data()
    candidates = data.get("candidates", [])
    index = data.get("index", 0)

    # Защита от зацикливания
    if index >= len(candidates):
        await message.answer(
            "Анкеты закончились.\nНажми «🔍 Искать», чтобы начать заново.",
            reply_markup=main_menu_kb()
        )
        await state.clear()
        return

    target_id = candidates[index]
    target = get_user(target_id)
    me = get_user(message.chat.id)  # в личке chat.id == user_id

    if not target or not me:
        # Пропускаем битую анкету и идём дальше
        await state.update_data(index=index + 1)
        await show_next_profile(message, state)
        return

    compat = calc_compatibility(me, target)
    dist_str = format_distance(me, target)

    height_str = f", {target['height']} см" if target.get("height") else ""
    text = (
        f"<b>{target['full_name'] or 'Пользователь'}</b>, {target['age']}{height_str}{dist_str}\n"
        f"📍 {target['city']}\n\n"
        f"🍺 {target['alcohol']}\n"
        f"🚬 {target['smoking']}\n\n"
        f"Интересы: {target['interests']}\n\n"
        f"{target['bio']}\n\n"
        f"Совместимость: <b>{compat}%</b>"
    )

    try:
        await message.answer_photo(
            photo=target["photo_id"],
            caption=text,
            parse_mode="HTML",
            reply_markup=profile_actions_kb(target_id)
        )
    except Exception:
        await message.answer(text, parse_mode="HTML", reply_markup=profile_actions_kb(target_id))


@router.callback_query(F.data.startswith("like_"))
async def process_like(callback: CallbackQuery, state: FSMContext):
    target_id = int(callback.data.split("_")[1])
    from_id = callback.from_user.id

    if is_blocked(from_id, target_id) or is_blocked(target_id, from_id):
        await callback.answer("Нельзя", show_alert=True)
        return

    is_match = add_like(from_id, target_id)

    if is_match:
        target = get_user(target_id)
        me = get_user(from_id)

        # Уведомление текущему
        uname = f"@{target['username']}" if target and target.get("username") else "без username"
        text = (
            f"🎉 <b>У вас матч!</b>\n\n"
            f"Вы понравились друг другу с <b>{target['full_name'] or 'пользователем'}</b>.\n"
            f"Telegram: {uname}\n\n"
            f"Можешь написать прямо здесь в боте или в личку Telegram."
        )
        await callback.message.answer(text, parse_mode="HTML", reply_markup=match_actions_kb(target_id))

        # Уведомление другому
        try:
            other_uname = f"@{me['username']}" if me and me.get("username") else "без username"
            other_text = (
                f"🎉 <b>У вас матч!</b>\n\n"
                f"Вы понравились друг другу с <b>{me['full_name'] or 'пользователем'}</b>.\n"
                f"Telegram: {other_uname}\n\n"
                f"Можешь написать прямо здесь в боте или в личку Telegram."
            )
            await callback.bot.send_message(target_id, other_text, parse_mode="HTML",
                                            reply_markup=match_actions_kb(from_id))
        except Exception:
            pass
    else:
        await callback.answer("Плюсвайб отправлен ➕")

    data = await state.get_data()
    await state.update_data(index=data.get("index", 0) + 1)
    try:
        await callback.message.delete()
    except:
        pass
    await show_next_profile(callback.message, state)


@router.callback_query(F.data.startswith("next_"))
async def process_next(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    data = await state.get_data()
    await state.update_data(index=data.get("index", 0) + 1)
    try:
        await callback.message.delete()
    except:
        pass
    await show_next_profile(callback.message, state)


# ==================== ПРОФИЛЬ ====================
@router.message(F.text == "👤 Мой профиль")
async def my_profile(message: Message, state: FSMContext):
    set_chat_partner(message.from_user.id, None)
    await state.clear()
    user = get_user(message.from_user.id)
    if not user:
        await message.answer("Анкета не найдена. Напиши /start")
        return

    height_str = f", {user['height']} см" if user.get("height") else ""
    text = (
        f"<b>Твой профиль</b>\n\n"
        f"{user['full_name']}, {user['age']}{height_str}\n"
        f"📍 {user['city']}\n"
        f"Ищет: {user['looking_for']}\n\n"
        f"🍺 {user['alcohol']}\n"
        f"🚬 {user['smoking']}\n\n"
        f"Интересы: {user['interests']}\n\n"
        f"{user['bio']}"
    )
    try:
        await message.answer_photo(photo=user["photo_id"], caption=text, parse_mode="HTML")
    except:
        await message.answer(text, parse_mode="HTML")


# ==================== МАТЧИ ====================
@router.message(F.text == "❤️ Мои матчи")
async def my_matches(message: Message, state: FSMContext):
    set_chat_partner(message.from_user.id, None)
    await state.clear()
    matches = get_matches_list(message.from_user.id)

    if not matches:
        await message.answer("Пока нет матчей 😢\nИщи людей через кнопку «Искать»")
        return

    await message.answer("<b>Твои матчи:</b>", parse_mode="HTML")
    for other in matches:
        uname = f"@{other['username']}" if other.get("username") else "без username"
        text = f"• <b>{other['full_name'] or 'Пользователь'}</b> ({other['age']}) — {uname}"
        await message.answer(text, parse_mode="HTML", reply_markup=match_actions_kb(other["user_id"]))


# ==================== РЕДАКТИРОВАНИЕ ПРОФИЛЯ ====================
@router.message(F.text == "✏️ Редактировать")
async def edit_start(message: Message, state: FSMContext):
    set_chat_partner(message.from_user.id, None)
    user = get_user(message.from_user.id)
    if not user:
        await message.answer("Сначала создай анкету через /start")
        return
    await message.answer("Что хочешь изменить?", reply_markup=edit_menu_kb())
    await state.set_state(Edit.choosing)


@router.callback_query(F.data == "edit_back")
async def edit_back(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await send_main_menu(callback.message)
    await callback.answer()


@router.callback_query(F.data.startswith("edit_"))
async def edit_choose(callback: CallbackQuery, state: FSMContext):
    action = callback.data.replace("edit_", "")
    await callback.answer()

    if action == "gender":
        await callback.message.answer("Выбери пол:", reply_markup=gender_kb())
        await state.set_state(Edit.gender)
    elif action == "age":
        await callback.message.answer("Напиши новый возраст:", reply_markup=ReplyKeyboardRemove())
        await state.set_state(Edit.age)
    elif action == "height":
        await callback.message.answer("Напиши новый рост в см (например 175):", reply_markup=ReplyKeyboardRemove())
        await state.set_state(Edit.height)
    elif action == "city":
        await callback.message.answer("Напиши новый город:", reply_markup=ReplyKeyboardRemove())
        await state.set_state(Edit.city)
    elif action == "looking":
        await callback.message.answer("Кого ищешь?", reply_markup=looking_kb())
        await state.set_state(Edit.looking_for)
    elif action == "alcohol":
        await callback.message.answer("Что пьёшь?", reply_markup=alcohol_kb())
        await state.set_state(Edit.alcohol)
    elif action == "smoking":
        await callback.message.answer("Курение:", reply_markup=smoking_kb())
        await state.set_state(Edit.smoking)
    elif action == "interests":
        await callback.message.answer("Новые интересы через запятую:", reply_markup=ReplyKeyboardRemove())
        await state.set_state(Edit.interests)
    elif action == "bio":
        await callback.message.answer("Новое описание о себе:", reply_markup=ReplyKeyboardRemove())
        await state.set_state(Edit.bio)
    elif action == "photo":
        await callback.message.answer(
            "Отправь новое <b>фото с лицом</b>:\n"
            "Лицо должно быть хорошо видно.",
            parse_mode="HTML",
            reply_markup=ReplyKeyboardRemove()
        )
        await state.set_state(Edit.photo)
    elif action == "location":
        from aiogram.types import KeyboardButton, ReplyKeyboardMarkup
        loc_kb = ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text="📍 Отправить геолокацию", request_location=True)],
                      [KeyboardButton(text="Пропустить")]],
            resize_keyboard=True
        )
        await callback.message.answer(
            "Отправь свою геолокацию, чтобы люди видели примерное расстояние до тебя.\n"
            "Можно пропустить.",
            reply_markup=loc_kb
        )
        await state.set_state(Edit.location)


@router.message(Edit.gender)
async def edit_gender(message: Message, state: FSMContext):
    text = message.text.lower()
    if text not in ["парень", "девушка"]:
        await message.answer("Выбери кнопку")
        return
    update_user_field(message.from_user.id, "gender", text)
    await message.answer("Пол обновлён ✅", reply_markup=main_menu_kb())
    await state.clear()


@router.message(Edit.age)
async def edit_age(message: Message, state: FSMContext):
    if not message.text.isdigit():
        await message.answer("Напиши число")
        return
    age = int(message.text)
    if age < 18 or age > 80:
        await message.answer("От 18 до 80")
        return
    update_user_field(message.from_user.id, "age", age)
    await message.answer("Возраст обновлён ✅", reply_markup=main_menu_kb())
    await state.clear()


@router.message(Edit.height)
async def edit_height(message: Message, state: FSMContext):
    if not message.text.isdigit():
        await message.answer("Напиши число в см")
        return
    height = int(message.text)
    if height < 140 or height > 230:
        await message.answer("От 140 до 230 см")
        return
    update_user_field(message.from_user.id, "height", height)
    await message.answer("Рост обновлён ✅", reply_markup=main_menu_kb())
    await state.clear()


@router.message(Edit.city)
async def edit_city(message: Message, state: FSMContext):
    city = normalize_city(message.text.strip())
    update_user_field(message.from_user.id, "city", city)
    await message.answer("Город обновлён ✅", reply_markup=main_menu_kb())
    await state.clear()


@router.message(Edit.looking_for)
async def edit_looking(message: Message, state: FSMContext):
    text = message.text.lower()
    if text not in ["парней", "девушек", "всех"]:
        await message.answer("Выбери кнопку")
        return
    update_user_field(message.from_user.id, "looking_for", text)
    await message.answer("Обновлено ✅", reply_markup=main_menu_kb())
    await state.clear()


@router.message(Edit.alcohol)
async def edit_alcohol(message: Message, state: FSMContext):
    allowed = ["пиво", "вино", "крепкий", "коктейли", "пью всё"]
    if message.text.lower() not in allowed:
        await message.answer("Выбери из кнопок")
        return
    update_user_field(message.from_user.id, "alcohol", message.text)
    await message.answer("Обновлено ✅", reply_markup=main_menu_kb())
    await state.clear()


@router.message(Edit.smoking)
async def edit_smoking(message: Message, state: FSMContext):
    allowed = ["сигареты", "электронки", "курю всё", "не курю"]
    if message.text.lower() not in allowed:
        await message.answer("Выбери из кнопок")
        return
    update_user_field(message.from_user.id, "smoking", message.text)
    await message.answer("Обновлено ✅", reply_markup=main_menu_kb())
    await state.clear()


@router.message(Edit.interests)
async def edit_interests(message: Message, state: FSMContext):
    update_user_field(message.from_user.id, "interests", message.text.strip())
    await message.answer("Интересы обновлены ✅", reply_markup=main_menu_kb())
    await state.clear()


@router.message(Edit.bio)
async def edit_bio(message: Message, state: FSMContext):
    if len(message.text.strip()) < 10:
        await message.answer("Слишком коротко")
        return
    update_user_field(message.from_user.id, "bio", message.text.strip())
    await message.answer("Описание обновлено ✅", reply_markup=main_menu_kb())
    await state.clear()


@router.message(Edit.photo, F.photo)
async def edit_photo(message: Message, state: FSMContext):
    photo_id = message.photo[-1].file_id
    update_user_field(message.from_user.id, "photo_id", photo_id)
    await message.answer("Фото обновлено ✅", reply_markup=main_menu_kb())
    await state.clear()


@router.message(Edit.photo)
async def edit_photo_wrong(message: Message):
    await message.answer("Пришли именно фото с лицом.")




@router.message(Edit.location, F.location)
async def edit_location(message: Message, state: FSMContext):
    lat = message.location.latitude
    lon = message.location.longitude
    update_user_field(message.from_user.id, "lat", lat)
    update_user_field(message.from_user.id, "lon", lon)
    await message.answer("Геолокация сохранена ✅\nТеперь в анкетах будет показываться расстояние.", reply_markup=main_menu_kb())
    await state.clear()


@router.message(Edit.location)
async def edit_location_skip(message: Message, state: FSMContext):
    if message.text and "пропустить" in message.text.lower():
        await message.answer("Геолокация не изменена.", reply_markup=main_menu_kb())
    else:
        await message.answer("Нажми кнопку «📍 Отправить геолокацию» или «Пропустить».")
        return
    await state.clear()


# ==================== ЧАТ ВНУТРИ БОТА ====================
@router.callback_query(F.data.startswith("chat_"))
async def start_chat(callback: CallbackQuery, state: FSMContext):
    partner_id = int(callback.data.split("_")[1])
    me_id = callback.from_user.id

    if not are_matched(me_id, partner_id):
        await callback.answer("Нет матча", show_alert=True)
        return
    if is_blocked(me_id, partner_id) or is_blocked(partner_id, me_id):
        await callback.answer("Пользователь заблокирован", show_alert=True)
        return

    partner = get_user(partner_id)
    set_chat_partner(me_id, partner_id)
    await state.set_state(Chat.talking)

    name = partner["full_name"] if partner else "пользователем"
    await callback.message.answer(
        f"Ты в чате с <b>{name}</b>.\n\n"
        f"Просто пиши сообщения — они будут приходить собеседнику.\n"
        f"Чтобы выйти — нажми «🚪 Выйти из чата».",
        parse_mode="HTML",
        reply_markup=chat_kb()
    )
    await callback.answer()


@router.message(Chat.talking)
async def process_chat_message(message: Message, state: FSMContext):
    # Сначала проверяем кнопки меню — они имеют приоритет и закрывают чат
    menu_buttons = {
        "🚪 Выйти из чата",
        "🔍 Искать",
        "💬 Чаты",
        "❤️ Мои матчи",
        "👤 Мой профиль",
        "✏️ Редактировать",
        "🗑 Удалить анкету",
    }
    if message.text in menu_buttons:
        set_chat_partner(message.from_user.id, None)
        await state.clear()
        if message.text == "🚪 Выйти из чата":
            await send_main_menu(message, "Ты вышел из чата. Можешь вернуться через «💬 Чаты».")
            return
        # Для остальных кнопок — просто выходим из состояния чата,
        # дальше сработают обычные обработчики этих кнопок
        # Но так как мы уже в этом хендлере, нужно вручную вызвать логику
        if message.text == "🔍 Искать":
            await start_search(message, state)
            return
        if message.text == "💬 Чаты":
            await show_chats(message, state)
            return
        if message.text == "❤️ Мои матчи":
            await my_matches(message, state)
            return
        if message.text == "👤 Мой профиль":
            await my_profile(message, state)
            return
        if message.text == "✏️ Редактировать":
            await edit_start(message, state)
            return
        if message.text == "🗑 Удалить анкету":
            await ask_delete(message)
            return
        await send_main_menu(message)
        return

    partner_id = get_chat_partner(message.from_user.id)
    if not partner_id:
        await state.clear()
        await message.answer("Чат закрыт.", reply_markup=main_menu_kb())
        return

    if is_blocked(message.from_user.id, partner_id) or is_blocked(partner_id, message.from_user.id):
        await message.answer("Переписка недоступна (блокировка).", reply_markup=main_menu_kb())
        set_chat_partner(message.from_user.id, None)
        await state.clear()
        return

    text = message.text or ""
    if not text:
        await message.answer("Пока можно отправлять только текст.")
        return

    save_message(message.from_user.id, partner_id, text)

    me = get_user(message.from_user.id)
    sender_name = me["full_name"] if me else "Кто-то"

    try:
        await message.bot.send_message(
            partner_id,
            f"💬 <b>Новое сообщение от {sender_name}:</b>\n\n{text}\n\n"
            f"<i>Чтобы ответить — нажми «Написать в боте» в матчах или открой чат.</i>",
            parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"Не удалось отправить сообщение: {e}")
        await message.answer("Не удалось доставить сообщение. Возможно, пользователь заблокировал бота.")
        return

    await message.answer("Сообщение отправлено ✅")


@router.message(F.text == "💬 Чаты")
async def show_chats(message: Message, state: FSMContext):
    set_chat_partner(message.from_user.id, None)
    await state.clear()
    matches = get_matches_list(message.from_user.id)
    if not matches:
        await message.answer("У тебя пока нет матчей для переписки.")
        return
    await message.answer("<b>Выбери, кому написать:</b>", parse_mode="HTML")
    for other in matches:
        await message.answer(
            f"{other['full_name'] or 'Пользователь'} ({other['age']})",
            reply_markup=match_actions_kb(other["user_id"])
        )


# ==================== БЛОКИРОВКА ====================
@router.callback_query(F.data.startswith("block_"))
async def process_block(callback: CallbackQuery, state: FSMContext):
    target_id = int(callback.data.split("_")[1])
    from_id = callback.from_user.id

    add_block(from_id, target_id)
    set_chat_partner(from_id, None)
    await state.clear()

    await callback.message.answer("Пользователь заблокирован. Он больше не будет появляться в поиске и не сможет писать тебе.")
    await callback.answer("Заблокирован")


# ==================== УДАЛЕНИЕ АНКЕТЫ ====================
@router.message(F.text == "🗑 Удалить анкету")
async def ask_delete(message: Message):
    await message.answer(
        "Точно удалить анкету?\nПропадут профиль, лайки, матчи и переписка.",
        reply_markup=confirm_delete_kb()
    )


@router.callback_query(F.data == "delete_yes")
async def confirm_delete(callback: CallbackQuery, state: FSMContext):
    delete_user(callback.from_user.id)
    set_chat_partner(callback.from_user.id, None)
    await state.clear()
    await callback.message.answer(
        "Анкета удалена.\nЧтобы начать заново — напиши /start",
        reply_markup=ReplyKeyboardRemove()
    )
    await callback.answer()


@router.callback_query(F.data == "delete_no")
async def cancel_delete(callback: CallbackQuery):
    await send_main_menu(callback.message, "Ок, анкета на месте.")
    await callback.answer()


# ==================== ЗАПУСК ====================
async def main():
    init_db()
    bot = Bot(token=TOKEN)
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)
    logger.info("Бот DrinkMatch запущен!")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
