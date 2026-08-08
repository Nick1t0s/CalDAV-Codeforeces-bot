import logging

import caldav
from caldav.lib.error import (
    AuthorizationError,
    ConsistencyError,
    NotFoundError,
)

from services.crypto import KeyChangedError, KEY_CHANGED_MSG, decrypt

logger = logging.getLogger(__name__)


class CalendarNotFoundError(Exception):
    pass


def _client(server_url: str, username: str, password: str, *, encrypted: bool = True) -> caldav.DAVClient:
    return caldav.DAVClient(
        url=server_url,
        username=username,
        password=decrypt(password) if encrypted else password,
        timeout=30,
        require_tls=False,
    )


def _target_calendar(principal: caldav.Principal) -> caldav.Calendar:
    calendars = principal.calendars()
    if not calendars:
        raise CalendarNotFoundError("На сервере нет календарей")
    return calendars[0]


def list_calendars(server_url: str, username: str, password: str) -> list[str]:
    client = _client(server_url, username, password, encrypted=False)
    return [cal.name or cal.id for cal in client.principal().calendars()]


def find_by_uid(server_url: str, username: str, password: str, uid: str) -> bool:
    client = _client(server_url, username, password)
    cal = _target_calendar(client.principal())
    try:
        cal.get_event_by_uid(uid)
        return True
    except ConsistencyError:
        return True
    except NotFoundError:
        return False


def add_event(
    server_url: str,
    username: str,
    password: str,
    *,
    uid: str,
    summary: str,
    start,
    end,
) -> None:
    client = _client(server_url, username, password)
    cal = _target_calendar(client.principal())
    cal.add_event(dtstart=start, dtend=end, uid=uid, summary=summary)


def friendly_error(exc: Exception) -> str:
    logger.warning("CalDAV error: %s", exc, exc_info=True)
    if isinstance(exc, KeyChangedError):
        return KEY_CHANGED_MSG
    if isinstance(exc, AuthorizationError):
        return "Неверные данные доступа"
    if isinstance(exc, CalendarNotFoundError):
        return str(exc)
    return "Сервер не отвечает или не поддерживает CalDAV"
