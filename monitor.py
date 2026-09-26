import asyncio
import logging
from typing import Optional
from aiogram import Bot
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.enums import ParseMode

from config import CHECK_INTERVAL_MINUTES
from database import db
from scraper import scraper
from matcher import extract_name_components, match_summons_title

logger = logging.getLogger(__name__)

# Track the last check timestamp and status
LAST_CHECK_INFO = {
    "last_check_time": None,
    "last_found_count": 0,
    "status": "Ініціалізація..."
}

async def send_summons_alert(bot: Bot, user_id: int, person: dict, post: dict):
    """
    Sends a formatted alert to a user about a detected summons.
    """
    try:
        # Fetch detailed post data for direct document links and body snippet
        details = await scraper.get_post_details(post["url"])

        title = details.get("title") or post.get("title", "")
        date = details.get("date") or post.get("date", "Невідомо")
        doc_url = details.get("document_url")

        text = (
            f"🚨 <b>УВАГА! Опубліковано повістку про виклик</b>\n\n"
            f"👤 <b>Особа:</b> <code>{person['full_name']}</code>\n"
            f"📅 <b>Дата на сайті:</b> {date}\n\n"
            f"📄 <b>Заголовок:</b>\n{title}\n\n"
        )

        if details.get("case_number"):
            text += f"⚖️ <b>Номер провадження:</b> № {details['case_number']}\n\n"

        text += "ℹ️ <i>Джерело: Офіс Генерального прокурора України</i>"

        buttons = [
            [InlineKeyboardButton(text="🌐 Відкрити на сайті ОГП", url=post["url"])]
        ]
        if doc_url:
            buttons.append([InlineKeyboardButton(text="📥 Завантажити документ", url=doc_url)])

        keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)

        await bot.send_message(
            chat_id=user_id,
            text=text,
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard,
            disable_web_page_preview=False
        )

        # Mark as sent in DB
        await db.record_notification_sent(user_id, person["id"], post["url"])
        logger.info(f"Successfully alerted user {user_id} regarding summons for {person['full_name']}")

    except Exception as e:
        logger.error(f"Failed to send alert to user {user_id}: {e}")

async def check_summons_for_all(bot: Bot):
    """
    Single check cycle:
    1. Check latest posts feed.
    2. Check targeted searches for all tracked stems.
    """
    from datetime import datetime
    now_str = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
    LAST_CHECK_INFO["last_check_time"] = now_str
    LAST_CHECK_INFO["status"] = "Виконується сканування..."

    tracked_persons = await db.get_all_active_tracked_persons()
    if not tracked_persons:
        LAST_CHECK_INFO["status"] = "Очікування (список спостереження порожній)"
        return

    logger.info(f"Starting check cycle for {len(tracked_persons)} tracked person(s)...")
    found_in_this_cycle = 0

    # Cache parsed components for tracked persons
    parsed_persons = []
    for p in tracked_persons:
        comp = extract_name_components(p["full_name"])
        parsed_persons.append({
            "db_person": p,
            "components": comp
        })

    # Strategy A: Scan latest posts from page 1 & 2
    latest_posts = []
    for page in [1, 2]:
        page_posts = await scraper.get_latest_summons(page=page)
        latest_posts.extend(page_posts)
        if len(page_posts) < 5:
            break

    for post in latest_posts:
        await db.record_seen_post(post["url"], post["title"], post.get("date"))

        for item in parsed_persons:
            p = item["db_person"]
            matched, confidence, reason = match_summons_title(post["title"], item["components"])
            if matched and confidence >= 0.7:
                already_sent = await db.has_notification_been_sent(p["user_id"], p["id"], post["url"])
                if not already_sent:
                    found_in_this_cycle += 1
                    await send_summons_alert(bot, p["user_id"], p, post)

    # Strategy B: Targeted search by stem for all distinct stems
    stems_map = {}
    for item in parsed_persons:
        stem = item["components"].get("stem")
        if stem:
            stems_map.setdefault(stem, []).append(item)

    for stem, person_items in stems_map.items():
        try:
            search_results = await scraper.search_summons(stem, page=1)
            for post in search_results:
                await db.record_seen_post(post["url"], post["title"], post.get("date"))

                for item in person_items:
                    p = item["db_person"]
                    matched, confidence, reason = match_summons_title(post["title"], item["components"])
                    if matched and confidence >= 0.7:
                        already_sent = await db.has_notification_been_sent(p["user_id"], p["id"], post["url"])
                        if not already_sent:
                            found_in_this_cycle += 1
                            await send_summons_alert(bot, p["user_id"], p, post)

            # Small pause between distinct search requests to be polite to the server
            await asyncio.sleep(1.0)
        except Exception as e:
            logger.error(f"Error in targeted search for stem '{stem}': {e}")

    LAST_CHECK_INFO["last_found_count"] = found_in_this_cycle
    LAST_CHECK_INFO["status"] = f"Працює нормально (останній раз перевірено о {now_str})"
    logger.info(f"Check cycle finished. New alerts sent: {found_in_this_cycle}")

async def run_monitoring_worker(bot: Bot):
    """
    Background worker loop that runs indefinitely while the bot is active.
    """
    logger.info(f"Starting background monitoring worker (interval: {CHECK_INTERVAL_MINUTES} min)...")
    # Initial delay to let the bot initialize cleanly
    await asyncio.sleep(5)

    while True:
        try:
            await check_summons_for_all(bot)
        except Exception as e:
            logger.error(f"Unexpected error in monitoring cycle: {e}", exc_info=True)
            LAST_CHECK_INFO["status"] = f"Помилка в циклі: {str(e)[:50]}"

        # Sleep until the next interval
        await asyncio.sleep(CHECK_INTERVAL_MINUTES * 60)
