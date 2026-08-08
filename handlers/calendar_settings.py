from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery
from sqlalchemy import func, select

from db.models import Calendar, async_session, ensure_user_id
from handlers.calendar_common import render_calendar_menu
from keyboards.inline import calendar_type_kb

router = Router()

MAX_CALENDARS = 10


@router.callback_query(F.data == "cal_settings")
async def cal_settings(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await render_calendar_menu(callback.from_user.id, callback.message)
    await callback.answer()


@router.callback_query(F.data.startswith("cal_toggle:"))
async def cal_toggle(callback: CallbackQuery) -> None:
    cal_id = int(callback.data.split(":", 1)[1])
    user_id = await ensure_user_id(callback.from_user.id)
    async with async_session() as session:
        cal = await session.get(Calendar, cal_id)
        if cal is not None and cal.user_id == user_id:
            cal.is_active = not cal.is_active
            await session.commit()
    await render_calendar_menu(callback.from_user.id, callback.message)
    await callback.answer()


@router.callback_query(F.data.startswith("cal_delete:"))
async def cal_delete(callback: CallbackQuery) -> None:
    cal_id = int(callback.data.split(":", 1)[1])
    user_id = await ensure_user_id(callback.from_user.id)
    async with async_session() as session:
        cal = await session.get(Calendar, cal_id)
        if cal is not None and cal.user_id == user_id:
            await session.delete(cal)
            await session.commit()
    await render_calendar_menu(callback.from_user.id, callback.message)
    await callback.answer()


@router.callback_query(F.data == "cal_add")
async def cal_add(callback: CallbackQuery) -> None:
    user_id = await ensure_user_id(callback.from_user.id)
    async with async_session() as session:
        count = await session.scalar(select(func.count(Calendar.id)).where(Calendar.user_id == user_id))
    if count >= MAX_CALENDARS:
        await callback.answer(f"Можно подключить не более {MAX_CALENDARS} календарей", show_alert=True)
        return
    await callback.message.edit_text("Какой календарь подключить?", reply_markup=calendar_type_kb())
    await callback.answer()
