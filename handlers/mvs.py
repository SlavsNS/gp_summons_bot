import html
import base64
import logging
from aiogram import Router, F
from aiogram.types import Message, ReplyKeyboardRemove, BufferedInputFile
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.enums import ParseMode

from mvs_client import mvs_client
from matcher import normalize_text
from handlers.common import get_main_keyboard

logger = logging.getLogger(__name__)
router = Router()

class MVSSearchStates(StatesGroup):
    waiting_for_name = State()

@router.message(Command("mvs"))
@router.message(F.text == "🚨 Розшук МВС")
async def handle_mvs_start(message: Message, state: FSMContext):
    args = message.text.split(maxsplit=1)
    if len(args) > 1 and args[0] == "/mvs":
        await perform_mvs_search(message, args[1].strip(), state)
        return

    await state.set_state(MVSSearchStates.waiting_for_name)
    await message.answer(
        "🚨 <b>Пошук у базі розшуку МВС України:</b>\n\n"
        "Введіть <b>Прізвище та Ім'я</b> особи (по батькові — за наявності):\n"
        "<i>Приклади:</i>\n"
        "• <code>Петренко Петро</code>\n"
        "• <code>Шевченко Тарас Григорович</code>\n\n"
        "<i>Діапазон дат народження перевіряється автоматично (1900–сьогодні).</i>\n\n"
        "<i>Для скасування надішліть /cancel</i>",
        parse_mode=ParseMode.HTML,
        reply_markup=ReplyKeyboardRemove()
    )

@router.message(MVSSearchStates.waiting_for_name)
async def handle_mvs_query(message: Message, state: FSMContext):
    if not message.text:
        await message.answer("Будь ласка, надішліть текстове повідомлення з ім'ям.")
        return
    await perform_mvs_search(message, message.text.strip(), state)

async def perform_mvs_search(message: Message, raw_query: str, state: FSMContext):
    clean = normalize_text(raw_query)
    parts = clean.split()

    if len(parts) < 2:
        await message.answer(
            "⚠️ <b>Для розшуку МВС необхідно вказати як мінімум Прізвище та Ім'я!</b>\n\n"
            "<i>Наприклад:</i> <code>Петренко Петро</code> або <code>Шевченко Тарас Григорович</code>\n\n"
            "Введіть ім'я ще раз або надішліть /cancel:",
            parse_mode=ParseMode.HTML
        )
        return

    await state.clear()

    last_name = parts[0]
    first_name = parts[1]
    middle_name = parts[2] if len(parts) > 2 else None

    query_str = f"{last_name} {first_name}" + (f" {middle_name}" if middle_name else "")
    status_msg = await message.answer(
        f"🔎 <i>Звертаюся до офіційного реєстру МВС України щодо:</i> <code>{html.escape(query_str)}</code>...",
        parse_mode=ParseMode.HTML,
        reply_markup=get_main_keyboard()
    )

    try:
        results = await mvs_client.search_wanted(
            last_name=last_name,
            first_name=first_name,
            middle_name=middle_name
        )

        if not results:
            text = (
                f"🟢 <b>Особу не знайдено в базі розшуку МВС!</b>\n\n"
                f"👤 Запит: <code>{html.escape(query_str)}</code>\n"
                f"📅 Діапазон дат: 1900 — {html.escape(mvs_client.headers.get('Referer', 'сьогодні')) and 'сьогодні'}\n\n"
                f"<i>Особа не перебуває у переліку осіб, які переховуються від органів влади.</i>"
            )
            await status_msg.edit_text(text, parse_mode=ParseMode.HTML)
            return

        # Found results
        # If 1-3 results, send detailed cards (with photo if available)
        try:
            await status_msg.delete()
        except Exception:
            pass

        for idx, item in enumerate(results[:3], 1):
            f_name = item.get("first_name", "")
            m_name = item.get("middle_name", "")
            l_name = item.get("last_name", "")
            full_pib = f"{l_name} {f_name} {m_name}".strip()

            caption = (
                f"🚨 <b>ОСОБА У РОЗШУКУ МВС (#{idx}/{len(results)})!</b>\n\n"
                f"👤 <b>ПІБ:</b> <b>{html.escape(full_pib)}</b>\n"
                f"📅 <b>Дата народження:</b> {html.escape(item.get('birthday') or 'Не вказано')}\n"
                f"⚖️ <b>Стаття ККУ:</b> <code>{html.escape(item.get('accusatory_item') or 'Не вказано')}</code>\n"
                f"🔒 <b>Запобіжний захід:</b> {html.escape(item.get('precaution') or 'Не вказано')}\n"
                f"🚔 <b>Орган розшуку:</b> {html.escape(item.get('authority') or 'Не вказано')}\n"
                f"📆 <b>Дата зникнення:</b> {html.escape(item.get('disappear_day') or 'Не вказано')}\n"
                f"📍 <b>Місце зникнення:</b> {html.escape(item.get('disappear_place') or 'Не вказано')}\n"
                f"🏷 <b>Категорія:</b> {html.escape(item.get('category') or 'Особа, що переховується')}\n"
            )
            if item.get("contacts"):
                caption += f"📞 <b>Контакти:</b> {html.escape(item['contacts'])}\n"

            photo_b64 = item.get("photo")
            if photo_b64:
                try:
                    photo_bytes = base64.b64decode(photo_b64)
                    photo_file = BufferedInputFile(photo_bytes, filename=f"mvs_{idx}.jpg")
                    await message.answer_photo(photo=photo_file, caption=caption, parse_mode=ParseMode.HTML)
                    continue
                except Exception as p_err:
                    logger.warning(f"Failed to send photo: {p_err}")

            await message.answer(caption, parse_mode=ParseMode.HTML)

        if len(results) > 3:
            await message.answer(
                f"ℹ️ <i>Також знайдено ще {len(results) - 3} осіб зі схожими даними. Для звуження пошуку вкажіть точне по батькові.</i>",
                parse_mode=ParseMode.HTML
            )

    except Exception as e:
        logger.exception(f"Error during MVS search: {e}")
        err_text = f"❌ Сталася помилка під час звернення до бази МВС: {html.escape(str(e)[:100])}"
        try:
            await status_msg.edit_text(err_text, parse_mode=ParseMode.HTML)
        except Exception:
            await message.answer(err_text, parse_mode=ParseMode.HTML)
