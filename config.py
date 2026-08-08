import os

from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
DB_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///bot.db")
PARSE_INTERVAL_SECONDS = int(os.getenv("PARSE_INTERVAL_SECONDS", "600"))
REMIND_INTERVAL_SECONDS = int(os.getenv("REMIND_INTERVAL_SECONDS", "60"))
YANDEX_CALDAV_URL = "https://caldav.yandex.ru"
