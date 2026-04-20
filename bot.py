import asyncio
import json
import os
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message, CallbackQuery
from dotenv import load_dotenv

from schedule_service import ScheduleService, DaySchedule

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
SCHEDULE_URL_TEMPLATE = os.getenv("SCHEDULE_URL_TEMPLATE", "")
TZ = ZoneInfo(os.getenv("TZ", "Europe/Moscow"))

USER_STATE_PATH = Path("user_state.json")


@dataclass
class UserState:
    group: str


def load_states() -> dict[str, UserState]:
    if not USER_STATE_PATH.exists():
        return {}
    raw = json.loads(USER_STATE_PATH.read_text(encoding="utf-8"))
    return {uid: UserState(**payload) for uid, payload in raw.items()}


def save_states(states: dict[str, UserState]) -> None:
    raw = {uid: {"group": state.group} for uid, state in states.items()}
    USER_STATE_PATH.write_text(
        json.dumps(raw, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def nav_keyboard(offset: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="◀️", callback_data=f"day:{offset-1}"),
                InlineKeyboardButton(text="🏠 Сегодня", callback_data="day:0"),
                InlineKeyboardButton(text="▶️", callback_data=f"day:{offset+1}"),
            ],
            [InlineKeyboardButton(text="По дням", callback_data="days:list")],
        ]
    )


def weekdays_keyboard(offset: int) -> InlineKeyboardMarkup:
    labels = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
    row = [
        InlineKeyboardButton(text=label, callback_data=f"weekday:{idx}")
        for idx, label in enumerate(labels)
    ]
    return InlineKeyboardMarkup(
        inline_keyboard=[row, [InlineKeyboardButton(text="⬅️ Назад", callback_data=f"day:{offset}")]]
    )


def format_day(group: str, day: DaySchedule) -> str:
    lines = [f"<b>{group}</b>", "", f"<b>{day.title}</b>"]
    if not day.lessons:
        lines.append("Выходной")
        return "\n".join(lines)

    for lesson in day.lessons:
        lines.extend(
            [
                "",
                f"<b>{lesson.subject}</b>",
                lesson.teacher,
                f"{lesson.time}   {lesson.kind}   {lesson.room}",
            ]
        )
    return "\n".join(lines)


async def send_day(message: Message, service: ScheduleService, group: str, offset: int) -> None:
    target_date = datetime.now(TZ).date() + timedelta(days=offset)
    day_schedule = await service.get_day(group, target_date)
    await message.answer(
        format_day(group, day_schedule),
        parse_mode="HTML",
        reply_markup=nav_keyboard(offset),
    )


async def main() -> None:
    if not BOT_TOKEN:
        raise RuntimeError("Не задан BOT_TOKEN")
    if not SCHEDULE_URL_TEMPLATE:
        raise RuntimeError("Не задан SCHEDULE_URL_TEMPLATE")

    bot = Bot(BOT_TOKEN)
    dp = Dispatcher()
    service = ScheduleService(SCHEDULE_URL_TEMPLATE, TZ)
    states = load_states()

    @dp.message(CommandStart())
    async def on_start(message: Message) -> None:
        await message.answer(
            "Привет! Отправь код группы (например, М80-118БВ-25), и я покажу расписание."
        )

    @dp.message(Command("group"))
    async def on_group_help(message: Message) -> None:
        await message.answer("Отправь новым сообщением код группы, чтобы сменить её.")

    @dp.message(F.text)
    async def on_text(message: Message) -> None:
        uid = str(message.from_user.id)
        text = (message.text or "").strip()

        if text.startswith("/"):
            return

        states[uid] = UserState(group=text)
        save_states(states)
        await send_day(message, service, text, 0)

    @dp.callback_query(F.data.startswith("day:"))
    async def on_day_nav(cb: CallbackQuery) -> None:
        uid = str(cb.from_user.id)
        state = states.get(uid)
        if not state:
            await cb.message.answer("Сначала отправь код группы.")
            await cb.answer()
            return

        offset = int(cb.data.split(":", 1)[1])
        target_date = datetime.now(TZ).date() + timedelta(days=offset)
        day_schedule = await service.get_day(state.group, target_date)
        await cb.message.edit_text(
            format_day(state.group, day_schedule),
            parse_mode="HTML",
            reply_markup=nav_keyboard(offset),
        )
        await cb.answer()

    @dp.callback_query(F.data == "days:list")
    async def on_days_list(cb: CallbackQuery) -> None:
        await cb.message.edit_reply_markup(reply_markup=weekdays_keyboard(0))
        await cb.answer()

    @dp.callback_query(F.data.startswith("weekday:"))
    async def on_weekday(cb: CallbackQuery) -> None:
        uid = str(cb.from_user.id)
        state = states.get(uid)
        if not state:
            await cb.answer("Сначала отправь код группы", show_alert=True)
            return

        weekday = int(cb.data.split(":", 1)[1])
        today = datetime.now(TZ).date()
        delta = (weekday - today.weekday()) % 7
        target_date = today + timedelta(days=delta)
        day_schedule = await service.get_day(state.group, target_date)
        await cb.message.edit_text(
            format_day(state.group, day_schedule),
            parse_mode="HTML",
            reply_markup=nav_keyboard(delta),
        )
        await cb.answer()

    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
