import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import ErrorEvent

from config import BOT_TOKEN, SECRET_KEY
from db.models import engine, init_db
from handlers import calendar_setup, calendar_settings, contest, notify_settings, start
from handlers.contest import cancel_background_tasks
from services.scheduler import start_scheduler

logger = logging.getLogger(__name__)


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN не задан: export BOT_TOKEN=...")
    if not SECRET_KEY:
        raise RuntimeError(
            "SECRET_KEY не задан: пароли календарей шифруются, ключ обязателен "
            "(см. .env.example, команда для генерации там же)"
        )
    await init_db()

    bot = Bot(BOT_TOKEN)
    dp = Dispatcher(storage=MemoryStorage())
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
        await cancel_background_tasks()
        await dp.storage.close()
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
