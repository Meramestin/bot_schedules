import asyncio
import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message, CallbackQuery
from dotenv import load_dotenv

from schedule_service import ScheduleService, DaySchedule

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
SCHEDULE_URL_TEMPLATE = os.getenv("SCHEDULE_URL_TEMPLATE", "")
FIXED_GROUP = os.getenv("FIXED_GROUP", "")
TZ = ZoneInfo(os.getenv("TZ", "Europe/Moscow"))

WEEKDAY_SHORT = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]


def week_keyboard(week_offset: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="◀️ Пред. неделя", callback_data=f"week:{week_offset-1}"),
                InlineKeyboardButton(text="🏠 Эта неделя", callback_data="week:0"),
                InlineKeyboardButton(text="След. неделя ▶️", callback_data=f"week:{week_offset+1}"),
            ]
        ]
    )


def format_week(group: str, week_start, days: list[DaySchedule]) -> str:
    week_end = week_start + timedelta(days=6)
    lines = [
        f"<b>{group}</b>",
        f"<b>Неделя {week_start.strftime('%d.%m')} — {week_end.strftime('%d.%m')}</b>",
        "",
    ]

    if all(day.parse_error for day in days):
        lines.append("Не удалось распознать формат расписания на сайте вуза.")
        lines.append("Проверьте ссылку/группу и HTML-структуру страницы.")
        return "\n".join(lines)

    for idx, day in enumerate(days):
        day_date = week_start + timedelta(days=idx)
        lines.append(f"<b>{WEEKDAY_SHORT[idx]} • {day_date.strftime('%d.%m')}</b>")

        if day.parse_error:
            lines.append("Ошибка парсинга для этого дня")
            lines.append("")
            continue

        if not day.lessons:
            lines.append("Выходной")
            lines.append("")
            continue

        for lesson in day.lessons:
            lines.append(f"• <b>{lesson.subject}</b>")
            lines.append(f"  {lesson.time} | {lesson.kind} | {lesson.room}")
            lines.append(f"  {lesson.teacher}")
        lines.append("")

    return "\n".join(lines)


def monday_for_offset(offset_weeks: int):
    today = datetime.now(TZ).date()
    return today - timedelta(days=today.weekday()) + timedelta(weeks=offset_weeks)


async def send_week(target_message: Message, service: ScheduleService, group: str, week_offset: int) -> None:
    week_start = monday_for_offset(week_offset)
    days = await service.get_week(group, week_start)
    await target_message.answer(
        format_week(group, week_start, days),
        parse_mode="HTML",
        reply_markup=week_keyboard(week_offset),
    )


async def main() -> None:
    if not BOT_TOKEN:
        raise RuntimeError("Не задан BOT_TOKEN")
    if not SCHEDULE_URL_TEMPLATE:
        raise RuntimeError("Не задан SCHEDULE_URL_TEMPLATE")
    if not FIXED_GROUP:
        raise RuntimeError("Не задан FIXED_GROUP")

    bot = Bot(BOT_TOKEN)
    dp = Dispatcher()
    service = ScheduleService(SCHEDULE_URL_TEMPLATE, TZ)

    @dp.message(CommandStart())
    async def on_start(message: Message) -> None:
        await message.answer(
            f"Привет! Показываю расписание для группы {FIXED_GROUP}.",
        )
        await send_week(message, service, FIXED_GROUP, 0)

    @dp.message(Command("week"))
    async def on_week_cmd(message: Message) -> None:
        await send_week(message, service, FIXED_GROUP, 0)

    @dp.message(F.text)
    async def on_text(message: Message) -> None:
        await message.answer(
            f"Бот закреплён за группой {FIXED_GROUP}. Используй /week для расписания недели."
        )

    @dp.callback_query(F.data.startswith("week:"))
    async def on_week_nav(cb: CallbackQuery) -> None:
        week_offset = int(cb.data.split(":", 1)[1])
        week_start = monday_for_offset(week_offset)
        days = await service.get_week(FIXED_GROUP, week_start)
        await cb.message.edit_text(
            format_week(FIXED_GROUP, week_start, days),
            parse_mode="HTML",
            reply_markup=week_keyboard(week_offset),
        )
        await cb.answer()

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
