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
            cf_id = int(item["id"])
            phase = item.get("phase", "")
            start_ts = item.get("startTimeSeconds")
            start = datetime.fromtimestamp(start_ts, tz=timezone.utc).replace(tzinfo=None) if start_ts else None
            contest = existing.get(cf_id)
            if contest is None:
                contest = Contest(
                    cf_id=cf_id,
                    name=item.get("name", ""),
                    type=item.get("type", ""),
                    phase=phase,
                    start_time=start,
                    duration_seconds=int(item.get("durationSeconds", 0)),
                )
                session.add(contest)
                existing[cf_id] = contest
            else:
                contest.name = item.get("name", "")
                contest.type = item.get("type", "")
                contest.phase = phase
                contest.start_time = start
                contest.duration_seconds = int(item.get("durationSeconds", 0))
            if phase == "BEFORE" and not contest.announced:
                contest.announced = True
                new_before.append(contest)
        await session.commit()
    return new_before
