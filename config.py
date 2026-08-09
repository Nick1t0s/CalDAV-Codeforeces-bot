import logging
import os

from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
DB_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///bot.db")
SECRET_KEY = os.getenv("SECRET_KEY", "")


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name, "")
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        logging.getLogger(__name__).warning("Invalid integer env %s=%r, using default %s", name, raw, default)
        return default


PARSE_INTERVAL_SECONDS = _env_int("PARSE_INTERVAL_SECONDS", 600)
REMIND_INTERVAL_SECONDS = _env_int("REMIND_INTERVAL_SECONDS", 60)
YANDEX_CALDAV_URL = "https://caldav.yandex.ru"
