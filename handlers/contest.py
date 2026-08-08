import asyncio
from datetime import timedelta

from aiogram import F, Router
from aiogram.types import CallbackQuery, Message
from sqlalchemy import select

from db.models import Calendar, Contest, Registration, async_session, ensure_user_id
from keyboards.inline import to_calendar_settings_kb, warning_kb
from services.caldav_service import add_event, find_by_uid, friendly_error
from services.text import to_utc_aware

router = Router()

PROCESSING: dict[int, dict] = {}


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
    contest_id = int(callback.data.split(":", 1)[1])
    tg_id = callback.from_user.id
    if tg_id in PROCESSING:
        await callback.answer("Уже выполняется операция, подождите", show_alert=True)
        return
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
    if contest is None:
        await callback.answer("Контест не найден", show_alert=True)
        return

    async with async_session() as session:
        existing = await session.scalar(
            select(Registration).where(
                Registration.user_id == user_id, Registration.contest_id == contest_id
            )
        )
        if existing is None:
            session.add(Registration(user_id=user_id, contest_id=contest_id))
            await session.commit()

    if not calendars:
        await callback.message.edit_text(
            "✅ Участие зафиксировано! Напомним о старте.\n\n"
            "⚠️ Подключите календарь в профиле, чтобы события контестов автоматически попадали в него.",
            reply_markup=to_calendar_settings_kb(),
        )
        await callback.answer()
        return

    tasks = [{"calendar": cal, "status": "pending", "detail": "", "dup": False} for cal in calendars]
    PROCESSING[tg_id] = {"contest": contest, "tasks": tasks, "pending": list(tasks), "current": None}
    await callback.message.edit_text("⏳ Добавляю события в календари…")
    await _process_next(tg_id, callback.message)


async def _process_next(tg_id: int, message: Message) -> None:
    state = PROCESSING.get(tg_id)
    if state is None:
        return
    contest = state["contest"]
    uid = f"cf-contest-{contest.cf_id}"
    while state["pending"]:
        task = state["pending"].pop(0)
        cal = task["calendar"]
        try:
            exists = await asyncio.to_thread(find_by_uid, cal.server_url, cal.username, cal.password, uid)
        except Exception as exc:
            task["status"] = "error"
            task["detail"] = friendly_error(exc)
            continue
        if exists:
            task["status"] = "warning"
            state["current"] = task
            await message.edit_text(
                f"⚠️ В календаре «{calendar_display(cal)}» уже есть событие для контеста «{contest.name}».\n\n"
                "Что сделать?",
                reply_markup=warning_kb(cal.id),
            )
            return
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
    PROCESSING.pop(tg_id, None)


@router.callback_query(F.data.startswith("warn_add:"))
async def warn_add(callback: CallbackQuery) -> None:
    await _warn_decision(callback, add_duplicate=True)


@router.callback_query(F.data.startswith("warn_skip:"))
async def warn_skip(callback: CallbackQuery) -> None:
    await _warn_decision(callback, add_duplicate=False)


async def _warn_decision(callback: CallbackQuery, add_duplicate: bool) -> None:
    tg_id = callback.from_user.id
    cal_id = int(callback.data.split(":", 1)[1])
    state = PROCESSING.get(tg_id)
    task = state.get("current") if state else None
    if state is None or task is None or task["calendar"].id != cal_id:
        await callback.answer("Операция устарела", show_alert=True)
        return
    contest = state["contest"]
    cal = task["calendar"]
    times = _event_times(contest)
    if add_duplicate and times is not None:
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
    elif not add_duplicate:
        task["status"] = "not_added"
    else:
        task["status"] = "error"
        task["detail"] = "Контест без времени старта"
    state["current"] = None
    await _process_next(tg_id, callback.message)
    await callback.answer()


async def _show_summary(tg_id: int, message: Message) -> None:
    state = PROCESSING[tg_id]
    added = [t for t in state["tasks"] if t["status"] == "added" and not t["dup"]]
    warnings = [t for t in state["tasks"] if t["dup"] or t["status"] == "not_added"]
    errors = [t for t in state["tasks"] if t["status"] == "error"]

    parts = ["✅ Участие зафиксировано! Уведомления о старте придут автоматически."]
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
    await message.edit_text("\n\n".join(parts))
