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
from mvs_client import mvs_client
from handlers.common import get_main_keyboard, get_cancel_keyboard

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
        "• <code>Дудник Микола Петрович</code> (найточніший пошук ОГП + МВС)\n"
        "• <code>Гавриленко Володимир</code>\n"
        "• <code>Шевченко</code>\n\n"
        "<i>Натисніть кнопку нижче або надішліть /cancel для повернення до меню.</i>",
        parse_mode=ParseMode.HTML,
        reply_markup=get_cancel_keyboard()
    )

@router.message(AddPersonStates.waiting_for_name)
async def handle_add_person_name(message: Message, state: FSMContext):
    if not message.text:
        await message.answer("Будь ласка, надішліть текстове повідомлення з ім'ям.")
        return
    if message.text in ["🔙 Головне меню", "❌ Скасувати", "🏠 Головне меню", "/cancel"]:
        await state.clear()
        await message.answer("Повертаємося до головного меню 👇", reply_markup=get_main_keyboard())
        return
    await process_person_name(message, message.text.strip(), state)

async def process_person_name(message: Message, raw_name: str, state: FSMContext):
    await state.clear()

    if len(raw_name) < 2:
        await message.answer(
            "⚠️ ПІБ занадто коротке. Спробуйте ще раз через кнопку <b>«➕ Додати особу»</b>.",
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

    # Initial confirmation message with explanation of BOTH registers
    await message.answer(
        f"✅ <b>Особу успішно додано до моніторингу!</b>\n\n"
        f"👤 <b>ПІБ:</b> <code>{html.escape(comp['raw'])}</code>\n"
        f"🔍 <b>Пошукова основа:</b> <code>{html.escape(stem)}</code>\n\n"
        f"🛡 <b>Встановлено подвійний моніторинг 24/7 (кожні 15 хв):</b>\n"
        f"1. 🏛 <b>Офіс Генпрокурора (ОГП):</b> повістки про виклик, підозри, спецрозслідування.\n"
        f"2. 🚨 <b>База розшуку МВС:</b> кримінальний розшук осіб, які переховуються від органів влади.\n\n"
        f"⏳ <i>Здійснюю первинну перевірку в обох реєстрах...</i>",
        parse_mode=ParseMode.HTML,
        reply_markup=get_main_keyboard()
    )

    # Perform immediate check on BOTH systems
    ogp_matches = []
    try:
        search_results = await scraper.search_summons(stem, page=1)
        for post in search_results:
            is_match, conf, reason = match_summons_title(post["title"], comp)
            if is_match and conf >= 0.7:
                ogp_matches.append(post)
    except Exception as e:
        logger.error(f"Error during OGP check: {e}")

    mvs_matches = []
    if comp.get("first_name"):
        try:
            mvs_matches = await mvs_client.search_wanted(
                last_name=surname,
                first_name=comp["first_name"],
                middle_name=comp.get("patronymic")
            )
            # Update DB with current wanted status so we don't alert unless status changes
            is_wanted_initial = 1 if len(mvs_matches) > 0 else 0
            await db.update_mvs_wanted_status(person_id, is_wanted_initial)
            if is_wanted_initial:
                mvs_key = f"mvs://wanted/{mvs_matches[0].get('last_name')}_{mvs_matches[0].get('first_name')}_{mvs_matches[0].get('birthday')}"
                await db.record_notification_sent(user_id, person_id, mvs_key)
        except Exception as mvs_e:
            logger.error(f"Error checking MVS on add: {mvs_e}")

    # Build comprehensive report
    report = (
        f"📊 <b>Звіт первинної перевірки:</b>\n"
        f"👤 <code>{html.escape(comp['raw'])}</code>\n\n"
    )

    # 1. OGP section
    if ogp_matches:
        report += f"🏛 <b>ОГП:</b> ⚠️ <b>Виявлено публікації ({len(ogp_matches)}):</b>\n"
        for m in ogp_matches[:3]:
            clean_t = html.escape(m['title'])
            report += f"• 📅 <i>{m['date']}</i> — <a href='{m['url']}'>{clean_t}</a>\n"
        if len(ogp_matches) > 3:
            report += f"<i>...та ще {len(ogp_matches) - 3} публікацій.</i>\n"
    else:
        report += "🏛 <b>ОГП:</b> 🟢 Поточних повісток не виявлено.\n"

    report += "\n"

    # 2. MVS section
    if mvs_matches:
        report += f"🚨 <b>МВС:</b> ⚠️ <b>УВАГА! Особу виявлено в базі розшуку ({len(mvs_matches)}):</b>\n"
        for item in mvs_matches[:2]:
            full_pib = f"{item.get('last_name', '')} {item.get('first_name', '')} {item.get('middle_name', '')}".strip()
            report += (
                f"• 👤 <b>{html.escape(full_pib)}</b> ({html.escape(item.get('birthday') or '')})\n"
                f"  ⚖️ Стаття ККУ: <code>{html.escape(item.get('accusatory_item') or 'Не вказано')}</code>\n"
                f"  🚔 Орган: {html.escape(item.get('authority') or 'Не вказано')}\n"
            )
        report += f"<i>(Детальніше з фото: надішліть команду <code>/mvs {html.escape(comp['raw'])}</code>)</i>\n"
    elif comp.get("first_name"):
        report += "🚨 <b>МВС:</b> 🟢 В офіційному розшуку не перебуває.\n"
    else:
        report += "🚨 <b>МВС:</b> ℹ️ Для перевірки в розшуку вкажіть також ім'я (наприклад, <code>/mvs {html.escape(surname)} Ім'я</code>).\n"

    report += (
        f"\n🔔 <b>Цілодобовий моніторинг активний.</b>\n"
        f"Щойно з'явиться повістка або оголошення в розшук — бот миттєво сповістить вас у цьому чаті!"
    )

    nav_keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📋 Мій список", callback_data="show_list"),
            InlineKeyboardButton(text="➕ Додати ще", callback_data="add_another")
        ],
        [
            InlineKeyboardButton(text="🏠 Головне меню", callback_data="go_main_menu")
        ]
    ])

    await message.answer(
        report,
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
        reply_markup=nav_keyboard
    )

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

@router.callback_query(F.data == "show_list")
async def handle_callback_show_list(callback: CallbackQuery):
    await callback.answer()
    await handle_list_persons(callback.message)

@router.callback_query(F.data == "add_another")
async def handle_callback_add_another(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.set_state(AddPersonStates.waiting_for_name)
    await callback.message.answer(
        "📝 <b>Введіть ПІБ або прізвище наступної особи для моніторингу:</b>\n\n"
        "<i>Приклади:</i>\n"
        "• <code>Шевченко Тарас Григорович</code>\n"
        "• <code>Ковальчук Петро</code>\n\n"
        "<i>Натисніть кнопку нижче або надішліть /cancel для скасування.</i>",
        parse_mode=ParseMode.HTML,
        reply_markup=get_cancel_keyboard()
    )

@router.callback_query(F.data == "go_main_menu")
async def handle_callback_main_menu(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.clear()
    await callback.message.answer(
        "Головне меню 👇",
        reply_markup=get_main_keyboard()
    )

@router.message(Command("check_all"))
@router.message(F.text == "⚡ Перевірити всіх зараз")
async def handle_check_all(message: Message):
    user_id = message.from_user.id
    persons = await db.get_user_tracked_persons(user_id)

    if not persons:
        await message.answer(
            "📋 <b>Ваш список спостереження порожній.</b>\n\n"
            "Щоб додати особу для моніторингу, натисніть <b>«➕ Додати особу»</b>.",
            parse_mode=ParseMode.HTML,
            reply_markup=get_main_keyboard()
        )
        return

    import html
    from datetime import datetime
    status_msg = await message.answer(
        f"⏳ <i>Здійснюю моментальну перевірку {len(persons)} осіб за базами ОГП та МВС...</i>",
        parse_mode=ParseMode.HTML,
        reply_markup=get_main_keyboard()
    )

    now_time = datetime.now().strftime("%H:%M:%S")
    results_text = (
        f"⚡ <b>МОМЕНТАЛЬНИЙ СТАТУС УСІХ ОСІБ ({len(persons)}):</b>\n"
        f"🕒 <i>Станом на {now_time}</i>\n\n"
    )

    for i, p in enumerate(persons, 1):
        full_name = p["full_name"]
        comp = extract_name_components(full_name)
        stem = comp["stem"]
        surname = comp["surname"]

        # 1. Check OGP
        ogp_status = "🟢 Повісток не виявлено"
        try:
            ogp_res = await scraper.search_summons(stem, page=1)
            matches = []
            for post in ogp_res:
                is_match, conf, _ = match_summons_title(post["title"], comp)
                if is_match and conf >= 0.7:
                    matches.append(post)
            if matches:
                latest_date = matches[0].get("date", "")
                ogp_status = f"⚠️ <b>Є повістка</b> (остання {latest_date})"
        except Exception:
            ogp_status = "⚠️ Помилка зв'язку"

        # 2. Check MVS
        mvs_status = "🟢 В розшуку відсутній"
        if comp.get("first_name"):
            try:
                mvs_res = await mvs_client.search_wanted(
                    last_name=surname,
                    first_name=comp["first_name"],
                    middle_name=comp.get("patronymic")
                )
                if mvs_res:
                    item = mvs_res[0]
                    art = item.get("accusatory_item") or "ст. не вказана"
                    mvs_status = f"🚨 <b>У РОЗШУКУ ({html.escape(art)})</b>"
            except Exception:
                mvs_status = "⚠️ Помилка зв'язку"
        else:
            mvs_status = "ℹ️ Потрібне ім'я"

        results_text += (
            f"<b>{i}. 👤 {html.escape(full_name)}</b>\n"
            f"   • 🏛 ОГП: {ogp_status}\n"
            f"   • 🚨 МВС: {mvs_status}\n\n"
        )
        await asyncio.sleep(0.3)

    results_text += "ℹ️ <i>Цілодобовий моніторинг продовжує відстежувати зміни кожні 15 хв.</i>"

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🔄 Оновити статус ще раз", callback_data="refresh_check_all"),
            InlineKeyboardButton(text="📋 Мій список", callback_data="show_list")
        ],
        [
            InlineKeyboardButton(text="🏠 Головне меню", callback_data="go_main_menu")
        ]
    ])

    try:
        await status_msg.edit_text(
            results_text,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
            reply_markup=keyboard
        )
    except Exception:
        await message.answer(
            results_text,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
            reply_markup=keyboard
        )

@router.callback_query(F.data == "refresh_check_all")
async def handle_callback_refresh_check_all(callback: CallbackQuery):
    await callback.answer("Оновлюю моментальний статус...")
    await handle_check_all(callback.message)
