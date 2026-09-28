import asyncio
import logging
import sqlite3
from datetime import datetime
from typing import Optional

from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove, FSInputFile
)
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder

# ==================== НАСТРОЙКИ ====================
# Токен берём из переменной окружения (безопаснее)
import os
TOKEN = os.getenv("BOT_TOKEN")
if not TOKEN:
    raise ValueError("BOT_TOKEN не установлен! Добавь переменную окружения BOT_TOKEN")

# ==================== ЛОГИРОВАНИЕ ====================
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ==================== БАЗА ДАННЫХ ====================
def init_db():
    conn = sqlite3.connect("drinkmatch.db")
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
    CREATE TABLE IF NOT EXISTS chat_sessions (
        user_id INTEGER PRIMARY KEY,
        partner_id INTEGER
    )
    """)

    conn.commit()
    conn.close()


def are_matched(user1: int, user2: int) -> bool:
    u1, u2 = sorted([user1, user2])
    conn = sqlite3.connect("drinkmatch.db")
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM matches WHERE user1 = ? AND user2 = ?", (u1, u2))
    row = cur.fetchone()
    conn.close()
    return row is not None


def set_chat_partner(user_id: int, partner_id: int):
    conn = sqlite3.connect("drinkmatch.db")
    cur = conn.cursor()
    cur.execute(
        "INSERT OR REPLACE INTO chat_sessions (user_id, partner_id) VALUES (?, ?)",
        (user_id, partner_id)
    )
    conn.commit()
    conn.close()


def get_chat_partner(user_id: int) -> Optional[int]:
    conn = sqlite3.connect("drinkmatch.db")
    cur = conn.cursor()
    cur.execute("SELECT partner_id FROM chat_sessions WHERE user_id = ?", (user_id,))
    row = cur.fetchone()
    conn.close()
    return row[0] if row else None


def clear_chat_partner(user_id: int):
    conn = sqlite3.connect("drinkmatch.db")
    cur = conn.cursor()
    cur.execute("DELETE FROM chat_sessions WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()


def get_user_matches(user_id: int) -> list:
    conn = sqlite3.connect("drinkmatch.db")
    conn.row_factory = sqlite3.Row
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
        other = get_user(other_id)
        if other:
            result.append(other)
    return result


def delete_user(user_id: int):
    conn = sqlite3.connect("drinkmatch.db")
    cur = conn.cursor()
    cur.execute("DELETE FROM users WHERE user_id = ?", (user_id,))
    cur.execute("DELETE FROM likes WHERE from_user = ? OR to_user = ?", (user_id, user_id))
    cur.execute("DELETE FROM matches WHERE user1 = ? OR user2 = ?", (user_id, user_id))
    cur.execute("DELETE FROM chat_sessions WHERE user_id = ? OR partner_id = ?", (user_id, user_id))
    conn.commit()
    conn.close()


def get_user(user_id: int) -> Optional[dict]:
    conn = sqlite3.connect("drinkmatch.db")
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else None

def save_user(data: dict):
    conn = sqlite3.connect("drinkmatch.db")
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

def add_like(from_user: int, to_user: int) -> bool:
    """Возвращает True если получился матч"""
    conn = sqlite3.connect("drinkmatch.db")
    cur = conn.cursor()
    
    # Добавляем лайк
    try:
        cur.execute(
            "INSERT OR IGNORE INTO likes (from_user, to_user, created_at) VALUES (?, ?, ?)",
            (from_user, to_user, datetime.now().isoformat())
        )
    except:
        pass

    # Проверяем взаимность
    cur.execute(
        "SELECT 1 FROM likes WHERE from_user = ? AND to_user = ?",
        (to_user, from_user)
    )
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

def get_candidates(user_id: int, limit: int = 20) -> list:
    me = get_user(user_id)
    if not me:
        return []

    conn = sqlite3.connect("drinkmatch.db")
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # Кого мы ищем
    looking = me["looking_for"]
    gender_filter = ""
    if looking == "парней":
        gender_filter = "AND gender = 'парень'"
    elif looking == "девушек":
        gender_filter = "AND gender = 'девушка'"

    # Кого ищет кандидат (должен искать наш пол)
    my_gender = me["gender"]
    looking_me = ""
    if my_gender == "парень":
        looking_me = "AND (looking_for = 'парней' OR looking_for = 'всех')"
    else:
        looking_me = "AND (looking_for = 'девушек' OR looking_for = 'всех')"

    # Уже лайкнутые / дизлайкнутые (простые дизлайки = просто не лайкаем)
    cur.execute("""
        SELECT * FROM users 
        WHERE user_id != ? 
          AND is_active = 1
          AND city = ?
          {gender_filter}
          {looking_me}
          AND user_id NOT IN (SELECT to_user FROM likes WHERE from_user = ?)
        ORDER BY RANDOM()
        LIMIT ?
    """.format(gender_filter=gender_filter, looking_me=looking_me),
    (user_id, me["city"], user_id, limit))

    rows = cur.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def calc_compatibility(me: dict, other: dict) -> int:
    """Простая оценка совместимости 0-100"""
    score = 40  # базовый

    # Алкоголь
    if me["alcohol"] == "Пью всё" or other["alcohol"] == "Пью всё":
        score += 20
    elif me["alcohol"] == other["alcohol"]:
        score += 25
    else:
        score += 5

    # Курение
    if me["smoking"] == other["smoking"]:
        score += 20
    elif "всё" in me["smoking"].lower() or "всё" in other["smoking"].lower():
        score += 15
    elif me["smoking"] == "Не курю" or other["smoking"] == "Не курю":
        score += 5
    else:
        score += 8

    # Интересы
    my_ints = set(i.strip().lower() for i in (me.get("interests") or "").split(",") if i.strip())
    other_ints = set(i.strip().lower() for i in (other.get("interests") or "").split(",") if i.strip())
    common = my_ints & other_ints
    score += min(len(common) * 8, 25)

    return min(score, 100)


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


class Search(StatesGroup):
    viewing = State()


class Chat(StatesGroup):
    talking = State()


# ==================== КЛАВИАТУРЫ ====================
def gender_kb():
    builder = ReplyKeyboardBuilder()
    builder.add(KeyboardButton(text="Парень"), KeyboardButton(text="Девушка"))
    builder.adjust(2)
    return builder.as_markup(resize_keyboard=True)

def looking_kb():
    builder = ReplyKeyboardBuilder()
    builder.add(KeyboardButton(text="Парней"), KeyboardButton(text="Девушек"), KeyboardButton(text="Всех"))
    builder.adjust(3)
    return builder.as_markup(resize_keyboard=True)

def alcohol_kb():
    builder = ReplyKeyboardBuilder()
    builder.add(
        KeyboardButton(text="Пиво"),
        KeyboardButton(text="Вино"),
        KeyboardButton(text="Крепкий"),
        KeyboardButton(text="Коктейли"),
        KeyboardButton(text="Пью всё")
    )
    builder.adjust(2)
    return builder.as_markup(resize_keyboard=True)

def smoking_kb():
    builder = ReplyKeyboardBuilder()
    builder.add(
        KeyboardButton(text="Сигареты"),
        KeyboardButton(text="Электронки"),
        KeyboardButton(text="Курю всё"),
        KeyboardButton(text="Не курю")
    )
    builder.adjust(2)
    return builder.as_markup(resize_keyboard=True)

def main_menu_kb():
    builder = ReplyKeyboardBuilder()
    builder.add(
        KeyboardButton(text="🔍 Искать"),
        KeyboardButton(text="👤 Мой профиль"),
        KeyboardButton(text="❤️ Мои матчи"),
        KeyboardButton(text="✏️ Редактировать"),
        KeyboardButton(text="🗑 Удалить анкету")
    )
    builder.adjust(2)
    return builder.as_markup(resize_keyboard=True)


def confirm_delete_kb():
    builder = InlineKeyboardBuilder()
    builder.add(
        InlineKeyboardButton(text="Да, удалить", callback_data="delete_yes"),
        InlineKeyboardButton(text="Отмена", callback_data="delete_no")
    )
    return builder.as_markup()


def chat_kb():
    builder = ReplyKeyboardBuilder()
    builder.add(KeyboardButton(text="🚪 Выйти из чата"))
    return builder.as_markup(resize_keyboard=True)


def open_chat_kb(target_id: int):
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="💬 Написать в боте", callback_data=f"chat_{target_id}"))
    return builder.as_markup()


def matches_kb(matches: list):
    builder = InlineKeyboardBuilder()
    for m in matches:
        name = m.get("full_name") or "Пользователь"
        builder.add(InlineKeyboardButton(
            text=f"💬 {name}, {m['age']}",
            callback_data=f"chat_{m['user_id']}"
        ))
    builder.adjust(1)
    return builder.as_markup()

def profile_actions_kb(target_id: int):
    builder = InlineKeyboardBuilder()
    builder.add(
        InlineKeyboardButton(text="❤️ Лайк", callback_data=f"like_{target_id}"),
        InlineKeyboardButton(text="👎 Дальше", callback_data=f"next_{target_id}")
    )
    return builder.as_markup()


# ==================== РОУТЕР ====================
router = Router()

@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    user = get_user(message.from_user.id)
    if user:
        await message.answer(
            f"С возвращением, {user['full_name'] or message.from_user.first_name}! 🍻\n\n"
            "Используй меню ниже:",
            reply_markup=main_menu_kb()
        )
        await state.clear()
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
    text = message.text
    if text.lower() not in allowed:
        await message.answer("Выбери из кнопок")
        return
    await state.update_data(alcohol=text)
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
        "Например: футбол, рок, настолки, путешествия, киберспорт",
        reply_markup=ReplyKeyboardRemove()
    )
    await state.set_state(Reg.interests)


@router.message(Reg.interests)
async def reg_interests(message: Message, state: FSMContext):
    interests = message.text.strip()
    await state.update_data(interests=interests)
    await message.answer("Напиши короткое описание о себе (2-4 предложения):")
    await state.set_state(Reg.bio)


@router.message(Reg.bio)
async def reg_bio(message: Message, state: FSMContext):
    bio = message.text.strip()
    if len(bio) < 10:
        await message.answer("Слишком коротко, напиши чуть подробнее")
        return
    await state.update_data(bio=bio)
    await message.answer("Теперь отправь своё фото (именно фото, не файл):")
    await state.set_state(Reg.photo)


@router.message(Reg.photo, F.photo)
async def reg_photo(message: Message, state: FSMContext):
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
    await message.answer("Пришли именно фотографию, пожалуйста.")


# ==================== ГЛАВНОЕ МЕНЮ ====================
@router.message(F.text == "🔍 Искать")
async def start_search(message: Message, state: FSMContext):
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
        await message.answer("Анкеты закончились. Попробуй позже или зайди в «Искать» снова.", reply_markup=main_menu_kb())
        await state.clear()
        return

    target_id = candidates[index]
    target = get_user(target_id)
    me = get_user(message.from_user.id)

    if not target:
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

    is_match = add_like(from_id, target_id)

    if is_match:
        target = get_user(target_id)
        me = get_user(from_id)
        tname = target["full_name"] if target else "пользователем"
        mname = me["full_name"] if me else "пользователем"

        await callback.message.answer(
            f"🎉 <b>У вас матч!</b>\n\n"
            f"Вы понравились друг другу с {tname}.\n"
            "Можете писать прямо здесь, в боте.",
            parse_mode="HTML",
            reply_markup=open_chat_kb(target_id)
        )

        try:
            await callback.bot.send_message(
                target_id,
                f"🎉 <b>У вас матч!</b>\n\n"
                f"Вы понравились друг другу с {mname}.\n"
                "Можете писать прямо здесь, в боте.",
                parse_mode="HTML",
                reply_markup=open_chat_kb(from_id)
            )
        except Exception:
            pass
    else:
        await callback.answer("Лайк отправлен ❤️")

    # Следующая анкета
    data = await state.get_data()
    await state.update_data(index=data.get("index", 0) + 1)
    await callback.message.delete()
    await show_next_profile(callback.message, state)


@router.callback_query(F.data.startswith("next_"))
async def process_next(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    data = await state.get_data()
    await state.update_data(index=data.get("index", 0) + 1)
    await callback.message.delete()
    await show_next_profile(callback.message, state)


@router.message(F.text == "👤 Мой профиль")
async def my_profile(message: Message):
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


@router.message(F.text == "❤️ Мои матчи")
async def my_matches(message: Message):
    matches = get_user_matches(message.from_user.id)
    if not matches:
        await message.answer("Пока нет матчей 😢\nИщи людей через кнопку «Искать»")
        return

    text = "<b>Твои матчи:</b>\nНажми на человека, чтобы написать ему в боте.\n"
    await message.answer(text, parse_mode="HTML", reply_markup=matches_kb(matches))


@router.callback_query(F.data.startswith("chat_"))
async def open_chat(callback: CallbackQuery, state: FSMContext):
    partner_id = int(callback.data.split("_")[1])
    my_id = callback.from_user.id

    if not are_matched(my_id, partner_id):
        await callback.answer("Чат доступен только после взаимного лайка", show_alert=True)
        return

    partner = get_user(partner_id)
    name = partner["full_name"] if partner else "пользователем"
    set_chat_partner(my_id, partner_id)
    await state.set_state(Chat.talking)
    await callback.message.answer(
        f"💬 Чат с {name} открыт.\n"
        "Пиши сюда — сообщения уйдут собеседнику через бота.\n"
        "Чтобы выйти, нажми «Выйти из чата».",
        reply_markup=chat_kb()
    )
    await callback.answer()


@router.message(Chat.talking, F.text == "🚪 Выйти из чата")
async def exit_chat(message: Message, state: FSMContext):
    clear_chat_partner(message.from_user.id)
    await state.clear()
    await message.answer("Чат закрыт. Ты снова в главном меню.", reply_markup=main_menu_kb())


@router.message(Chat.talking)
async def relay_chat(message: Message, state: FSMContext):
    my_id = message.from_user.id
    partner_id = get_chat_partner(my_id)

    if not partner_id or not are_matched(my_id, partner_id):
        clear_chat_partner(my_id)
        await state.clear()
        await message.answer("Чат недоступен. Вернулся в меню.", reply_markup=main_menu_kb())
        return

    me = get_user(my_id)
    name = me["full_name"] if me else "Собеседник"

    try:
        if message.text:
            await message.bot.send_message(
                partner_id,
                f"💬 <b>{name}:</b>\n{message.text}",
                parse_mode="HTML"
            )
        elif message.photo:
            await message.bot.send_photo(
                partner_id,
                photo=message.photo[-1].file_id,
                caption=f"💬 Фото от {name}"
            )
        else:
            await message.answer("Сейчас можно отправлять текст или фото.")
            return
        await message.answer("Отправлено ✅")
    except Exception:
        await message.answer("Не удалось доставить сообщение. Возможно, человек ещё не запускал бота.")


@router.message(F.text == "✏️ Редактировать")
async def edit_profile(message: Message, state: FSMContext):
    await message.answer(
        "Чтобы изменить анкету — просто пройди регистрацию заново.\n"
        "Напиши /start и создай новую анкету (старая перезапишется)."
    )


@router.message(F.text == "🗑 Удалить анкету")
async def ask_delete_profile(message: Message):
    user = get_user(message.from_user.id)
    if not user:
        await message.answer("Анкета уже не найдена.")
        return
    await message.answer(
        "Точно удалить анкету?\n"
        "Пропадут профиль, лайки и матчи. Это нельзя отменить.",
        reply_markup=confirm_delete_kb()
    )


@router.callback_query(F.data == "delete_yes")
async def confirm_delete_profile(callback: CallbackQuery, state: FSMContext):
    delete_user(callback.from_user.id)
    await state.clear()
    await callback.message.answer(
        "Анкета удалена.\n"
        "Если захочешь снова пользоваться ботом — напиши /start.",
        reply_markup=ReplyKeyboardRemove()
    )
    await callback.answer("Анкета удалена")


@router.callback_query(F.data == "delete_no")
async def cancel_delete_profile(callback: CallbackQuery):
    await callback.message.answer("Ок, анкета на месте.", reply_markup=main_menu_kb())
    await callback.answer("Отменено")


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
