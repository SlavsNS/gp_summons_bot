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
            KeyboardButton(text="📊 Статус")
        ],
        [
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
        f"Цей бот автоматично моніторить офіційний вебсайт <b>Офісу Генерального прокурора України</b> "
        f"на предмет публікації повісток про виклик, повідомлень про підозру та спеціального досудового розслідування.\n\n"
        f"📌 <b>Можливості:</b>\n"
        f"• <b>Цілодобовий моніторинг:</b> перевірка публікацій кожні {CHECK_INTERVAL_MINUTES} хв.\n"
        f"• <b>Розумний пошук:</b> врахування українських відмінків прізвищ (наприклад: <i>Шевченка / Шевченку / Шевченко</i>).\n"
        f"• <b>Миттєвий розшук:</b> разова швидка перевірка в архіві публікацій.\n"
        f"• <b>Прямі файли:</b> посилання на офіційний текст і PDF-документи повістки.\n\n"
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
        "<i>(наприклад: <code>/add Шевченко Тарас Григорович</code> або <code>/add Шевченко Т.Г.</code>)</i>\n\n"
        "2️⃣ <b>Переглянути відстежуваних осіб:</b>\n"
        "Натисніть <b>«📋 Мій список»</b> або надішліть <code>/list</code>. Ви зможете будь-коли видалити особу зі списку в один клік.\n\n"
        "3️⃣ <b>Швидка разова перевірка:</b>\n"
        "Натисніть <b>«🔍 Швидка перевірка»</b> або надішліть:\n"
        "<code>/check Прізвище</code>\n"
        "<i>Бот миттєво здійснить пошук на сайті ОГП і покаже знайдені результати.</i>\n\n"
        "4️⃣ <b>Статус моніторингу:</b>\n"
        "Натисніть <b>«📊 Статус»</b> або надішліть <code>/status</code>, щоб дізнатися час останньої перевірки."
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
