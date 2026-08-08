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


def format_dt_msk(dt: datetime) -> str:
    return to_utc_aware(dt).astimezone(MSK).strftime("%d.%m.%Y %H:%M")


def format_contest_info(contest) -> str:
    lines = [f"🏆 {contest.name}", f"📋 Тип: {contest.type}"]
    if contest.start_time is not None:
        lines.append(f"🕒 {format_dt_msk(contest.start_time)} (МСК)")
    lines.append(f"⏱ {format_duration(contest.duration_seconds)}")
    lines.append(f"🔗 https://codeforces.com/contest/{contest.cf_id}")
    return "\n".join(lines)
