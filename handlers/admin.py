import logging
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy import func, select

from config import is_admin
from db.models import Contest, async_session
from handlers.common import safe_edit_text
from keyboards.inline import admin_cancel_kb, admin_menu_kb
from services.scheduler import announce_contest
from services.text import format_contest_info

logger = logging.getLogger(__name__)

router = Router()

MSK = ZoneInfo("Europe/Moscow")

ADMIN_MENU_TEXT = (
    "🛠 Админ-панель\n\n"
    "Эмуляция нового контеста: контест попадает в базу, а анонс рассылается всем "
    "пользователям, как при реальном появлении на Codeforces."
)
ACCESS_DENIED = "⛔️ Нет доступа."

DEFAULT_DURATION_MINUTES = 120
MAX_DURATION_MINUTES = 1440


class ContestCreate(StatesGroup):
    name = State()
    start_time = State()
    duration = State()
    confirm = State()


def _parse_start_time(raw: str) -> datetime | None:
    raw = raw.strip()
    now_msk = datetime.now(MSK)
    for fmt in ("%Y-%m-%d %H:%M", "%d.%m.%Y %H:%M"):
        try:
            parsed = datetime.strptime(raw, fmt)
        except ValueError:
            continue
        parsed = parsed.replace(tzinfo=MSK)
        if parsed < now_msk:
            return None
        return parsed.astimezone(timezone.utc).replace(tzinfo=None)
    try:
        parsed = datetime.strptime(raw, "%H:%M")
    except ValueError:
        return None
    candidate = now_msk.replace(hour=parsed.hour, minute=parsed.minute, second=0, microsecond=0)
    if candidate <= now_msk:
        candidate += timedelta(days=1)
    return candidate.astimezone(timezone.utc).replace(tzinfo=None)


def _confirm_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Создать и разослать", callback_data="admin_confirm_create")],
            [InlineKeyboardButton(text="Отмена", callback_data="admin_cancel")],
        ]
    )


async def _next_cf_id() -> int:
    async with async_session() as session:
        current = await session.scalar(select(func.max(Contest.cf_id)))
    return (current or 0) + 1


@router.message(Command("admin"))
async def cmd_admin(message: Message) -> None:
    if not is_admin(message.from_user.id):
        await message.answer(ACCESS_DENIED)
        return
    await message.answer(ADMIN_MENU_TEXT, reply_markup=admin_menu_kb())


@router.message(Command("create"))
async def cmd_create(message: Message, state: FSMContext) -> None:
    if not is_admin(message.from_user.id):
        await message.answer(ACCESS_DENIED)
        return
    await _start_contest_create(message, state)


@router.callback_query(F.data == "admin_create_contest")
async def create_contest_from_menu(callback: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(callback.from_user.id):
        await callback.answer(ACCESS_DENIED, show_alert=True)
        return
    await _start_contest_create(callback.message, state)
    await callback.answer()


async def _start_contest_create(message: Message, state: FSMContext) -> None:
    await state.set_state(ContestCreate.name)
    await safe_edit_text(
        message,
        "📢 Эмуляция нового контеста\n\nШаг 1/3 — отправьте название контеста:",
        reply_markup=admin_cancel_kb(),
    )


@router.message(ContestCreate.name)
async def contest_name(message: Message, state: FSMContext) -> None:
    if not is_admin(message.from_user.id):
        await message.answer(ACCESS_DENIED)
        return
    name = message.text.strip()
    if not name:
        await message.answer("Название не может быть пустым. Отправьте название контеста:")
        return
    await state.update_data(name=name)
    await state.set_state(ContestCreate.start_time)
    await safe_edit_text(
        message,
        "Шаг 2/3 — время начала (МСК):\n"
        "• только время: `18:00` — ближайшее из сегодня/завтра\n"
        "• дата и время: `2026-08-10 18:00` или `10.08.2026 18:00`",
        reply_markup=admin_cancel_kb(),
    )


@router.message(ContestCreate.start_time)
async def contest_start_time(message: Message, state: FSMContext) -> None:
    if not is_admin(message.from_user.id):
        await message.answer(ACCESS_DENIED)
        return
    start = _parse_start_time(message.text)
    if start is None:
        await message.answer(
            "Не получилось разобрать время. Форматы: `18:00`, `2026-08-10 18:00` "
            "или `10.08.2026 18:00` (МСК). Дата должна быть в будущем."
        )
        return
    await state.update_data(start_time=start)
    await state.set_state(ContestCreate.duration)
    await safe_edit_text(
        message,
        f"Шаг 3/3 — длительность в минутах. Нажмите без текста для значения по умолчанию "
        f"({DEFAULT_DURATION_MINUTES} мин):",
        reply_markup=admin_cancel_kb(),
    )


@router.message(ContestCreate.duration)
async def contest_duration(message: Message, state: FSMContext) -> None:
    if not is_admin(message.from_user.id):
        await message.answer(ACCESS_DENIED)
        return
    raw = message.text.strip()
    if not raw:
        duration = DEFAULT_DURATION_MINUTES
    else:
        try:
            duration = int(raw)
        except ValueError:
            await message.answer("Длительность — число минут (например, 120). Введите ещё раз:")
            return
        if duration <= 0 or duration > MAX_DURATION_MINUTES:
            await message.answer(f"Длительность должна быть от 1 до {MAX_DURATION_MINUTES} минут:")
            return
    data = await state.get_data()
    await state.update_data(duration_seconds=duration * 60)
    await state.set_state(ContestCreate.confirm)
    contest = SimpleNamespace(
        name=data["name"], type="EMULATED", start_time=data["start_time"], duration_seconds=duration * 60, cf_id=0
    )
    await safe_edit_text(
        message,
        "📢 Итог контеста:\n\n" + format_contest_info(contest) + "\n\nСоздать и разослать анонс?",
        reply_markup=_confirm_kb(),
    )


@router.callback_query(ContestCreate.confirm, F.data == "admin_confirm_create")
async def confirm_create(callback: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(callback.from_user.id):
        await callback.answer(ACCESS_DENIED, show_alert=True)
        return
    data = await state.get_data()
    contest = Contest(
        cf_id=await _next_cf_id(),
        name=data["name"],
        type="EMULATED",
        phase="BEFORE",
        start_time=data["start_time"],
        duration_seconds=data["duration_seconds"],
    )
    async with async_session() as session:
        session.add(contest)
        await session.commit()
        await session.refresh(contest)
    await state.clear()
    delivered = await announce_contest(callback.message.bot, contest)
    await safe_edit_text(
        callback.message,
        "✅ Контест создан и анонс разослан!\n\n"
        f"{format_contest_info(contest)}\n\n"
        f"📨 Доставлено адресатам: {delivered}",
        reply_markup=None,
    )
    await callback.answer()


@router.callback_query(F.data == "admin_cancel")
async def cancel_create(callback: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(callback.from_user.id):
        await callback.answer(ACCESS_DENIED, show_alert=True)
        return
    await state.clear()
    await safe_edit_text(callback.message, "Отменено.", reply_markup=None)
    await callback.answer()