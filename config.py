import os
from pathlib import Path
from dotenv import load_dotenv

# Base directory of the project
BASE_DIR = Path(__file__).resolve().parent

# Load .env file
load_dotenv(BASE_DIR / ".env")

# Telegram Bot configuration
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
if not BOT_TOKEN:
    raise ValueError("Помилка: BOT_TOKEN не знайдено у файлі .env! Будь ласка, вкажіть дійсний токен Telegram бота.")

# Scraper & monitoring configuration
CHECK_INTERVAL_MINUTES = int(os.getenv("CHECK_INTERVAL_MINUTES", "15"))

# Database path
DB_PATH = BASE_DIR / os.getenv("DB_PATH", "data/summons_bot.db")
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

# Site constants
GP_BASE_URL = "https://gp.gov.ua"
SUMMONS_CATEGORY_PATH = "/ua/categories/povistki-pro-viklik-ta-vidomosti-pro-zdijsnennya-specialnogo-dosudovogo-rozsliduvannya"
SUMMONS_FULL_URL = f"{GP_BASE_URL}{SUMMONS_CATEGORY_PATH}"


# Logging level
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
