from datetime import datetime, timezone
from zoneinfo import ZoneInfo

MSK = ZoneInfo("Europe/Moscow")


def to_utc_aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def format_duration(seconds: int) -> str:
    hours, minutes = divmod(seconds // 60, 60)
    if hours and minutes:
        return f"{hours} ч {minutes} мин"
    if hours:
        return f"{hours} ч"
    return f"{minutes} мин"


def _plural(number: int, one: str, few: str, many: str) -> str:
    mod10 = number % 10
    mod100 = number % 100
    if mod10 == 1 and mod100 != 11:
        return one
    if 2 <= mod10 <= 4 and not 12 <= mod100 <= 14:
        return few
    return many


def format_minutes(minutes: int) -> str:
    """Человекочитаемое «через N недель/дней/часов/минут» с русской плюрализацией."""
    if minutes < 1:
        minutes = 1
    units: list[tuple[int, str, str, str]] = [
        (7 * 24 * 60, "неделя", "недели", "недель"),
        (24 * 60, "день", "дня", "дней"),
        (60, "час", "часа", "часов"),
        (1, "минута", "минуты", "минут"),
    ]
    parts: list[str] = []
    remaining = minutes
    for size, one, few, many in units:
        value, remaining = divmod(remaining, size)
        if value:
            parts.append(f"{value} {_plural(value, one, few, many)}")
    return " ".join(parts[:2]) if parts else "0 минут"


def format_dt_msk(dt: datetime) -> str:
    return to_utc_aware(dt).astimezone(MSK).strftime("%d.%m.%Y %H:%M")


def format_contest_info(contest) -> str:
    lines = [f"🏆 {contest.name}", f"📋 Тип: {contest.type}"]
    if contest.start_time is not None:
        lines.append(f"🕒 {format_dt_msk(contest.start_time)} (МСК)")
    lines.append(f"⏱ {format_duration(contest.duration_seconds)}")
    lines.append(f"🔗 https://codeforces.com/contest/{contest.cf_id}")
    return "\n".join(lines)
