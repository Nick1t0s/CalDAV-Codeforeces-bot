import logging
import os

from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
DB_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///bot.db")
SECRET_KEY = os.getenv("SECRET_KEY", "")


def _env_int_list(name: str) -> set[int]:
    raw = os.getenv(name, "")
    if not raw:
        return set()
    result: set[int] = set()
    for part in raw.split(","):
        part = part.strip()
        try:
            result.add(int(part))
        except ValueError:
            logging.getLogger(__name__).warning("Invalid integer in %s: %r, skipped", name, part)
    return result


ADMIN_IDS = _env_int_list("ADMIN_IDS")


def is_admin(tg_id: int) -> bool:
    return tg_id in ADMIN_IDS


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
REMIND_INTERVAL_SECONDS = _env_int("REMIND_INTERVAL_SECONDS", 10)
YANDEX_CALDAV_URL = "https://caldav.yandex.ru"


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name, "").strip().lower()
    if not raw:
        return default
    return raw in ("1", "true", "yes", "on")


ALLOW_LOCAL_CALDAV = _env_bool("ALLOW_LOCAL_CALDAV", False)
