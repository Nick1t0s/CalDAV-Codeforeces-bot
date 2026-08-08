import logging

from aiogram.exceptions import TelegramBadRequest
from aiogram.types import Message

logger = logging.getLogger(__name__)

MAX_MESSAGE_LENGTH = 4096

_NOT_MODIFIED_HINTS = ("message is not modified", "nothing to edit")


def _truncate(text: str) -> str:
    if len(text) <= MAX_MESSAGE_LENGTH:
        return text
    return text[: MAX_MESSAGE_LENGTH - 3] + "..."


async def safe_edit_text(message: Message, text: str, **kwargs) -> None:
    text = _truncate(text)
    try:
        await message.edit_text(text, **kwargs)
    except TelegramBadRequest as exc:
        lowered = str(exc.message).lower()
        if any(hint in lowered for hint in _NOT_MODIFIED_HINTS):
            return
        logger.warning("Failed to edit message: %s", exc, exc_info=True)
        try:
            await message.answer(text, **kwargs)
        except Exception:
            logger.exception("Failed to fallback-answer edited message")
