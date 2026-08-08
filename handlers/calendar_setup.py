import asyncio

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from sqlalchemy import func, select

from config import YANDEX_CALDAV_URL
from db.models import Calendar, async_session, ensure_user_id
from handlers.calendar_common import render_calendar_menu
from handlers.calendar_settings import MAX_CALENDARS
from keyboards.inline import calendar_type_kb, guide_kb, main_menu_kb, retry_cancel_kb
from services.caldav_service import friendly_error, list_calendars
from services.guides import get_guide

router = Router()


class CalendarSetup(StatesGroup):
    type = State()
    yandex_email = State()
    yandex_password = State()
    caldav_server = State()
    caldav_login = State()
    caldav_password = State()


@router.callback_query(F.data == "cal_setup_start")
async def cal_setup_start(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(CalendarSetup.type)
    await callback.message.edit_text("Какой календарь подключить?", reply_markup=calendar_type_kb())
    await callback.answer()


@router.callback_query(F.data == "cal_setup_yandex")
async def cal_setup_yandex(callback: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(cal_type="yandex")
    await state.set_state(CalendarSetup.yandex_email)
    await callback.message.edit_text(
        "📅 Подключение Яндекс Календаря\n\nОтправьте email Яндекс-аккаунта:",
        reply_markup=guide_kb(),
    )
    await callback.answer()


@router.callback_query(F.data == "cal_setup_caldav")
async def cal_setup_caldav(callback: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(cal_type="caldav")
    await state.set_state(CalendarSetup.caldav_server)
    await callback.message.edit_text(
        "📅 Подключение CalDAV-сервера\n\nОтправьте адрес CalDAV-сервера "
        "(например, https://caldav.example.com/):"
    )
    await callback.answer()


@router.message(CalendarSetup.yandex_email)
async def yandex_email_input(message: Message, state: FSMContext) -> None:
    await state.update_data(email=message.text.strip())
    await state.set_state(CalendarSetup.yandex_password)
    await message.answer("Отправьте пароль приложения для CalDAV (нужен пароль приложения, а не основной пароль):", reply_markup=guide_kb())


@router.message(CalendarSetup.caldav_server)
async def caldav_server_input(message: Message, state: FSMContext) -> None:
    await state.update_data(server_url=message.text.strip())
    await state.set_state(CalendarSetup.caldav_login)
    await message.answer("Отправьте логин:")


@router.message(CalendarSetup.caldav_login)
async def caldav_login_input(message: Message, state: FSMContext) -> None:
    await state.update_data(username=message.text.strip())
    await state.set_state(CalendarSetup.caldav_password)
    await message.answer("Отправьте пароль:")


@router.message(CalendarSetup.yandex_password)
async def yandex_password_input(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    await _validate_and_save(message, state, YANDEX_CALDAV_URL, data.get("email", ""), message.text.strip())


@router.message(CalendarSetup.caldav_password)
async def caldav_password_input(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    await _validate_and_save(message, state, data.get("server_url", ""), data.get("username", ""), message.text.strip())


@router.callback_query(F.data == "cal_retry")
async def cal_retry(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    if data.get("cal_type") == "yandex":
        await state.set_state(CalendarSetup.yandex_email)
        await callback.message.edit_text("Отправьте email Яндекс-аккаунта:", reply_markup=guide_kb())
    else:
        await state.set_state(CalendarSetup.caldav_server)
        await callback.message.edit_text("Отправьте адрес CalDAV-сервера:")
    await callback.answer()


@router.callback_query(F.data == "cal_guide")
async def cal_guide(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    guide = get_guide(data.get("cal_type", "yandex"))
    if guide:
        await callback.message.answer(guide)
    await callback.answer()


@router.callback_query(F.data == "cal_cancel")
async def cal_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await render_calendar_menu(callback.from_user.id, callback.message)
    await callback.answer()


@router.message(Command("cancel"))
async def cancel_command(message: Message, state: FSMContext) -> None:
    if await state.get_state() is None:
        await message.answer("Нет активных операций.")
        return
    await state.clear()
    await message.answer("Отменено.")


async def _validate_and_save(message: Message, state: FSMContext, server_url: str, username: str, password: str) -> None:
    checking = await message.answer("⏳ Проверяю подключение…")
    try:
        await asyncio.to_thread(list_calendars, server_url, username, password)
    except Exception as exc:
        await checking.edit_text(
            f"❌ Не удалось подключиться: {friendly_error(exc)}",
            reply_markup=retry_cancel_kb(),
        )
        return

    user_id = await ensure_user_id(message.from_user.id)
    async with async_session() as session:
        count = await session.scalar(select(func.count(Calendar.id)).where(Calendar.user_id == user_id))
        if count >= MAX_CALENDARS:
            await state.clear()
            await checking.edit_text(
                f"❌ Достигнут лимит календарей ({MAX_CALENDARS}).",
                reply_markup=main_menu_kb(),
            )
            return
        data = await state.get_data()
        session.add(
            Calendar(
                user_id=user_id,
                type=data.get("cal_type", "caldav"),
                server_url=server_url,
                username=username,
                password=password,
            )
        )
        await session.commit()
    await state.clear()
    await render_calendar_menu(message.from_user.id, checking, "✅ Календарь подключён!")
