from aiogram import F, Router
from aiogram.types import CallbackQuery
from sqlalchemy import func, select

from db.models import NotifySetting, async_session, ensure_user_id
from keyboards.inline import notify_settings_kb

router = Router()

MAX_NOTIFICATIONS = 10


def _text() -> str:
    return (
        "🔔 Настройка уведомлений\n\n"
        "Включите, за сколько времени напоминать о старте контеста.\n"
        "Напоминания приходят только по контестам, где нажата кнопка «Буду участвовать»."
    )


@router.callback_query(F.data == "notify_settings")
async def notify_settings_menu(callback: CallbackQuery) -> None:
    user_id = await ensure_user_id(callback.from_user.id)
    async with async_session() as session:
        active = set(
            (await session.scalars(select(NotifySetting.offset_minutes).where(NotifySetting.user_id == user_id))).all()
        )
    await callback.message.edit_text(_text(), reply_markup=notify_settings_kb(active))
    await callback.answer()


@router.callback_query(F.data.startswith("notif_toggle:"))
async def notif_toggle(callback: CallbackQuery) -> None:
    offset = int(callback.data.split(":", 1)[1])
    user_id = await ensure_user_id(callback.from_user.id)
    async with async_session() as session:
        existing = await session.scalar(
            select(NotifySetting).where(
                NotifySetting.user_id == user_id, NotifySetting.offset_minutes == offset
            )
        )
        if existing is not None:
            await session.delete(existing)
            await session.commit()
        else:
            count = await session.scalar(
                select(func.count(NotifySetting.id)).where(NotifySetting.user_id == user_id)
            )
            if count >= MAX_NOTIFICATIONS:
                await callback.answer(
                    f"Можно включить не более {MAX_NOTIFICATIONS} напоминаний", show_alert=True
                )
                return
            session.add(NotifySetting(user_id=user_id, offset_minutes=offset))
            await session.commit()
    await notify_settings_menu(callback)
