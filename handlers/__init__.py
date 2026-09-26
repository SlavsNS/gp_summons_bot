from aiogram import Router
from .common import router as common_router
from .watchlist import router as watchlist_router
from .search import router as search_router

main_router = Router()
main_router.include_router(common_router)
main_router.include_router(watchlist_router)
main_router.include_router(search_router)
