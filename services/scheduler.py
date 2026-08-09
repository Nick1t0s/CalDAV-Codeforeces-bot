import asyncio
import logging
import time
from datetime import datetime, timedelta, timezone
from math import ceil

from aiogram import Bot
from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter
from sqlalchemy import delete, select

from config import PARSE_INTERVAL_SECONDS, REMIND_INTERVAL_SECONDS
from db.models import (
    Contest,
    NotificationLog,
    NotifySetting,
    Registration,
    User,
    async_session,
    mark_user_blocked,
)
from keyboards.inline import contest_announce_kb, notify_settings_shortcut_kb
from services.cf_parser import parse_contests
from services.text import format_contest_info, format_dt_msk, format_minutes

logger = logging.getLogger(__name__)

LOG_RETENTION_DAYS = 30
_CLEANUP_INTERVAL_SECONDS = 86400
_last_log_cleanup = 0.0


async def _send_message(bot: Bot, tg_id: int, text: str, reply_markup=None) -> bool:
    for _ in range(3):
        try:
            await bot.send_message(tg_id, text, reply_markup=reply_markup)
            return True
        except TelegramForbiddenError:
            await mark_user_blocked(tg_id)
            return False
        except TelegramRetryAfter as exc:
            await asyncio.sleep(exc.retry_after)
        except Exception:
            logger.exception("Failed to send message to user %s", tg_id)
            return False
    logger.error("Giving up sending message to user %s after retries", tg_id)
    return False


async def broadcast_new_contests(bot: Bot, contests: list[Contest]) -> None:
    if not contests:
        return
    async with async_session() as session:
        tg_ids = list(
            (
                await session.scalars(
                    select(User.tg_id).where(User.is_blocked.is_(False))
                )
            ).all()
        )
    delivered_ids: list[int] = []
    for contest in contests:
        text = "\n".join(
            ["🔥 Новый контест на Codeforces!", "", format_contest_info(contest)]
        )
        delivered = False
        for tg_id in tg_ids:
            if await _send_message(bot, tg_id, text, reply_markup=contest_announce_kb(contest.id)):
                delivered = True
        if delivered:
            delivered_ids.append(contest.id)
    # Помечаем анонсированными только после успешной рассылки (хотя бы одному
    # пользователю), иначе при сбое контест останется неанонсированным и будет
    # разослан повторно на следующем тике.
    async with async_session() as session:
        for contest_id in delivered_ids:
            row = await session.get(Contest, contest_id)
            if row is not None:
                row.announced = True
        await session.commit()


async def send_reminders(bot: Bot) -> None:
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    async with async_session() as session:
        rows = (
            await session.execute(
                select(Registration, Contest)
                .join(Contest, Registration.contest_id == Contest.id)
                .where(Contest.phase == "BEFORE", Contest.start_time.is_not(None))
            )
        ).all()
        active_offsets: dict[int, set[int]] = {}
        for user_id, offset in (
            await session.execute(select(NotifySetting.user_id, NotifySetting.offset_minutes))
        ).all():
            active_offsets.setdefault(user_id, set()).add(offset)
        logged = {
            (user_id, contest_id, offset)
            for user_id, contest_id, offset in (
                await session.execute(
                    select(NotificationLog.user_id, NotificationLog.contest_id, NotificationLog.offset_minutes)
                )
            ).all()
        }
        tg_by_db_id = dict(
            (
                await session.execute(
                    select(User.id, User.tg_id).where(User.is_blocked.is_(False))
                )
            ).all()
        )

    for reg, contest in rows:
        if contest.start_time <= now:
            continue
        remaining = contest.start_time - now
        # Сработавшими считаем все офсеты, чьё окно уже открылось (remaining <= offset).
        # Шлём ОДНО сообщение на (пользователь, контест) за раз — за ближайший
        # (наименьший) из таких офсетов, а в лог пишем все сработавшие, чтобы
        # не напоминать повторно на каждом тике.
        due_offsets = [
            offset
            for offset in active_offsets.get(reg.user_id, set())
            if (reg.user_id, reg.contest_id, offset) not in logged
            and remaining.total_seconds() <= offset * 60
        ]
        if not due_offsets:
            continue
        # ceil намеренно: округляем вверх, чтобы не напомнить раньше заявленного времени
        minutes = max(1, ceil(remaining.total_seconds() / 60))
        tg_id = tg_by_db_id.get(reg.user_id)
        if tg_id is None:
            continue
        text = (
            f"⏰ Контест «{contest.name}» начнётся через {format_minutes(minutes)}\n"
            f"🕒 Начало: {format_dt_msk(contest.start_time)} (МСК)\n\n"
            f"🔗 https://codeforces.com/contest/{contest.cf_id}"
        )
        delivered = await _send_message(
            bot, tg_id, text, reply_markup=notify_settings_shortcut_kb()
        )
        if not delivered:
            continue
        async with async_session() as session:
            for offset in due_offsets:
                session.add(
                    NotificationLog(user_id=reg.user_id, contest_id=reg.contest_id, offset_minutes=offset)
                )
            await session.commit()


async def cleanup_notification_log() -> None:
    """Удаляет логи напоминаний по контестам, стартовавшим более LOG_RETENTION_DAYS назад."""
    cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=LOG_RETENTION_DAYS)
    async with async_session() as session:
        stale_ids = select(Contest.id).where(
            Contest.start_time.is_not(None), Contest.start_time < cutoff
        )
        await session.execute(delete(NotificationLog).where(NotificationLog.contest_id.in_(stale_ids)))
        await session.commit()


async def _parse_loop(bot: Bot) -> None:
    while True:
        try:
            new_contests = await parse_contests()
            if new_contests:
                await broadcast_new_contests(bot, new_contests)
        except Exception:
            logger.exception("Contest parsing loop failed")
        await asyncio.sleep(PARSE_INTERVAL_SECONDS)


async def _remind_loop(bot: Bot) -> None:
    global _last_log_cleanup
    while True:
        try:
            await send_reminders(bot)
        except Exception:
            logger.exception("Reminder loop failed")
        now_ts = time.monotonic()
        if now_ts - _last_log_cleanup >= _CLEANUP_INTERVAL_SECONDS:
            try:
                await cleanup_notification_log()
                _last_log_cleanup = now_ts
            except Exception:
                logger.exception("Notification log cleanup failed")
        await asyncio.sleep(REMIND_INTERVAL_SECONDS)


def start_scheduler(bot: Bot) -> None:
    loop = asyncio.get_running_loop()
    loop.create_task(_parse_loop(bot))
    loop.create_task(_remind_loop(bot))
