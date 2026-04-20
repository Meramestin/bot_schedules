import re
from dataclasses import dataclass
from datetime import date, datetime
from urllib.parse import quote
from zoneinfo import ZoneInfo

import aiohttp
from bs4 import BeautifulSoup, Tag


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
    parse_error: bool = False


class ScheduleService:
    """
    Парсер расписания с несколькими стратегиями:
    1) структурные CSS-селекторы;
    2) fallback по текстовым заголовкам дней и времени пар.

    Это нужно, потому что разные страницы вузов (и даже один и тот же вуз)
    могут отдавать разную HTML-структуру.
    """

    DAY_NAMES = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]

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

        structured = self._parse_structured_day(soup, target_date)
        if structured is not None:
            return structured

        text_fallback = self._parse_text_day(soup, target_date)
        if text_fallback is not None:
            return text_fallback

        title = self._default_title(target_date)
        return DaySchedule(
            title=title,
            lessons=[],
            parse_error=True,
        )

    def _parse_structured_day(self, soup: BeautifulSoup, target_date: date) -> DaySchedule | None:
        target_iso = target_date.isoformat()
        day_node = soup.select_one(f'.schedule-day[data-date="{target_iso}"]')

        if day_node is None:
            for selector in [
                f'[data-date="{target_iso}"]',
                f'[data-day-date="{target_iso}"]',
                f'[datetime^="{target_iso}"]',
            ]:
                node = soup.select_one(selector)
                if node is not None:
                    day_node = node
                    break

        if day_node is None:
            return None

        title_node = day_node.select_one("h1, h2, h3, .day-title, .schedule-day-title")
        title = title_node.get_text(strip=True) if title_node else self._default_title(target_date)

        lesson_nodes = day_node.select(".lesson, .pair, .schedule-item, tr")
        lessons: list[Lesson] = []
        for lesson_node in lesson_nodes:
            lesson = self._extract_lesson(lesson_node)
            if lesson:
                lessons.append(lesson)

        lessons.sort(key=lambda x: _safe_time(x.time))
        return DaySchedule(title=title, lessons=lessons)

    def _parse_text_day(self, soup: BeautifulSoup, target_date: date) -> DaySchedule | None:
        lines = [line.strip() for line in soup.get_text("\n").splitlines() if line.strip()]
        if not lines:
            return None

        day_prefix = self.DAY_NAMES[target_date.weekday()]
        day_pattern = re.compile(rf"^({day_prefix}|{self._weekday_full_ru(target_date.weekday())})\b", re.IGNORECASE)
        time_pattern = re.compile(r"\b\d{1,2}:\d{2}\s*[-–]\s*\d{1,2}:\d{2}\b")

        start = None
        for i, line in enumerate(lines):
            if day_pattern.search(line):
                start = i
                break

        if start is None:
            return None

        end = len(lines)
        other_days = [d for d in self.DAY_NAMES if d != day_prefix]
        next_day_pattern = re.compile(rf"^({'|'.join(other_days)}|Понедельник|Вторник|Среда|Четверг|Пятница|Суббота|Воскресенье)\b", re.IGNORECASE)
        for i in range(start + 1, len(lines)):
            if next_day_pattern.search(lines[i]):
                end = i
                break

        chunk = lines[start:end]
        title = chunk[0]
        lessons: list[Lesson] = []

        i = 1
        while i < len(chunk):
            line = chunk[i]
            if not time_pattern.search(line):
                i += 1
                continue

            time = _extract_time(line)
            subject = chunk[i + 1] if i + 1 < len(chunk) else "—"
            teacher = chunk[i + 2] if i + 2 < len(chunk) else "—"
            details = chunk[i + 3] if i + 3 < len(chunk) else "—"

            kind, room = _split_kind_room(details)
            lessons.append(Lesson(subject=subject, teacher=teacher, time=time, kind=kind, room=room))
            i += 4

        lessons.sort(key=lambda x: _safe_time(x.time))
        return DaySchedule(title=title, lessons=lessons)

    def _extract_lesson(self, node: Tag) -> Lesson | None:
        subject = text_or_dash(node.select_one(".subject, .discipline, .name, td:nth-child(2)"))
        teacher = text_or_dash(node.select_one(".teacher, .lecturer, .prep, td:nth-child(3)"))
        time = text_or_dash(node.select_one(".time, .hours, .pair-time, td:nth-child(1)"))
        kind = text_or_dash(node.select_one(".kind, .type, .lesson-type, td:nth-child(4)"))
        room = text_or_dash(node.select_one(".room, .auditory, .cabinet, td:nth-child(5)"))

        if subject == "—" and teacher == "—" and not re.search(r"\d{1,2}:\d{2}", time):
            return None

        if not re.search(r"\d{1,2}:\d{2}", time):
            time = _extract_time(node.get_text(" ", strip=True))

        return Lesson(subject=subject, teacher=teacher, time=time, kind=kind, room=room)

    def _default_title(self, target_date: date) -> str:
        return target_date.strftime("%a • %d.%m")

    @staticmethod
    def _weekday_full_ru(idx: int) -> str:
        names = [
            "Понедельник",
            "Вторник",
            "Среда",
            "Четверг",
            "Пятница",
            "Суббота",
            "Воскресенье",
        ]
        return names[idx]


def text_or_dash(node: Tag | None) -> str:
    if node is None:
        return "—"
    return node.get_text(" ", strip=True) or "—"


def _extract_time(value: str) -> str:
    m = re.search(r"(\d{1,2}:\d{2}\s*[-–]\s*\d{1,2}:\d{2})", value)
    return m.group(1).replace("–", "-") if m else "—"


def _split_kind_room(details: str) -> tuple[str, str]:
    details = details.strip()
    if not details or details == "—":
        return "—", "—"
    parts = details.split()
    if len(parts) == 1:
        return parts[0], "—"
    return parts[0], " ".join(parts[1:])


def _safe_time(value: str) -> datetime:
    try:
        start = value.split("-", 1)[0].strip()
        return datetime.strptime(start, "%H:%M")
    except Exception:
        return datetime.max
