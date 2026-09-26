from aiogram import Router, F
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton
from aiogram.filters import CommandStart, Command
from aiogram.enums import ParseMode

from database import db
from monitor import LAST_CHECK_INFO
from config import CHECK_INTERVAL_MINUTES

router = Router()

def get_main_keyboard() -> ReplyKeyboardMarkup:
    keyboard = [
        [
            KeyboardButton(text="➕ Додати особу"),
            KeyboardButton(text="📋 Мій список")
        ],
        [
            KeyboardButton(text="🔍 Швидка перевірка"),
            KeyboardButton(text="🚨 Розшук МВС")
        ],
        [
            KeyboardButton(text="📊 Статус"),
            KeyboardButton(text="ℹ️ Довідка")
        ]
    ]
    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)

@router.message(CommandStart())
async def handle_start(message: Message):
    user = message.from_user
    if user:
        await db.add_or_update_user(
            user_id=user.id,
            username=user.username,
            first_name=user.first_name
        )

    welcome_text = (
        f"👋 <b>Вітаю, {user.first_name if user else 'користувачу'}!</b>\n\n"
        f"Цей бот автоматично моніторить:\n"
        f"1. <b>Офіс Генерального прокурора України</b> (повістки про виклик, підозри, спеціальне досудове розслідування).\n"
        f"2. <b>Базу розшуку МВС України</b> (особи, які переховуються від органів влади).\n\n"
        f"📌 <b>Можливості:</b>\n"
        f"• <b>Цілодобовий моніторинг:</b> автоперевірка кожні {CHECK_INTERVAL_MINUTES} хв.\n"
        f"• <b>Розумний пошук повісток:</b> врахування українських відмінків прізвищ.\n"
        f"• <b>Розшук МВС:</b> миттєва перевірка за Прізвищем та Іменем з фото та статтею ККУ.\n"
        f"• <b>Прямі файли:</b> офіційні посилання та PDF-документи.\n\n"
        f"Оберіть дію в меню нижче 👇"
    )
    await message.answer(welcome_text, reply_markup=get_main_keyboard(), parse_mode=ParseMode.HTML)

@router.message(Command("help"))
@router.message(F.text == "ℹ️ Довідка")
async def handle_help(message: Message):
    help_text = (
        "📖 <b>Інструкція з використання бота:</b>\n\n"
        "1️⃣ <b>Додати особу на моніторинг:</b>\n"
        "Натисніть <b>«➕ Додати особу»</b> або надішліть команду:\n"
        "<code>/add Прізвище Ім'я По батькові</code>\n"
        "<i>(наприклад: <code>/add Шевченко Тарас Григорович</code>)</i>\n\n"
        "2️⃣ <b>Швидка перевірка повісток ОГП:</b>\n"
        "Натисніть <b>«🔍 Швидка перевірка»</b> або надішліть:\n"
        "<code>/check Прізвище</code>\n\n"
        "3️⃣ <b>Перевірка в базі розшуку МВС:</b>\n"
        "Натисніть <b>«🚨 Розшук МВС»</b> або надішліть:\n"
        "<code>/mvs Прізвище Ім'я</code>\n"
        "<i>Бот перевірить особу в реєстрі розшукуваних МВС і надішле фото та статтю ККУ.</i>\n\n"
        "4️⃣ <b>Переглянути відстежуваних осіб:</b>\n"
        "Натисніть <b>«📋 Мій список»</b> або надішліть <code>/list</code>.\n\n"
        "5️⃣ <b>Статус моніторингу:</b>\n"
        "Натисніть <b>«📊 Статус»</b> або надішліть <code>/status</code>."
    )
    await message.answer(help_text, parse_mode=ParseMode.HTML)

@router.message(Command("status"))
@router.message(F.text == "📊 Статус")
async def handle_status(message: Message):
    user_id = message.from_user.id
    user_persons = await db.get_user_tracked_persons(user_id)
    global_stats = await db.get_stats()

    last_time = LAST_CHECK_INFO.get("last_check_time") or "ще не виконувалась"
    sys_status = LAST_CHECK_INFO.get("status") or "Активний"

    status_text = (
        "📊 <b>Статус системи моніторингу:</b>\n\n"
        f"• <b>Стан:</b> 🟢 {sys_status}\n"
        f"• <b>Періодичність перевірки:</b> кожні {CHECK_INTERVAL_MINUTES} хв\n"
        f"• <b>Остання перевірка сайту:</b> {last_time}\n\n"
        f"👤 <b>Ваш профіль:</b>\n"
        f"• Особи на вашому моніторингу: <b>{len(user_persons)}</b>\n\n"
        f"🌐 <b>Загальна статистика:</b>\n"
        f"• Всього користувачів бота: {global_stats['active_users']}\n"
        f"• Всього осіб на моніторингу: {global_stats['tracked_persons']}\n"
        f"• Надіслано сповіщень: {global_stats['notifications_sent']}"
    )
    await message.answer(status_text, parse_mode=ParseMode.HTML)
