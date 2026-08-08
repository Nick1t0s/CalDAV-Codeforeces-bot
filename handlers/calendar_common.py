from aiogram.types import Message
from sqlalchemy import select

from db.models import Calendar, async_session, ensure_user_id
from handlers.common import safe_edit_text
from keyboards.inline import calendar_settings_kb


async def get_calendars(user_id: int) -> list[Calendar]:
    async with async_session() as session:
        return list(
            (await session.scalars(select(Calendar).where(Calendar.user_id == user_id).order_by(Calendar.id))).all()
        )


def calendars_text(calendars: list[Calendar]) -> str:
    lines = ["📅 Настройка календарей", ""]
    if not calendars:
        lines.append("Календари не подключены.")
    else:
        for i, cal in enumerate(calendars, 1):
            status = "✅ активен" if cal.is_active else "❌ выключен"
            lines.append(f"{i}) {cal.username or cal.server_url} • {status}")
    return "\n".join(lines)


async def render_calendar_menu(tg_id: int, message: Message, prefix: str = "") -> None:
    user_id = await ensure_user_id(tg_id)
    calendars = await get_calendars(user_id)
    text = f"{prefix}\n\n{calendars_text(calendars)}" if prefix else calendars_text(calendars)
    await safe_edit_text(message, text, reply_markup=calendar_settings_kb(calendars))
