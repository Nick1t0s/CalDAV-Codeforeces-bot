import logging
from datetime import datetime, timezone

import aiohttp
from sqlalchemy import select

from db.models import Contest, async_session

logger = logging.getLogger(__name__)

CF_CONTESTS_URL = "https://codeforces.com/api/contest.list"


async def parse_contests() -> list[Contest]:
    async with aiohttp.ClientSession() as session:
        async with session.get(CF_CONTESTS_URL, timeout=aiohttp.ClientTimeout(total=30)) as response:
            payload = await response.json()
    if payload.get("status") != "OK":
        raise RuntimeError(f"Codeforces API error: {payload.get('comment')}")

    new_before: list[Contest] = []
    async with async_session() as session:
        existing = {c.cf_id: c for c in (await session.scalars(select(Contest))).all()}
        for item in payload.get("result", []):
            if not isinstance(item, dict):
                continue
            cf_id = item.get("id")
            try:
                cf_id = int(cf_id)
            except (TypeError, ValueError):
                continue
            phase = item.get("phase", "") or ""
            start_ts = item.get("startTimeSeconds")
            start = (
                datetime.fromtimestamp(int(start_ts), tz=timezone.utc).replace(tzinfo=None)
                if start_ts
                else None
            )
            try:
                duration = int(item.get("durationSeconds", 0) or 0)
            except (TypeError, ValueError):
                duration = 0
            contest = existing.get(cf_id)
            if contest is None:
                contest = Contest(
                    cf_id=cf_id,
                    name=str(item.get("name", "") or ""),
                    type=str(item.get("type", "") or ""),
                    phase=phase,
                    start_time=start,
                    duration_seconds=duration,
                )
                session.add(contest)
                existing[cf_id] = contest
            else:
                contest.name = str(item.get("name", "") or "")
                contest.type = str(item.get("type", "") or "")
                contest.phase = phase
                contest.start_time = start
                contest.duration_seconds = duration
            if phase == "BEFORE" and not contest.announced:
                contest.announced = True
                new_before.append(contest)
        await session.commit()
    return new_before
