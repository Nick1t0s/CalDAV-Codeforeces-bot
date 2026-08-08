import asyncio
import logging

from aiogram import Bot, Dispatcher

from config import BOT_TOKEN
from db.models import init_db
from handlers import calendar_setup, calendar_settings, contest, notify_settings, start
from services.scheduler import start_scheduler


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN не задан: export BOT_TOKEN=...")
    await init_db()

    bot = Bot(BOT_TOKEN)
    dp = Dispatcher()
    dp.include_router(start.router)
    dp.include_router(calendar_setup.router)
    dp.include_router(calendar_settings.router)
    dp.include_router(notify_settings.router)
    dp.include_router(contest.router)

    start_scheduler(bot)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
