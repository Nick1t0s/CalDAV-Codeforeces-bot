import asyncio
from datetime import datetime, timedelta, timezone

from aiogram import F, Router
from aiogram.types import CallbackQuery, Message
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from db.models import Calendar, Contest, Registration, async_session, ensure_user_id
from handlers.common import safe_edit_text
from keyboards.inline import to_calendar_settings_kb, warning_kb
from services.caldav_service import add_event, find_by_uid, friendly_error
from services.crypto import KEY_CHANGED_MSG, key_hash
from services.text import format_contest_info, to_utc_aware

router = Router()

PROCESSING_TIMEOUT_SECONDS = 300
PROCESSING: dict[int, dict] = {}
_LOCKS: dict[int, asyncio.Lock] = {}


def _int_param(data: str) -> int | None:
    try:
        return int(data.split(":", 1)[1])
    except (ValueError, IndexError):
        return None


def _is_stale(state: dict) -> bool:
    age = datetime.now(timezone.utc).replace(tzinfo=None) - state.get("started_at", datetime.min)
    return age.total_seconds() > PROCESSING_TIMEOUT_SECONDS


def _deadline_remaining(state: dict) -> float:
    age = datetime.now(timezone.utc).replace(tzinfo=None) - state["started_at"]
    return max(1.0, PROCESSING_TIMEOUT_SECONDS - age.total_seconds())


def calendar_display(cal: Calendar) -> str:
    return cal.username or cal.server_url


def _event_times(contest: Contest) -> tuple | None:
    if contest.start_time is None:
        return None
    start = to_utc_aware(contest.start_time)
    end = start + timedelta(seconds=contest.duration_seconds or 3600)
    return start, end


@router.callback_query(F.data.startswith("reg:"))
async def register_for_contest(callback: CallbackQuery) -> None:
    contest_id = _int_param(callback.data)
    if contest_id is None:
        await callback.answer("Неверные данные", show_alert=True)
        return
    tg_id = callback.from_user.id
    lock = _LOCKS.setdefault(tg_id, asyncio.Lock())
    if lock.locked():
        await callback.answer(
            "❌ Слишком много нажатий! Операция уже выполняется, подождите", show_alert=True
        )
        return
    async with lock:
        await _register_for_contest(callback, tg_id, contest_id)


async def _register_for_contest(callback: CallbackQuery, tg_id: int, contest_id: int) -> None:
    user_id = await ensure_user_id(tg_id)

    async with async_session() as session:
        contest = await session.get(Contest, contest_id)
        calendars = list(
            (
                await session.scalars(
                    select(Calendar).where(Calendar.user_id == user_id, Calendar.is_active.is_(True))
                )
            ).all()
        )
        existing = await session.scalar(
            select(Registration).where(
                Registration.user_id == user_id, Registration.contest_id == contest_id
            )
        )
    if contest is None:
        await callback.answer("Контест не найден", show_alert=True)
        return
    registered_now = existing is None
    if registered_now:
        try:
            async with async_session() as session:
                session.add(Registration(user_id=user_id, contest_id=contest_id))
                await session.commit()
        except IntegrityError:
            registered_now = False
    await callback.answer()

    if not registered_now:
        await safe_edit_text(
            callback.message,
            f"✅ Участие подтверждено!\n\n{format_contest_info(contest)}",
        )
        return

    if not calendars:
        await safe_edit_text(
            callback.message,
            f"✅ Участие подтверждено!\n\n{format_contest_info(contest)}\n\n"
            "⚠️ Подключите календарь в профиле, чтобы события контестов автоматически попадали в него.",
            reply_markup=to_calendar_settings_kb(),
        )
        return

    tasks = [{"calendar": cal, "status": "pending", "detail": "", "dup": False} for cal in calendars]
    PROCESSING[tg_id] = {
        "contest": contest,
        "tasks": tasks,
        "pending": list(tasks),
        "current": None,
        "future": None,
        "started_at": datetime.now(timezone.utc).replace(tzinfo=None),
    }
    await safe_edit_text(
        callback.message,
        f"✅ Участие подтверждено! ⏳ Добавляю события в календари…\n\n{format_contest_info(contest)}",
    )
    await _process_next(tg_id, callback.message)


async def _process_next(tg_id: int, message: Message) -> None:
    state = PROCESSING.get(tg_id)
    if state is None or _is_stale(state):
        PROCESSING.pop(tg_id, None)
        return
    contest = state["contest"]
    uid = f"cf-contest-{contest.cf_id}"
    try:
        while state["pending"]:
            task = state["pending"].pop(0)
            cal = task["calendar"]
            if cal.key_hash is not None and cal.key_hash != key_hash():
                task["status"] = "error"
                task["detail"] = KEY_CHANGED_MSG
                continue
            try:
                exists = await asyncio.to_thread(
                    find_by_uid, cal.server_url, cal.username, cal.password, uid
                )
            except Exception as exc:
                task["status"] = "error"
                task["detail"] = friendly_error(exc)
                continue
            if exists:
                task["status"] = "warning"
                state["current"] = task
                state["future"] = asyncio.get_running_loop().create_future()
                await safe_edit_text(
                    message,
                    f"⚠️ В календаре «{calendar_display(cal)}» уже есть событие для контеста «{contest.name}».\n\n"
                    f"{format_contest_info(contest)}\n\n"
                    "Что сделать?",
                    reply_markup=warning_kb(cal.id),
                )
                try:
                    add_duplicate = await asyncio.wait_for(
                        state["future"], timeout=_deadline_remaining(state)
                    )
                except asyncio.TimeoutError:
                    add_duplicate = False
                finally:
                    state["current"] = None
                    state["future"] = None
                if add_duplicate:
                    times = _event_times(contest)
                    if times is None:
                        task["status"] = "error"
                        task["detail"] = "Контест без времени старта"
                    else:
                        try:
                            await asyncio.to_thread(
                                add_event,
                                cal.server_url,
                                cal.username,
                                cal.password,
                                uid=f"cf-contest-{contest.cf_id}-dup",
                                summary=contest.name,
                                start=times[0],
                                end=times[1],
                            )
                            task["status"] = "added"
                            task["dup"] = True
                        except Exception as exc:
                            task["status"] = "error"
                            task["detail"] = friendly_error(exc)
                else:
                    task["status"] = "not_added"
                continue
            times = _event_times(contest)
            if times is None:
                task["status"] = "error"
                task["detail"] = "Контест без времени старта"
                continue
            try:
                await asyncio.to_thread(
                    add_event,
                    cal.server_url,
                    cal.username,
                    cal.password,
                    uid=uid,
                    summary=contest.name,
                    start=times[0],
                    end=times[1],
                )
                task["status"] = "added"
            except Exception as exc:
                task["status"] = "error"
                task["detail"] = friendly_error(exc)
        await _show_summary(tg_id, message)
    finally:
        PROCESSING.pop(tg_id, None)


@router.callback_query(F.data.startswith("warn_add:"))
async def warn_add(callback: CallbackQuery) -> None:
    await _warn_decision(callback, add_duplicate=True)


@router.callback_query(F.data.startswith("warn_skip:"))
async def warn_skip(callback: CallbackQuery) -> None:
    await _warn_decision(callback, add_duplicate=False)


async def _warn_decision(callback: CallbackQuery, add_duplicate: bool) -> None:
    tg_id = callback.from_user.id
    cal_id = _int_param(callback.data)
    if cal_id is None:
        await callback.answer("Неверные данные", show_alert=True)
        return
    state = PROCESSING.get(tg_id)
    task = state.get("current") if state else None
    future = state.get("future") if state else None
    if (
        state is None
        or _is_stale(state)
        or task is None
        or task["calendar"].id != cal_id
        or future is None
        or future.done()
    ):
        await callback.answer("Операция устарела", show_alert=True)
        return
    future.set_result(add_duplicate)
    state["current"] = None
    await callback.answer()


async def _show_summary(tg_id: int, message: Message) -> None:
    state = PROCESSING.get(tg_id)
    if state is None:
        return
    added = [t for t in state["tasks"] if t["status"] == "added" and not t["dup"]]
    warnings = [t for t in state["tasks"] if t["dup"] or t["status"] == "not_added"]
    errors = [t for t in state["tasks"] if t["status"] == "error"]

    parts = [
        "✅ Участие подтверждено! Уведомления о старте придут автоматически.",
        format_contest_info(state["contest"]),
    ]
    if added:
        parts.append(
            "✅ Успешно добавлено в:\n" + "\n".join(f"• {calendar_display(t['calendar'])}" for t in added)
        )
    if warnings:
        lines = [
            f"• {calendar_display(t['calendar'])} — "
            f"{'добавлено' if t['status'] == 'added' else 'не добавлено'}"
            for t in warnings
        ]
        parts.append("⚠️ Наслоение событий:\n" + "\n".join(lines))
    if errors:
        parts.append(
            "❌ Ошибка при добавлении:\n"
            + "\n".join(f"• {calendar_display(t['calendar'])}: {t['detail']}" for t in errors)
        )
    parts.append("🔗 https://codeforces.com/contests")
    await safe_edit_text(message, "\n\n".join(parts))
