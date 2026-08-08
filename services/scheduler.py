import asyncio
import logging
from datetime import datetime, timezone
from math import ceil

from aiogram import Bot
from sqlalchemy import select

from config import PARSE_INTERVAL_SECONDS, REMIND_INTERVAL_SECONDS
from db.models import (
    Contest,
    NotificationLog,
    NotifySetting,
    Registration,
    User,
    async_session,
)
from keyboards.inline import contest_announce_kb, notify_settings_shortcut_kb
from services.cf_parser import parse_contests
from services.text import format_contest_info

logger = logging.getLogger(__name__)


async def broadcast_new_contests(bot: Bot, contests: list[Contest]) -> None:
    async with async_session() as session:
        tg_ids = list((await session.scalars(select(User.tg_id))).all())
    for contest in contests:
        text = "\n".join(
            ["🔥 Новый контест на Codeforces!", "", format_contest_info(contest)]
        )
        for tg_id in tg_ids:
            try:
                await bot.send_message(tg_id, text, reply_markup=contest_announce_kb(contest.id))
            except Exception:
                logger.exception("Failed to send contest announcement to user %s", tg_id)


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
        tg_by_db_id = dict((await session.execute(select(User.id, User.tg_id))).all())

    for reg, contest in rows:
        if contest.start_time <= now:
            continue
        for offset in active_offsets.get(reg.user_id, set()):
            if (reg.user_id, reg.contest_id, offset) in logged:
                continue
            remaining = contest.start_time - now
            if remaining.total_seconds() > offset * 60:
                continue
            minutes = max(1, ceil(remaining.total_seconds() / 60))
            tg_id = tg_by_db_id.get(reg.user_id)
            if tg_id is None:
                continue
            text = (
                f"⏰ Контест «{contest.name}» начнётся через {minutes} мин\n\n"
                f"🔗 https://codeforces.com/contest/{contest.cf_id}"
            )
            try:
                await bot.send_message(tg_id, text, reply_markup=notify_settings_shortcut_kb())
            except Exception:
                logger.exception("Failed to send reminder to user %s", tg_id)
                continue
            async with async_session() as session:
                session.add(
                    NotificationLog(user_id=reg.user_id, contest_id=reg.contest_id, offset_minutes=offset)
                )
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
    while True:
        try:
            await send_reminders(bot)
        except Exception:
            logger.exception("Reminder loop failed")
        await asyncio.sleep(REMIND_INTERVAL_SECONDS)


def start_scheduler(bot: Bot) -> None:
    loop = asyncio.get_running_loop()
    loop.create_task(_parse_loop(bot))
    loop.create_task(_remind_loop(bot))
