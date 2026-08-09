import logging
from datetime import date, datetime, time, timedelta, timezone

import caldav
from caldav.lib.error import (
    AuthorizationError,
    ConsistencyError,
    NotFoundError,
    RateLimitError,
    ResponseError,
)
from dateutil.rrule import rrulestr

from services.crypto import KeyChangedError, KEY_CHANGED_MSG, decrypt

logger = logging.getLogger(__name__)

# Буфер вокруг окна контеста для раскрытия повторяющихся событий.
_OVERLAP_BUFFER = timedelta(days=1)


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


def _target_calendar(principal: caldav.Principal, calendar_url: str | None = None) -> caldav.Calendar:
    if calendar_url:
        return principal.client.calendar(url=calendar_url)
    calendars = principal.calendars()
    if not calendars:
        raise CalendarNotFoundError("На сервере нет календарей")
    return calendars[0]


def _calendar_label(cal: caldav.Calendar) -> str:
    return cal.get_display_name() or cal.id or str(cal.url)


def list_calendars(server_url: str, username: str, password: str) -> list[tuple[str, str]]:
    client = _client(server_url, username, password, encrypted=False)
    return [
        (str(cal.url), _calendar_label(cal)) for cal in client.principal().calendars()
    ]


def find_by_uid(
    server_url: str, username: str, password: str, uid: str, calendar_url: str | None = None
) -> bool:
    client = _client(server_url, username, password)
    cal = _target_calendar(client.principal(), calendar_url)
    try:
        cal.get_event_by_uid(uid)
        return True
    except ConsistencyError:
        return True
    except NotFoundError:
        return False


def _dt_value(value) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
    if isinstance(value, date):
        return datetime.combine(value, time.min).replace(tzinfo=timezone.utc)
    return None


def _to_utc_naive(dt: datetime) -> datetime:
    """Нормализует datetime в UTC (naive), чтобы сравнение не зависело от TZID."""
    return dt.astimezone(timezone.utc).replace(tzinfo=None)


def _flatten_dates(values) -> list[datetime]:
    out: list[datetime] = []
    for value in values or []:
        if isinstance(value, (list, tuple)):
            out.extend(_flatten_dates(value))
        else:
            dt = _dt_value(value)
            if dt is not None:
                out.append(dt)
    return out


def _rrule_values(vevent) -> list[str]:
    rrule = getattr(vevent, "rrule", None)
    if rrule is None:
        return []
    values = rrule.value
    if isinstance(values, str):
        return [values]
    return list(values or [])


def _event_occurrences(vevent, win_start: datetime, win_end: datetime) -> list[tuple[datetime, datetime]]:
    dtstart = _dt_value(getattr(getattr(vevent, "dtstart", None), "value", None))
    if dtstart is None:
        return []
    duration = getattr(getattr(vevent, "duration", None), "value", None) or timedelta(hours=1)
    dtend = _dt_value(getattr(getattr(vevent, "dtend", None), "value", None))
    if dtend is None or dtend <= dtstart:
        dtend = dtstart + duration
    excluded = {_to_utc_naive(dt) for dt in _flatten_dates(vevent.getChildValue("exdate"))}

    starts: list[datetime] = []
    for rule_str in _rrule_values(vevent):
        try:
            rule = rrulestr(rule_str, dtstart=dtstart, cache=False)
        except (ValueError, TypeError):
            continue
        starts.extend(rule.between(win_start, win_end, inc=True))
    starts.extend(_flatten_dates(vevent.getChildValue("rdate")))

    if not starts:
        starts = [dtstart]
    return [
        (start, start + (dtend - dtstart))
        for start in starts
        if _to_utc_naive(start) not in excluded
    ]


def list_events_between(
    server_url: str,
    username: str,
    password: str,
    start: datetime,
    end: datetime,
    calendar_url: str | None = None,
    exclude_uid: str | None = None,
) -> list[dict]:
    """Все события календаря (без серверного time-range фильтра), пересекающие окно [start, end]."""
    client = _client(server_url, username, password)
    cal = _target_calendar(client.principal(), calendar_url)
    events = cal.search(event=True, expand=False)
    win_start = start - _OVERLAP_BUFFER
    win_end = end + _OVERLAP_BUFFER
    found: list[tuple[datetime, datetime, str]] = []
    seen: set[tuple[datetime, datetime]] = set()
    for event in events:
        try:
            vevent = event.vobject_instance.vevent
        except (AttributeError, ValueError):
            continue
        uid = getattr(getattr(vevent, "uid", None), "value", None)
        if exclude_uid and uid and str(uid) == exclude_uid:
            continue
        status = getattr(getattr(vevent, "status", None), "value", None)
        if status and str(status).upper() == "CANCELLED":
            continue
        summary = str(getattr(getattr(vevent, "summary", None), "value", None) or "Без названия")
        for ev_start, ev_end in _event_occurrences(vevent, win_start, win_end):
            if not (ev_start < end and ev_end > start):
                continue
            key = (ev_start, ev_end)
            if key in seen:
                continue
            seen.add(key)
            found.append((ev_start, ev_end, summary))
    found.sort()
    return [{"start": s, "end": e, "summary": summary} for s, e, summary in found]


def add_event(
    server_url: str,
    username: str,
    password: str,
    *,
    uid: str,
    summary: str,
    start,
    end,
    calendar_url: str | None = None,
) -> None:
    # Известное ограничение: событие создаётся один раз и в дальнейшем не
    # синхронизируется. Если Codeforces перенесёт контест (случается редко, на
    # 30–60 минут из-за технических проблем), время в календаре обновится только
    # при повторном добавлении; база контестов при этом обновляется парсером.
    client = _client(server_url, username, password)
    cal = _target_calendar(client.principal(), calendar_url)
    cal.add_event(dtstart=start, dtend=end, uid=uid, summary=summary)


def friendly_error(exc: Exception) -> str:
    logger.warning("CalDAV error: %s", exc)
    if isinstance(exc, KeyChangedError):
        return KEY_CHANGED_MSG
    if isinstance(exc, AuthorizationError):
        return "Неверные данные доступа"
    if isinstance(exc, CalendarNotFoundError):
        return str(exc)
    if isinstance(exc, NotFoundError):
        return "Календарь не найден по указанному адресу"
    if isinstance(exc, RateLimitError):
        return "Сервер временно перегружен. Попробуйте позже"
    if isinstance(exc, ResponseError):
        return "Сервер вернул ошибку. Проверьте адрес и права доступа"
    # Пользователю не показываем текст исключения и URL (в DAVError лежит адрес) —
    # только обобщённую причину.
    try:
        from niquests.exceptions import (
            ConnectionError as NiquestsConnectionError,
            SSLError as NiquestsSSLError,
            Timeout as NiquestsTimeout,
        )
    except ImportError:
        NiquestsTimeout = NiquestsConnectionError = NiquestsSSLError = None
    if NiquestsTimeout is not None and isinstance(exc, NiquestsTimeout):
        return "Сервер не отвечает (таймаут). Попробуйте позже"
    if NiquestsSSLError is not None and isinstance(exc, NiquestsSSLError):
        return "Ошибка защищённого соединения (SSL). Убедитесь, что сервер поддерживает HTTPS"
    if NiquestsConnectionError is not None and isinstance(exc, NiquestsConnectionError):
        return "Не удалось подключиться к серверу. Проверьте адрес"
    if isinstance(exc, TimeoutError):
        return "Сервер не отвечает (таймаут). Попробуйте позже"
    if isinstance(exc, ValueError):
        return "Неверный адрес сервера"
    return "Сервер не отвечает или не поддерживает CalDAV"
