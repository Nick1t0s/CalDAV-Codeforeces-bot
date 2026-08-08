from aiogram import F, Router
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from db.models import get_or_create_user
from handlers.common import safe_edit_text
from keyboards.inline import main_menu_kb, start_new_user_kb

router = Router()

MENU_TEXT = "👋 Привет! Я бот Codeforces Contests.\n\nНастройки уведомлений и календарей доступны в меню:"


@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    _, created = await get_or_create_user(message.from_user.id)
    if created:
        await message.answer(
            "👋 Привет! Я помогу тебе не пропускать контесты на Codeforces.\n\n"
            "Что я умею:\n"
            "• Присылать анонсы новых контестов\n"
            "• Напоминать о старте\n"
            "• Добавлять события в календарь (Яндекс / CalDAV)\n\n"
            "Подключить календарь, чтобы события контестов попадали в него автоматически?",
            reply_markup=start_new_user_kb(),
        )
    else:
        await message.answer(MENU_TEXT, reply_markup=main_menu_kb())


@router.callback_query(F.data == "no_thanks")
async def no_thanks(callback: CallbackQuery) -> None:
    await safe_edit_text(callback.message, MENU_TEXT, reply_markup=main_menu_kb())
    await callback.answer()


@router.callback_query(F.data == "main_menu")
async def back_to_menu(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await safe_edit_text(callback.message, MENU_TEXT, reply_markup=main_menu_kb())
    await callback.answer()
