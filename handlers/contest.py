import asyncio
import logging
from datetime import datetime, timedelta, timezone

from aiogram import F, Router
from aiogram.types import CallbackQuery, Message
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from db.models import Calendar, Contest, Registration, async_session, ensure_user_id
from handlers.common import safe_edit_text
from keyboards.inline import to_calendar_settings_kb
from services.caldav_service import add_event, find_by_uid, friendly_error, list_events_between
from services.crypto import KEY_CHANGED_MSG, key_hash
from services.text import format_contest_info, format_dt_msk, to_utc_aware

logger = logging.getLogger(__name__)

router = Router()

PROCESSING_TIMEOUT_SECONDS = 300
# Состояние обработки «Буду участвовать» на пользователя и контест: aiogram
# обрабатывает апдейты конкурентно (create_task), поэтому запись ведётся по паре
# (tg_id, contest_id), а сама обработка CalDAV запускается фоновой задачей —
# нажатие на другой контест не блокируется текущей операцией.
PROCESSING: dict[tuple[int, int], dict] = {}

MAX_OVERLAPS_DISPLAYED = 3

# Фоновые задачи обработки «Буду участвовать»: храним ссылки, чтобы задачи не
# собирались GC и могли быть отменены при остановке бота (иначе — падение на
# закрытой БД и «Task exception was never retrieved»).
_BACKGROUND_TASKS: set[asyncio.Task] = set()


def _spawn_task(coro) -> asyncio.Task:
    task = asyncio.create_task(coro)
    _BACKGROUND_TASKS.add(task)
    task.add_done_callback(_BACKGROUND_TASKS.discard)
    task.add_done_callback(lambda t: None if t.cancelled() else t.exception())
    return task


async def cancel_background_tasks() -> None:
    tasks = list(_BACKGROUND_TASKS)
    _BACKGROUND_TASKS.clear()
    for task in tasks:
        task.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)


def _int_param(data: str) -> int | None:
    try:
        return int(data.split(":", 1)[1])
    except (ValueError, IndexError):
        return None


def _is_stale(state: dict) -> bool:
    age = datetime.now(timezone.utc).replace(tzinfo=None) - state.get("started_at", datetime.min)
    return age.total_seconds() > PROCESSING_TIMEOUT_SECONDS


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
    await _register_for_contest(callback, callback.from_user.id, contest_id)


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

    tasks = [{"calendar": cal, "status": "pending", "detail": "", "overlap": None} for cal in calendars]
    stale = PROCESSING.get((tg_id, contest_id))
    if stale is not None and _is_stale(stale):
        PROCESSING.pop((tg_id, contest_id), None)
    PROCESSING[(tg_id, contest_id)] = {
        "contest": contest,
        "tasks": tasks,
        "pending": list(tasks),
        "started_at": datetime.now(timezone.utc).replace(tzinfo=None),
    }
    await safe_edit_text(
        callback.message,
        f"✅ Участие подтверждено! ⏳ Добавляю события в календари…\n\n{format_contest_info(contest)}",
    )
    _spawn_task(_process_next(tg_id, contest_id, callback.message))


async def _process_next(tg_id: int, contest_id: int, message: Message) -> None:
    key = (tg_id, contest_id)
    state = PROCESSING.get(key)
    if state is None or _is_stale(state):
        PROCESSING.pop(key, None)
        await safe_edit_text(
            message,
            "⏱ Операция прервана (таймаут обработки). Нажмите «Буду участвовать» ещё раз.",
        )
        return
    contest = state["contest"]
    uid = f"cf-contest-{contest.cf_id}"
    try:
        while state["pending"]:
            if _is_stale(state):
                break
            task = state["pending"].pop(0)
            cal = task["calendar"]
            if cal.key_hash is not None and cal.key_hash != key_hash():
                task["status"] = "error"
                task["detail"] = KEY_CHANGED_MSG
                continue
            try:
                exists = await asyncio.to_thread(
                    find_by_uid, cal.server_url, cal.username, cal.password, uid, cal.calendar_url
                )
            except Exception as exc:
                task["status"] = "error"
                task["detail"] = friendly_error(exc)
                continue
            if exists:
                task["status"] = "warning"
                task["detail"] = "контест уже есть в календаре"
                continue
            times = _event_times(contest)
            if times is None:
                task["status"] = "error"
                task["detail"] = "Контест без времени старта"
                continue
            try:
                overlaps = await asyncio.to_thread(
                    list_events_between,
                    cal.server_url,
                    cal.username,
                    cal.password,
                    times[0],
                    times[1],
                    cal.calendar_url,
                    uid,
                )
            except Exception as exc:
                logger.warning("Failed to list events for overlap check: %s", exc)
                overlaps = []
                task["overlap_unknown"] = True
            if overlaps:
                task["overlap"] = _render_overlaps(overlaps)
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
                    calendar_url=cal.calendar_url,
                )
                task["status"] = "added"
            except Exception as exc:
                task["status"] = "error"
                task["detail"] = friendly_error(exc)
        if _is_stale(state):
            await safe_edit_text(
                message,
                "⏱ Операция прервана (таймаут обработки). Нажмите «Буду участвовать» ещё раз.",
            )
            return
        await _show_summary(tg_id, contest_id, message)
    finally:
        PROCESSING.pop((tg_id, contest_id), None)


def _render_overlaps(overlaps: list[dict]) -> str:
    shown = overlaps[:MAX_OVERLAPS_DISPLAYED]
    parts = [f"«{e['summary']}» {format_dt_msk(e['start'])}–{format_dt_msk(e['end'])}" for e in shown]
    rest = len(overlaps) - len(shown)
    if rest > 0:
        parts.append(f"и ещё {rest}")
    return ", ".join(parts)


async def _show_summary(tg_id: int, contest_id: int, message: Message) -> None:
    state = PROCESSING.get((tg_id, contest_id))
    if state is None:
        return
    added = [
        t for t in state["tasks"]
        if t["status"] == "added" and not t.get("overlap") and not t.get("overlap_unknown")
    ]
    warnings = [
        t
        for t in state["tasks"]
        if t["status"] == "warning"
        or (t["status"] == "added" and (t.get("overlap") or t.get("overlap_unknown")))
    ]
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
        lines = []
        for t in warnings:
            if t["status"] == "warning":
                lines.append(f"• {calendar_display(t['calendar'])} — {t['detail']}")
            elif t.get("overlap_unknown"):
                lines.append(f"• {calendar_display(t['calendar'])} — добавлено, проверить пересечения не удалось")
            else:
                lines.append(f"• {calendar_display(t['calendar'])} — добавлено, пересекается с {t['overlap']}")
        parts.append("⚠️ Наслоение событий:\n" + "\n".join(lines))
    if errors:
        parts.append(
            "❌ Ошибка при добавлении:\n"
            + "\n".join(f"• {calendar_display(t['calendar'])}: {t['detail']}" for t in errors)
        )
    parts.append("🔗 https://codeforces.com/contests")
    try:
        await safe_edit_text(message, "\n\n".join(parts))
    except Exception:
        logger.exception("Failed to show summary to user %s", tg_id)
        try:
            await message.answer("✅ Участие подтверждено! Подробности недоступны — нажмите «Буду участвовать» повторно.")
        except Exception:
            logger.exception("Failed to send fallback summary to user %s", tg_id)
