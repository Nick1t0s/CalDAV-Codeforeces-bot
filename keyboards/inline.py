from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from db.models import Calendar

NOTIFY_OPTIONS = [
    (5, "5 мин"),
    (10, "10 мин"),
    (15, "15 мин"),
    (30, "30 мин"),
    (60, "1 час"),
    (120, "2 часа"),
    (360, "6 часов"),
    (1440, "1 день"),
    (2880, "2 дня"),
    (10080, "1 неделя"),
]


def start_new_user_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📅 Подключить календарь", callback_data="cal_setup_start")],
            [InlineKeyboardButton(text="Нет, спасибо", callback_data="no_thanks")],
        ]
    )


def main_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔔 Настройка уведомлений", callback_data="notify_settings")],
            [InlineKeyboardButton(text="📅 Настройка календарей", callback_data="cal_settings")],
        ]
    )


def calendar_type_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Яндекс Календарь", callback_data="cal_setup_yandex")],
            [InlineKeyboardButton(text="CalDAV", callback_data="cal_setup_caldav")],
            [InlineKeyboardButton(text="← Назад", callback_data="cal_settings")],
        ]
    )


def calendar_settings_kb(calendars: list[Calendar]) -> InlineKeyboardMarkup:
    buttons = []
    for cal in calendars:
        buttons.append(
            [
                InlineKeyboardButton(text="Вкл/Выкл", callback_data=f"cal_toggle:{cal.id}"),
                InlineKeyboardButton(text="Удалить", callback_data=f"cal_delete:{cal.id}"),
            ]
        )
    buttons.append([InlineKeyboardButton(text="＋ Добавить", callback_data="cal_add")])
    buttons.append([InlineKeyboardButton(text="← Назад", callback_data="main_menu")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def notify_settings_kb(active: set[int] | None = None) -> InlineKeyboardMarkup:
    active = active or set()
    buttons = []
    for offset, label in NOTIFY_OPTIONS:
        mark = "✅" if offset in active else "☑️"
        buttons.append([InlineKeyboardButton(text=f"{mark} {label}", callback_data=f"notif_toggle:{offset}")])
    buttons.append([InlineKeyboardButton(text="← Назад", callback_data="main_menu")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def notify_settings_shortcut_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="⚙️ Настроить уведомления", callback_data="notify_settings")]]
    )


def guide_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="❓ Гайд по подключению", callback_data="cal_guide")]]
    )


def retry_cancel_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Попробовать снова", callback_data="cal_retry")],
            [InlineKeyboardButton(text="Отмена", callback_data="cal_cancel")],
        ]
    )


def http_confirm_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Всё равно продолжить", callback_data="cal_http_confirm")],
            [InlineKeyboardButton(text="✏️ Изменить адрес", callback_data="cal_http_edit")],
            [InlineKeyboardButton(text="Отмена", callback_data="cal_cancel")],
        ]
    )


def contest_announce_kb(contest_db_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="🔥 Буду участвовать", callback_data=f"reg:{contest_db_id}")]]
    )


def warning_kb(calendar_id: int, contest_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="➕ Добавить", callback_data=f"warn_add:{calendar_id}:{contest_id}")],
            [InlineKeyboardButton(text="Пропустить", callback_data=f"warn_skip:{calendar_id}:{contest_id}")],
        ]
    )


def to_calendar_settings_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="📅 Настроить календари", callback_data="cal_settings")]]
    )
