import logging
import os
from urllib.parse import urlparse

from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
DB_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///bot.db")
SECRET_KEY = os.getenv("SECRET_KEY", "")

# Прокси для исходящих запросов к Telegram API и Codeforces API.
# CalDAV идёт через отдельную переменную CALDAV_PROXY_URL (см. ниже).
PROXY_URL = os.getenv("PROXY_URL", "").strip()
CALDAV_PROXY_URL = os.getenv("CALDAV_PROXY_URL", "").strip()

# Схемы, поддерживаемые сразу всеми сетевыми стеками проекта:
# aiohttp-socks (Telegram, Codeforces) — http/socks4/socks5,
# niquests (CalDAV) — те же плюс socks5h (DNS резолвится на стороне прокси).
_PROXY_ALLOWED_SCHEMES = ("http", "socks4", "socks5", "socks5h")
_PROXY_LOCAL_HOSTS = ("localhost", "127.0.0.1", "0.0.0.0", "::1")


def validate_proxy_url(raw: str, name: str) -> str:
    """Проверяет URL прокси. Пустая строка = прокси не задан (норма).

    Бросает ValueError с понятным сообщением — его показывает стартовая
    валидация в main.py, чтобы бот не запускался с невалидной конфигурацией.
    """
    if not raw:
        return ""
    parsed = urlparse(raw)
    scheme = parsed.scheme.lower()
    if scheme not in _PROXY_ALLOWED_SCHEMES:
        raise ValueError(
            f"{name}: неподдерживаемая схема прокси {scheme!r}. "
            f"Поддерживаются: http://, socks4://, socks5://, socks5h://"
        )
    if not parsed.hostname:
        raise ValueError(f"{name}: в URL прокси не указан хост")
    if parsed.port is None:
        raise ValueError(f"{name}: в URL прокси не указан порт")
    if parsed.hostname.lower() in _PROXY_LOCAL_HOSTS:
        logging.getLogger(__name__).warning(
            "%s: адрес прокси %s локальный. Внутри контейнера localhost — сам контейнер, "
            "прокси на хост-машине не будет доступен: укажите host.docker.internal "
            "(в docker-compose.yml нужное отображение уже настроено). "
            "Это безопасно, только если бот запущен на хосте без Docker.",
            name,
            parsed.hostname,
        )
    return raw


def normalize_proxy_url_for_aiohttp(raw: str) -> str:
    """aiohttp-socks (python-socks) не знает схему socks5h://.

    Заменяем на socks5:// — семантика сохраняется, т.к. коннектор всегда
    использует rdns=True (DNS резолвится на стороне прокси), как в socks5h.
    """
    if raw.startswith("socks5h://"):
        return "socks5://" + raw[len("socks5h://") :]
    return raw


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
