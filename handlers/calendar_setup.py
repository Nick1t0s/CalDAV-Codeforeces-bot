import asyncio
from urllib.parse import urlparse

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from sqlalchemy import func, select

from config import YANDEX_CALDAV_URL, is_admin
from db.models import Calendar, async_session, ensure_user_id
from handlers.calendar_common import render_calendar_menu
from handlers.calendar_settings import MAX_CALENDARS
from handlers.common import safe_edit_text
from keyboards.inline import (
    calendar_pick_kb,
    calendar_type_kb,
    guide_kb,
    http_confirm_kb,
    main_menu_kb,
    retry_cancel_kb,
)
from services.caldav_service import friendly_error, list_calendars
from services.crypto import KeyChangedError, decrypt, encrypt, key_hash
from services.guides import get_guide

router = Router()


class CalendarSetup(StatesGroup):
    type = State()
    yandex_email = State()
    yandex_password = State()
    caldav_server = State()
    http_confirm = State()
    caldav_login = State()
    caldav_password = State()
    pick_calendar = State()


def _message_text(message: Message) -> str | None:
    text = message.text
    return text.strip() if text else None


@router.callback_query(F.data == "cal_setup_start")
async def cal_setup_start(callback: CallbackQuery, state: FSMContext) -> None:
    if is_admin(callback.from_user.id):
        await callback.answer("⛔️ Нет доступа.", show_alert=True)
        return
    await state.set_state(CalendarSetup.type)
    await safe_edit_text(callback.message, "Какой календарь подключить?", reply_markup=calendar_type_kb())
    await callback.answer()


@router.callback_query(F.data == "cal_setup_yandex")
async def cal_setup_yandex(callback: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(cal_type="yandex")
    await state.set_state(CalendarSetup.yandex_email)
    await safe_edit_text(callback.message, 
        "📅 Подключение Яндекс Календаря\n\nОтправьте email Яндекс-аккаунта:",
        reply_markup=guide_kb(),
    )
    await callback.answer()


@router.callback_query(F.data == "cal_setup_caldav")
async def cal_setup_caldav(callback: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(cal_type="caldav")
    await state.set_state(CalendarSetup.caldav_server)
    await safe_edit_text(callback.message, 
        "📅 Подключение CalDAV-сервера\n\nОтправьте адрес CalDAV-сервера "
        "(например, https://caldav.example.com/):"
    )
    await callback.answer()


@router.message(CalendarSetup.yandex_email)
async def yandex_email_input(message: Message, state: FSMContext) -> None:
    email = _message_text(message)
    if email is None:
        await message.answer("Пожалуйста, отправьте email текстовым сообщением.")
        return
    await state.update_data(email=email)
    await state.set_state(CalendarSetup.yandex_password)
    await message.answer("Отправьте пароль приложения для CalDAV (нужен пароль приложения, а не основной пароль):", reply_markup=guide_kb())


@router.message(CalendarSetup.caldav_server)
async def caldav_server_input(message: Message, state: FSMContext) -> None:
    server_url = _normalize_server_url(_message_text(message))
    if not server_url:
        await message.answer("Укажите адрес CalDAV-сервера, например https://caldav.example.com/")
        return
    await state.update_data(server_url=server_url)
    if _is_insecure_http(server_url):
        await state.set_state(CalendarSetup.http_confirm)
        await message.answer(
            "⚠️ Адрес указан по протоколу HTTP: пароль будет передаваться на сервер "
            "без шифрования и может быть перехвачен.\n\n"
            "Настоятельно рекомендуется использовать HTTPS. Продолжить?",
            reply_markup=http_confirm_kb(),
        )
        return
    await state.set_state(CalendarSetup.caldav_login)
    await message.answer("Отправьте логин:")


def _normalize_server_url(raw: str | None) -> str:
    url = (raw or "").strip()
    if url and "://" not in url:
        url = "https://" + url
    return url


def _is_insecure_http(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme == "http" and parsed.hostname not in ("localhost", "127.0.0.1")


@router.callback_query(F.data == "cal_http_confirm")
async def cal_http_confirm(callback: CallbackQuery, state: FSMContext) -> None:
    if await state.get_state() != CalendarSetup.http_confirm:
        await callback.answer("Операция устарела, попробуйте ещё раз", show_alert=True)
        return
    await state.set_state(CalendarSetup.caldav_login)
    await safe_edit_text(callback.message, "Отправьте логин:")
    await callback.answer()


@router.callback_query(F.data == "cal_http_edit")
async def cal_http_edit(callback: CallbackQuery, state: FSMContext) -> None:
    if await state.get_state() != CalendarSetup.http_confirm:
        await callback.answer("Операция устарела, попробуйте ещё раз", show_alert=True)
        return
    await state.set_state(CalendarSetup.caldav_server)
    await safe_edit_text(callback.message, "Отправьте адрес CalDAV-сервера (например, https://caldav.example.com/):")
    await callback.answer()


@router.message(CalendarSetup.caldav_login)
async def caldav_login_input(message: Message, state: FSMContext) -> None:
    username = _message_text(message)
    if username is None:
        await message.answer("Пожалуйста, отправьте логин текстовым сообщением.")
        return
    await state.update_data(username=username)
    await state.set_state(CalendarSetup.caldav_password)
    await message.answer("Отправьте пароль:")


@router.message(CalendarSetup.yandex_password)
async def yandex_password_input(message: Message, state: FSMContext) -> None:
    password = _message_text(message)
    if password is None:
        await message.answer("Пожалуйста, отправьте пароль текстовым сообщением.")
        return
    data = await state.get_data()
    await _validate_and_save(message, state, YANDEX_CALDAV_URL, data.get("email", ""), password)


@router.message(CalendarSetup.caldav_password)
async def caldav_password_input(message: Message, state: FSMContext) -> None:
    password = _message_text(message)
    if password is None:
        await message.answer("Пожалуйста, отправьте пароль текстовым сообщением.")
        return
    data = await state.get_data()
    await _validate_and_save(message, state, data.get("server_url", ""), data.get("username", ""), password)


@router.callback_query(F.data == "cal_retry")
async def cal_retry(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    if data.get("cal_type") == "yandex":
        await state.set_state(CalendarSetup.yandex_email)
        await safe_edit_text(callback.message, "Отправьте email Яндекс-аккаунта:", reply_markup=guide_kb())
    else:
        await state.set_state(CalendarSetup.caldav_server)
        await safe_edit_text(callback.message, "Отправьте адрес CalDAV-сервера:")
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
        calendars = await asyncio.to_thread(list_calendars, server_url, username, password)
    except Exception as exc:
        await safe_edit_text(checking, 
            f"❌ Не удалось подключиться: {friendly_error(exc)}",
            reply_markup=retry_cancel_kb(),
        )
        return

    if not calendars:
        await safe_edit_text(checking, "❌ На сервере нет календарей.", reply_markup=retry_cancel_kb())
        return

    if len(calendars) == 1:
        await _save_calendar(message.from_user.id, checking, state, server_url, username, password, calendars[0])
        return

    await state.update_data(
        pick_server_url=server_url,
        pick_username=username,
        pick_password=encrypt(password),
        calendars=calendars,
    )
    await state.set_state(CalendarSetup.pick_calendar)
    await safe_edit_text(
        checking,
        "📅 На аккаунте несколько календарей. Куда добавлять события контестов?",
        reply_markup=calendar_pick_kb(calendars),
    )


@router.callback_query(F.data.startswith("cal_pick:"))
async def cal_pick(callback: CallbackQuery, state: FSMContext) -> None:
    if await state.get_state() != CalendarSetup.pick_calendar:
        await callback.answer("Операция устарела, попробуйте ещё раз", show_alert=True)
        return
    try:
        idx = int(callback.data.split(":", 1)[1])
    except (ValueError, IndexError):
        await callback.answer("Неверные данные", show_alert=True)
        return
    data = await state.get_data()
    calendars = data.get("calendars") or []
    if not (0 <= idx < len(calendars)):
        await callback.answer("Неверные данные", show_alert=True)
        return
    try:
        password = decrypt(data["pick_password"])
    except KeyChangedError:
        await state.clear()
        await safe_edit_text(
            callback.message,
            "❌ Ключ шифрования изменился — начните подключение заново.",
            reply_markup=main_menu_kb(),
        )
        await callback.answer()
        return
    await _save_calendar(
        callback.from_user.id,
        callback.message,
        state,
        data["pick_server_url"],
        data["pick_username"],
        password,
        calendars[idx],
    )
    await callback.answer()


async def _save_calendar(
    tg_id: int,
    message: Message,
    state: FSMContext,
    server_url: str,
    username: str,
    password: str,
    calendar: tuple[str, str] | None,
) -> None:
    user_id = await ensure_user_id(tg_id)
    async with async_session() as session:
        count = await session.scalar(select(func.count(Calendar.id)).where(Calendar.user_id == user_id))
        if count >= MAX_CALENDARS:
            await state.clear()
            await safe_edit_text(message, 
                f"❌ Достигнут лимит календарей ({MAX_CALENDARS}).",
                reply_markup=main_menu_kb(),
            )
            return
        data = await state.get_data()
        cal = Calendar(
            user_id=user_id,
            type=data.get("cal_type", "caldav"),
            server_url=server_url,
            username=username,
            password=encrypt(password),
            key_hash=key_hash(),
            calendar_url=calendar[0] if calendar else None,
            name=calendar[1] if calendar else None,
        )
        session.add(cal)
        await session.commit()
    # Проверка count перед INSERT не атомарна (SQLite не умеет row-locks):
    # при параллельных подключениях лимит мог быть превышен другим потоком,
    # поэтому после коммита пересчитываем и откатываем лишний календарь.
    async with async_session() as session:
        count = await session.scalar(select(func.count(Calendar.id)).where(Calendar.user_id == user_id))
        if count > MAX_CALENDARS:
            await session.delete(cal)
            await session.commit()
            await state.clear()
            await safe_edit_text(message, 
                f"❌ Достигнут лимит календарей ({MAX_CALENDARS}).",
                reply_markup=main_menu_kb(),
            )
            return
    await state.clear()
    await render_calendar_menu(tg_id, message, "✅ Календарь подключён!")
