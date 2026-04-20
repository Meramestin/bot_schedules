from dataclasses import dataclass
from datetime import date, datetime
from zoneinfo import ZoneInfo
from urllib.parse import quote

import aiohttp
from bs4 import BeautifulSoup


@dataclass
class Lesson:
    subject: str
    teacher: str
    time: str
    kind: str
    room: str


@dataclass
class DaySchedule:
    title: str
    lessons: list[Lesson]


class ScheduleService:
    """
    Универсальный парсер расписания.

    Ожидаемая HTML-структура на странице:
    <div class="schedule-day" data-date="YYYY-MM-DD">
      <h3>Пн • 16.03</h3>
      <div class="lesson">
        <span class="subject">...</span>
        <span class="teacher">...</span>
        <span class="time">09:00-10:30</span>
        <span class="kind">ЛК</span>
        <span class="room">ГУК Б-214</span>
      </div>
    </div>

    Подстройте селекторы под сайт вашего вуза в parse_day.
    """

    def __init__(self, url_template: str, tz: ZoneInfo) -> None:
        self.url_template = url_template
        self.tz = tz

    async def get_day(self, group: str, target_date: date) -> DaySchedule:
        encoded_group = quote(group, safe="")
        url = self.url_template.format(group=encoded_group)
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=20) as resp:
                resp.raise_for_status()
                html = await resp.text()
        return self.parse_day(html, target_date)

    def parse_day(self, html: str, target_date: date) -> DaySchedule:
        soup = BeautifulSoup(html, "html.parser")
        day_node = soup.select_one(f'.schedule-day[data-date="{target_date.isoformat()}"]')
        if not day_node:
            title = target_date.strftime("%a • %d.%m")
            return DaySchedule(title=title, lessons=[])

        title_node = day_node.select_one("h3")
        title = title_node.get_text(strip=True) if title_node else target_date.strftime("%a • %d.%m")

        lessons: list[Lesson] = []
        for lesson_node in day_node.select(".lesson"):
            lessons.append(
                Lesson(
                    subject=text_or_dash(lesson_node.select_one(".subject")),
                    teacher=text_or_dash(lesson_node.select_one(".teacher")),
                    time=text_or_dash(lesson_node.select_one(".time")),
                    kind=text_or_dash(lesson_node.select_one(".kind")),
                    room=text_or_dash(lesson_node.select_one(".room")),
                )
            )

        lessons.sort(key=lambda x: _safe_time(x.time))
        return DaySchedule(title=title, lessons=lessons)


def text_or_dash(node) -> str:
    if node is None:
        return "—"
    return node.get_text(" ", strip=True) or "—"


def _safe_time(value: str) -> datetime:
    try:
        start = value.split("-", 1)[0]
        return datetime.strptime(start, "%H:%M")
    except Exception:
        return datetime.max
