# Telegram бот расписания вуза

Бот получает код группы, скачивает страницу расписания с сайта вуза и показывает занятия в стиле как на скриншоте: один день, стрелки навигации, кнопка «По дням».

## 1) Установка

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 2) Настройка

```bash
cp .env.example .env
```

Заполните:
- `BOT_TOKEN` — токен от BotFather.
- `SCHEDULE_URL_TEMPLATE` — ссылка на страницу расписания, где `{group}` заменяется на код группы.
  - Пример: `https://myuniversity.edu/timetable/{group}`
- `TZ` — часовой пояс (по умолчанию `Europe/Moscow`).

## 3) Запуск

```bash
python bot.py
```

## Важно про парсинг

Парсер реализован в `schedule_service.py` и по умолчанию ожидает HTML-узлы:
- `.schedule-day[data-date="YYYY-MM-DD"]`
- внутри `.lesson` с полями `.subject`, `.teacher`, `.time`, `.kind`, `.room`

Если на сайте вуза другая структура, поменяйте селекторы в `parse_day`.
