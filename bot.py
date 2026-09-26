import asyncio
import logging
import sys
import aiohttp
from aiohttp import web
from curl_cffi.requests import AsyncSession

from aiogram import Bot, Dispatcher

from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage



from config import BOT_TOKEN, LOG_LEVEL, CHECK_INTERVAL_MINUTES
from handlers import main_router
from monitor import run_monitoring_worker
from database import db
from scraper import scraper


# Configure logging
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("summons_bot")

async def start_health_server():
    """Runs a lightweight HTTP server on $PORT for Render health checks and diagnostics."""
    import os
    port = int(os.getenv("PORT", "10000"))
    app = web.Application()
    
    async def handle_ping(request):
        return web.Response(text="🟢 GP Summons Bot is alive and running!")

    async def handle_diag(request):
        q = request.query.get("q", "Гавриленк")
        diag_info = []
        try:
            latest = await scraper.get_latest_summons(page=1)
            diag_info.append(f"Latest items parsed: {len(latest)}")
            if latest:
                diag_info.append(f"First item: {latest[0]['date']} - {latest[0]['title']}")
            
            res = await scraper.search_summons(q, page=1)
            diag_info.append(f"\nSearch for '{q}': found {len(res)} items")
            for r in res[:3]:
                diag_info.append(f" - {r['date']}: {r['title']}")
                
            return web.Response(text="\n".join(diag_info))
        except Exception as e:
            return web.Response(text=f"Diagnostic error: {type(e).__name__}: {str(e)}", status=500)




        
    app.router.add_get("/", handle_ping)
    app.router.add_get("/health", handle_ping)
    app.router.add_get("/diag", handle_diag)
    
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logger.info(f"Health check & diag web server started on 0.0.0.0:{port}")


async def on_startup(bot: Bot):
    bot_info = await bot.get_me()
    logger.info("=" * 60)
    logger.info(f"Бот успішно запущений: @{bot_info.username} (ID: {bot_info.id})")
    logger.info(f"Інтервал моніторингу ОГП: {CHECK_INTERVAL_MINUTES} хв.")
    logger.info("=" * 60)

    # Start background monitoring worker task
    asyncio.create_task(run_monitoring_worker(bot))
    
    # Start web server for Render health checks
    asyncio.create_task(start_health_server())


async def main():
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN не вказано! Перевірте файл .env.")
        sys.exit(1)

    bot = Bot(
        token=BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )
    dp = Dispatcher(storage=MemoryStorage())

    # Include routers
    dp.include_router(main_router)

    # Startup callback
    dp.startup.register(on_startup)

    try:
        # Drop pending updates so bot doesn't reply to old messages
        await bot.delete_webhook(drop_pending_updates=True)
        logger.info("Початок отримання оновлень (polling)...")
        await dp.start_polling(bot)
    finally:
        await bot.session.close()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Бот зупинений.")
