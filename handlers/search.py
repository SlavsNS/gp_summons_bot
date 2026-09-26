import logging
from aiogram import Router, F
from aiogram.types import Message, ReplyKeyboardRemove, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.enums import ParseMode

from matcher import extract_name_components, match_summons_title
from scraper import scraper
from handlers.common import get_main_keyboard

logger = logging.getLogger(__name__)
router = Router()

class SearchStates(StatesGroup):
    waiting_for_query = State()

@router.message(Command("check"))
@router.message(F.text == "🔍 Швидка перевірка")
async def handle_search_start(message: Message, state: FSMContext):
    args = message.text.split(maxsplit=1)
    if len(args) > 1 and args[0] == "/check":
        await perform_quick_search(message, args[1].strip(), state)
        return

    await state.set_state(SearchStates.waiting_for_query)
    await message.answer(
        "🔍 <b>Швидка разова перевірка в базі ОГП:</b>\n\n"
        "Введіть ПІБ або прізвище для пошуку:\n"
        "<i>(наприклад: <code>Подольська</code> або <code>Гавриленко Володимир</code>)</i>\n\n"
        "<i>Для скасування надішліть /cancel</i>",
        parse_mode=ParseMode.HTML,
        reply_markup=ReplyKeyboardRemove()
    )

@router.message(SearchStates.waiting_for_query)
async def handle_search_query(message: Message, state: FSMContext):
    if not message.text:
        await message.answer("Будь ласка, надішліть текстове повідомлення з ім'ям.")
        return
    await perform_quick_search(message, message.text.strip(), state)

async def perform_quick_search(message: Message, raw_query: str, state: FSMContext):
    await state.clear()

    comp = extract_name_components(raw_query)
    stem = comp["stem"]
    surname = comp["surname"]

    if not stem:
        await message.answer(
            "⚠️ Введіть коректне ім'я для пошуку.",
            reply_markup=get_main_keyboard()
        )
        return

    status_msg = await message.answer(
        f"🔎 <i>Шукаю публікації на сайті ОГП за запитом:</i> <code>{comp['raw']}</code>...",
        parse_mode=ParseMode.HTML,
        reply_markup=get_main_keyboard()
    )

    try:
        results = await scraper.search_summons(stem, page=1)
        matched_posts = []
        for p in results:
            is_match, conf, reason = match_summons_title(p["title"], comp)
            if is_match and conf >= 0.7:
                matched_posts.append((p, conf, reason))

        if not matched_posts:
            # If no match with strict matcher, but search had raw results, check if raw results are relevant
            if results and not comp.get("first_name") and not comp.get("initials"):
                matched_posts = [(p, 0.7, "За збігом запиту") for p in results]

        if not matched_posts:
            text = (
                f"🟢 <b>Повісток не знайдено!</b>\n\n"
                f"За запитом <code>{comp['raw']}</code> (пошуковий корінь: <code>{stem}</code>) "
                f"на офіційному сайті Офісу Генерального прокурора публікацій не виявлено.\n\n"
                f"💡 <i>Ви можете поставити цю особу на постійний моніторинг за допомогою кнопки <b>«➕ Додати особу»</b>.</i>"
            )
            await status_msg.edit_text(text, parse_mode=ParseMode.HTML)
            return

        # Results found!
        import html
        text = (
            f"⚠️ <b>Знайдено публікації ({len(matched_posts)}):</b>\n"
            f"👤 Запит: <code>{html.escape(comp['raw'])}</code>\n\n"
        )

        buttons = []
        for i, (post, conf, reason) in enumerate(matched_posts[:5], 1):
            clean_title = html.escape(post['title'])
            text += f"<b>{i}. {clean_title}</b>\n"
            text += f"📅 Дата: {post['date']}\n"
            text += f"🔗 <a href='{post['url']}'>Переглянути публікацію</a>\n\n"
            if i <= 3:
                buttons.append([InlineKeyboardButton(text=f"🌐 Новина #{i}", url=post["url"])])

        if len(matched_posts) > 5:
            text += f"<i>...та ще {len(matched_posts) - 5} результатів у базі.</i>\n\n"

        text += "ℹ️ <i>Щоб отримувати автоматичні сповіщення при появі нових повісток, додайте особу через «➕ Додати особу».</i>"

        keyboard = InlineKeyboardMarkup(inline_keyboard=buttons) if buttons else None
        try:
            await status_msg.edit_text(text, parse_mode=ParseMode.HTML, disable_web_page_preview=True, reply_markup=keyboard)
        except Exception as edit_err:
            logger.error(f"Failed to edit status message: {edit_err}")
            await message.answer(text, parse_mode=ParseMode.HTML, disable_web_page_preview=True, reply_markup=keyboard)

    except Exception as e:
        logger.exception(f"Error during quick search: {e}")
        try:
            await status_msg.edit_text(f"❌ Сталася помилка під час звернення до сайту ОГП: {str(e)[:100]}")
        except Exception:
            await message.answer("❌ Сталася помилка під час звернення до сайту ОГП. Спробуйте пізніше.")

