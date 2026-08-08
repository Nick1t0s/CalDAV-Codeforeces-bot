import caldav
from caldav.lib.error import (
    AuthorizationError,
    ConsistencyError,
    DAVError,
    NotFoundError,
)


class CalendarNotFoundError(Exception):
    pass


def _client(server_url: str, username: str, password: str) -> caldav.DAVClient:
    return caldav.DAVClient(
        url=server_url,
        username=username,
        password=password,
        timeout=30,
        require_tls=False,
    )


def list_calendars(server_url: str, username: str, password: str) -> list[str]:
    client = _client(server_url, username, password)
    return [cal.name or cal.id for cal in client.principal().calendars()]


def find_by_uid(server_url: str, username: str, password: str, uid: str) -> bool:
    client = _client(server_url, username, password)
    for cal in client.principal().calendars():
        try:
            cal.get_event_by_uid(uid)
            return True
        except ConsistencyError:
            return True
        except NotFoundError:
            continue
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
    principal = client.principal()
    calendars = principal.calendars()
    if not calendars:
        raise CalendarNotFoundError("На сервере нет календарей")
    calendars[0].add_event(dtstart=start, dtend=end, uid=uid, summary=summary)


def friendly_error(exc: Exception) -> str:
    if isinstance(exc, AuthorizationError):
        return "Неверный логин или пароль"
    if isinstance(exc, NotFoundError):
        return "Сервер не поддерживает CalDAV или адрес указан неверно"
    if isinstance(exc, (ConnectionRefusedError, TimeoutError)):
        return "Не удалось подключиться к серверу"
    if isinstance(exc, CalendarNotFoundError):
        return str(exc)
    if isinstance(exc, DAVError):
        return "Ошибка CalDAV-протокола"
    if isinstance(exc, OSError):
        return "Ошибка сети при подключении"
    return f"{type(exc).__name__}: {exc}"
