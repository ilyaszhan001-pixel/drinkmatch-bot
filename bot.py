import asyncio
import logging
import sqlite3
import os
from datetime import datetime
from typing import Optional

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
def get_conn():
    conn = sqlite3.connect("drinkmatch.db")
    conn.row_factory = sqlite3.Row
    return conn

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
        is_active INTEGER DEFAULT 1,
        created_at TEXT
    )
    """)

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
    (user_id, username, full_name, gender, age, city, looking_for, alcohol, smoking, interests, bio, photo_id, is_active, created_at)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
    """, (
        data["user_id"], data.get("username"), data.get("full_name"),
        data["gender"], data["age"], data["city"], data["looking_for"],
        data["alcohol"], data["smoking"], data["interests"], data["bio"],
        data.get("photo_id"), datetime.now().isoformat()
    ))
    conn.commit()
    conn.close()


def update_user_field(user_id: int, field: str, value):
    allowed = {"gender", "age", "city", "looking_for", "alcohol", "smoking", "interests", "bio", "photo_id", "username", "full_name"}
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


def get_candidates(user_id: int, limit: int = 30) -> list:
    me = get_user(user_id)
    if not me:
        return []

    conn = get_conn()
    cur = conn.cursor()

    looking = me["looking_for"]
    gender_filter = ""
    if looking == "парней":
        gender_filter = "AND gender = 'парень'"
    elif looking == "девушек":
        gender_filter = "AND gender = 'девушка'"

    my_gender = me["gender"]
    looking_me = ""
    if my_gender == "парень":
        looking_me = "AND (looking_for = 'парней' OR looking_for = 'всех')"
    else:
        looking_me = "AND (looking_for = 'девушек' OR looking_for = 'всех')"

    cur.execute(f"""
        SELECT * FROM users 
        WHERE user_id != ? 
          AND is_active = 1
          AND city = ?
          {gender_filter}
          {looking_me}
          AND user_id NOT IN (SELECT to_user FROM likes WHERE from_user = ?)
          AND user_id NOT IN (SELECT to_user FROM blocks WHERE from_user = ?)
          AND user_id NOT IN (SELECT from_user FROM blocks WHERE to_user = ?)
        ORDER BY RANDOM()
        LIMIT ?
    """, (user_id, me["city"], user_id, user_id, user_id, limit))

    rows = cur.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def calc_compatibility(me: dict, other: dict) -> int:
    score = 40
    if me["alcohol"] == "Пью всё" or other["alcohol"] == "Пью всё":
        score += 20
    elif me["alcohol"] == other["alcohol"]:
        score += 25
    else:
        score += 5

    if me["smoking"] == other["smoking"]:
        score += 20
    elif "всё" in me["smoking"].lower() or "всё" in other["smoking"].lower():
        score += 15
    elif me["smoking"] == "Не курю" or other["smoking"] == "Не курю":
        score += 5
    else:
        score += 8

    my_ints = set(i.strip().lower() for i in (me.get("interests") or "").split(",") if i.strip())
    other_ints = set(i.strip().lower() for i in (other.get("interests") or "").split(",") if i.strip())
    common = my_ints & other_ints
    score += min(len(common) * 8, 25)
    return min(score, 100)


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
    city = State()
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
    city = State()
    looking_for = State()
    alcohol = State()
    smoking = State()
    interests = State()
    bio = State()
    photo = State()


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
        InlineKeyboardButton(text="Город", callback_data="edit_city"),
        InlineKeyboardButton(text="Кого ищу", callback_data="edit_looking"),
        InlineKeyboardButton(text="Алкоголь", callback_data="edit_alcohol"),
        InlineKeyboardButton(text="Курение", callback_data="edit_smoking"),
        InlineKeyboardButton(text="Интересы", callback_data="edit_interests"),
        InlineKeyboardButton(text="О себе", callback_data="edit_bio"),
        InlineKeyboardButton(text="Фото", callback_data="edit_photo"),
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

        await message.answer(
            f"С возвращением, {user['full_name'] or message.from_user.first_name}! 🍻\n\n"
            "Используй меню ниже:",
            reply_markup=main_menu_kb()
        )
    else:
        await message.answer(
            "Привет! Это <b>DrinkMatch</b> 🍻\n\n"
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
    await message.answer("В каком городе ты находишься?")
    await state.set_state(Reg.city)


@router.message(Reg.city)
async def reg_city(message: Message, state: FSMContext):
    city = message.text.strip().title()
    await state.update_data(city=city)
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
        "city": data["city"],
        "looking_for": data["looking_for"],
        "alcohol": data["alcohol"],
        "smoking": data["smoking"],
        "interests": data["interests"],
        "bio": data["bio"],
        "photo_id": photo_id
    }
    save_user(user_data)

    await message.answer(
        "Анкета создана! 🎉\n\n"
        "Теперь ты можешь искать людей.",
        reply_markup=main_menu_kb()
    )
    await state.clear()


@router.message(Reg.photo)
async def reg_photo_wrong(message: Message):
    await message.answer("Пришли именно фотографию (не файл и не видео). Фото должно быть с лицом.")


# ==================== ГЛАВНОЕ МЕНЮ ====================
@router.message(F.text == "🔍 Искать")
async def start_search(message: Message, state: FSMContext):
    set_chat_partner(message.from_user.id, None)
    user = get_user(message.from_user.id)
    if not user:
        await message.answer("Сначала создай анкету через /start")
        return

    candidates = get_candidates(message.from_user.id)
    if not candidates:
        await message.answer("Пока нет подходящих анкет в твоём городе. Зайди позже 🍻")
        return

    await state.set_state(Search.viewing)
    await state.update_data(candidates=[c["user_id"] for c in candidates], index=0)
    await show_next_profile(message, state)


async def show_next_profile(message: Message, state: FSMContext):
    data = await state.get_data()
    candidates = data.get("candidates", [])
    index = data.get("index", 0)

    if index >= len(candidates):
        await message.answer("Анкеты закончились. Нажми «Искать» снова.", reply_markup=main_menu_kb())
        await state.clear()
        return

    target_id = candidates[index]
    target = get_user(target_id)
    me = get_user(message.chat.id)

    if not target or not me:
        await state.update_data(index=index + 1)
        await show_next_profile(message, state)
        return

    compat = calc_compatibility(me, target)

    text = (
        f"<b>{target['full_name'] or 'Пользователь'}</b>, {target['age']}\n"
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

    text = (
        f"<b>Твой профиль</b>\n\n"
        f"{user['full_name']}, {user['age']}\n"
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
    await callback.message.answer("Главное меню:", reply_markup=main_menu_kb())
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


@router.message(Edit.city)
async def edit_city(message: Message, state: FSMContext):
    update_user_field(message.from_user.id, "city", message.text.strip().title())
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
        f"Чтобы выйти из чата — нажми «🔍 Искать» или любую кнопку меню.",
        parse_mode="HTML",
        reply_markup=main_menu_kb()
    )
    await callback.answer()


@router.message(Chat.talking)
async def process_chat_message(message: Message, state: FSMContext):
    partner_id = get_chat_partner(message.from_user.id)
    if not partner_id:
        await state.clear()
        await message.answer("Чат закрыт.", reply_markup=main_menu_kb())
        return

    if is_blocked(message.from_user.id, partner_id) or is_blocked(partner_id, message.from_user.id):
        await message.answer("Переписка недоступна (блокировка).")
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

    # Отправляем сообщение собеседнику + уведомление
    try:
        await message.bot.send_message(
            partner_id,
            f"💬 <b>Новое сообщение от {sender_name}:</b>\n\n{text}\n\n"
            f"<i>Чтобы ответить — нажми «Написать в боте» в матчах или открой чат.</i>",
            parse_mode="HTML"
        )
        # Если собеседник тоже в чате с нами — можно было бы просто переслать, но уведомление всегда приходит.
    except Exception as e:
        logger.error(f"Не удалось отправить сообщение: {e}")
        await message.answer("Не удалось доставить сообщение. Возможно, пользователь заблокировал бота.")

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
    await callback.message.answer("Ок, анкета на месте.", reply_markup=main_menu_kb())
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
