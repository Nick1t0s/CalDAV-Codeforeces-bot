import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.types import ErrorEvent

from config import BOT_TOKEN, SECRET_KEY
from db.fsm_storage import SQLiteStorage
from db.models import engine, init_db
from handlers import calendar_setup, calendar_settings, contest, notify_settings, start
from services.scheduler import start_scheduler

logger = logging.getLogger(__name__)


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN не задан: export BOT_TOKEN=...")
    if not SECRET_KEY:
        logger.warning(
            "SECRET_KEY не задан: пароли календарей будут храниться открытым текстом "
            "(см. .env.example)"
        )
    await init_db()

    bot = Bot(BOT_TOKEN)
    dp = Dispatcher(storage=SQLiteStorage())
    dp.include_router(start.router)
    dp.include_router(calendar_setup.router)
    dp.include_router(calendar_settings.router)
    dp.include_router(notify_settings.router)
    dp.include_router(contest.router)

    @dp.errors()
    async def on_update_error(event: ErrorEvent) -> None:
        logger.exception("Update processing error: %s", event.exception)

    start_scheduler(bot)
    try:
        await dp.start_polling(bot, drop_pending_updates=True)
    finally:
        await dp.storage.close()
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
