import logging
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardRemove
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.enums import ParseMode

from database import db
from matcher import extract_name_components, match_summons_title
from scraper import scraper
from handlers.common import get_main_keyboard

logger = logging.getLogger(__name__)
router = Router()

class AddPersonStates(StatesGroup):
    waiting_for_name = State()

@router.message(Command("add"))
@router.message(F.text == "➕ Додати особу")
async def handle_add_person_start(message: Message, state: FSMContext):
    # Check if name was provided in the command line (e.g. /add Шевченко Тарас)
    args = message.text.split(maxsplit=1)
    if len(args) > 1 and args[0] == "/add":
        await process_person_name(message, args[1].strip(), state)
        return

    await state.set_state(AddPersonStates.waiting_for_name)
    await message.answer(
        "📝 <b>Введіть ПІБ або прізвище особи для моніторингу:</b>\n\n"
        "<i>Приклади:</i>\n"
        "• <code>Гавриленко Володимир Анатолійович</code> (найточніший пошук)\n"
        "• <code>Подольська Д.М.</code> (пошук з ініціалами)\n"
        "• <code>Шевченко</code> (пошук за прізвищем)\n\n"
        "<i>Для скасування надішліть /cancel</i>",
        parse_mode=ParseMode.HTML,
        reply_markup=ReplyKeyboardRemove()
    )

@router.message(Command("cancel"))
@router.message(F.text == "❌ Скасувати")
async def handle_cancel(message: Message, state: FSMContext):
    current_state = await state.get_state()
    if current_state:
        await state.clear()
    await message.answer("Дію скасовано.", reply_markup=get_main_keyboard())

@router.message(AddPersonStates.waiting_for_name)
async def handle_add_person_name(message: Message, state: FSMContext):
    if not message.text:
        await message.answer("Будь ласка, надішліть текстове повідомлення з ім'ям.")
        return
    await process_person_name(message, message.text.strip(), state)

async def process_person_name(message: Message, raw_name: str, state: FSMContext):
    await state.clear()

    if len(raw_name) < 2:
        await message.answer(
            "⚠️ ПІБ занадто коротке. Спробуйте ще раз через команду <code>/add ПІБ</code>.",
            parse_mode=ParseMode.HTML,
            reply_markup=get_main_keyboard()
        )
        return

    # Parse and extract morphology
    comp = extract_name_components(raw_name)
    surname = comp["surname"]
    stem = comp["stem"]
    user_id = message.from_user.id

    if not surname:
        await message.answer(
            "⚠️ Не вдалося розпізнати прізвище. Введіть коректне ім'я.",
            reply_markup=get_main_keyboard()
        )
        return

    import html
    # Register in DB
    person_id = await db.add_tracked_person(
        user_id=user_id,
        full_name=comp["raw"],
        surname=surname,
        stem=stem
    )

    if not person_id:
        await message.answer(
            f"ℹ️ Особа <b>{html.escape(comp['raw'])}</b> вже є у вашому списку моніторингу!",
            parse_mode=ParseMode.HTML,
            reply_markup=get_main_keyboard()
        )
        return

    # Initial response
    status_msg = await message.answer(
        f"✅ <b>Особу успішно додано!</b>\n\n"
        f"👤 <b>ПІБ:</b> <code>{html.escape(comp['raw'])}</code>\n"
        f"🔍 <b>Пошукова основа:</b> <code>{html.escape(stem)}</code>\n\n"
        f"⏳ <i>Здійснюю початкову перевірку на сайті ОГП...</i>",
        parse_mode=ParseMode.HTML,
        reply_markup=get_main_keyboard()
    )

    # Perform immediate check
    try:
        search_results = await scraper.search_summons(stem, page=1)
        matches = []
        for post in search_results:
            is_match, conf, reason = match_summons_title(post["title"], comp)
            if is_match and conf >= 0.7:
                matches.append(post)

        if matches:
            response_text = (
                f"⚠️ <b>Увага! На сайті ОГП вже є публікації щодо цієї особи ({len(matches)}):</b>\n\n"
            )
            for m in matches[:5]:
                clean_t = html.escape(m['title'])
                response_text += f"📅 <i>{m['date']}</i>\n<a href='{m['url']}'>{clean_t}</a>\n\n"

            if len(matches) > 5:
                response_text += f"<i>...та ще {len(matches) - 5} публікацій.</i>\n\n"

            response_text += "Бот продовжуватиме цілодобовий моніторинг нових повісток."
            await message.answer(response_text, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
        else:
            await message.answer(
                "🟢 <b>Поточних повісток на сайті не виявлено.</b>\n"
                "Система відстежуватиме сайт цілодобово і надішле сповіщення, щойно з'явиться будь-яка повістка.",
                parse_mode=ParseMode.HTML
            )

    except Exception as e:
        logger.error(f"Error during initial check: {e}")
        await message.answer("⚠️ Не вдалося виконати початкову перевірку сайту, але моніторинг активний.")

@router.message(Command("list"))
@router.message(F.text == "📋 Мій список")
async def handle_list_persons(message: Message):
    user_id = message.from_user.id
    persons = await db.get_user_tracked_persons(user_id)

    if not persons:
        await message.answer(
            "📋 <b>Ваш список спостереження порожній.</b>\n\n"
            "Щоб додати особу для моніторингу, натисніть <b>«➕ Додати особу»</b> або надішліть:\n"
            "<code>/add Прізвище Ім'я По батькові</code>",
            parse_mode=ParseMode.HTML,
            reply_markup=get_main_keyboard()
        )
        return

    text = f"📋 <b>Ваш список спостереження ({len(persons)} ос.):</b>\n\n"
    keyboard_buttons = []

    for i, p in enumerate(persons, 1):
        text += f"{i}. 👤 <b>{p['full_name']}</b> (корінь: <code>{p['stem']}</code>)\n"
        keyboard_buttons.append([
            InlineKeyboardButton(text=f"🗑️ Видалити {p['full_name'][:20]}", callback_data=f"del_person:{p['id']}")
        ])

    text += "\n<i>Натисніть кнопку під повідомленням, щоб видалити особу з моніторингу.</i>"
    keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)

    await message.answer(text, parse_mode=ParseMode.HTML, reply_markup=keyboard)

@router.callback_query(F.data.startswith("del_person:"))
async def handle_delete_person(callback: CallbackQuery):
    person_id = int(callback.data.split(":")[1])
    user_id = callback.from_user.id

    success = await db.remove_tracked_person(user_id, person_id)
    if success:
        await callback.answer("Особу видалено з моніторингу ✅")
        # Refresh the list
        persons = await db.get_user_tracked_persons(user_id)
        if not persons:
            await callback.message.edit_text(
                "📋 <b>Ваш список спостереження тепер порожній.</b>\n\n"
                "Щоб додати нову особу, скористайтеся <b>«➕ Додати особу»</b>.",
                parse_mode=ParseMode.HTML
            )
        else:
            text = f"📋 <b>Ваш список спостереження ({len(persons)} ос.):</b>\n\n"
            keyboard_buttons = []
            for i, p in enumerate(persons, 1):
                text += f"{i}. 👤 <b>{p['full_name']}</b> (корінь: <code>{p['stem']}</code>)\n"
                keyboard_buttons.append([
                    InlineKeyboardButton(text=f"🗑️ Видалити {p['full_name'][:20]}", callback_data=f"del_person:{p['id']}")
                ])
            text += "\n<i>Натисніть кнопку під повідомленням, щоб видалити особу з моніторингу.</i>"
            await callback.message.edit_text(
                text,
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)
            )
    else:
        await callback.answer("Помилка видалення або особу вже видалено.", show_alert=True)
