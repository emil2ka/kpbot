# Kaspi research MVP

Backend для исследования карточек Kaspi: получает публичную страницу товара, извлекает доступные данные, применяет фильтры и сохраняет историю в Supabase. По желанию Grok 4.3 выдаёт структурированную оценку импортных рисков.

## Важно

Используй только ссылки на публичные страницы и соблюдай условия Kaspi. Сервис не логинится, не обходит защиту и не выполняет массовые запросы. Для запуска сканирования категории потребуется отдельная согласованная стратегия источника данных.

## Локальный запуск

```bash
cp .env.example .env
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Для этого проекта используй Python 3.13 (он указан в `.python-version`).

Открой `http://127.0.0.1:8000/docs` и вызови `POST /api/v1/kaspi/scan`:

```json
{
  "url": "https://kaspi.kz/shop/p/example/",
  "analyze_with_ai": false
}
```

## Подключение сервисов

1. **Supabase**: создай проект → SQL Editor → выполни `supabase/migrations/001_kaspi_scans.sql`. В Project Settings → API скопируй `SUPABASE_URL` и **service_role** key в `.env` локально или в Secrets Render. Никогда не используй service_role key в браузере.
2. **xAI**: отзови ключ, который был опубликован в чате, создай новый и укажи его только как `XAI_API_KEY`. Модель — `grok-4.3`.
3. **Render**: загрузи проект в приватный GitHub-репозиторий → New → Blueprint → выбери репозиторий. `render.yaml` создаст web service; секреты введи в панели Render.

Render Blueprints берёт конфигурацию из `render.yaml`, а web service должен слушать `$PORT`; проект уже настроен под это. См. [документацию Render](https://render.com/docs/blueprint-spec).

## Следующая итерация

Добавить планировщик задач, белый список категорий и Telegram-уведомления после того, как подтвердим извлечение данных на реальных страницах Kaspi.
