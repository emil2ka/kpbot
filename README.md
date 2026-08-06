# Kaspi Sourcing AI

AI-основа для Telegram-бота, который помогает проверить товар на Kaspi, показать его фото, оценить конкуренцию, рассчитать прибыль и сравнить варианты карго. Это первый рабочий этап продукта «Kaspi → Китай → Казахстан».

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

Открой `http://127.0.0.1:8000/docs`. Если задан `APP_API_KEY`, передай его в заголовке `X-API-Key`.

### Проверить карточку Kaspi

```json
{
  "url": "https://kaspi.kz/shop/p/example/",
  "analyze_with_ai": false
}
```

### Посчитать экономику

`POST /api/v1/economics/calculate`:

```json
{
  "sale_price_kzt": 8990,
  "unit_price_cny": 18,
  "quantity": 50,
  "cargo_cost_kzt": 60000
}
```

Ответ включает полную себестоимость, прибыль на единицу, маржу, ROI и рекомендуемую максимальную цену закупки.

### Сравнить карго

`POST /api/v1/cargo/compare`:

```json
{
  "actual_weight_kg": 12,
  "length_cm": 40,
  "width_cm": 30,
  "height_cm": 25,
  "quantity": 50,
  "urgency": "normal",
  "cargo_type": "standard"
}
```

Сервис сравнит демонстрационные тарифы авиа, авто и эконом-доставки. Тарифы намеренно находятся в коде как временные: перед реальными закупками их нужно заменить условиями конкретных карго-партнёров.

## Telegram-бот

1. Создай бота через `@BotFather` и задай `TELEGRAM_BOT_TOKEN` в `.env`.
2. Создай длинную случайную строку для `TELEGRAM_WEBHOOK_SECRET`.
3. После развёртывания укажи Telegram webhook:

```bash
curl "https://api.telegram.org/bot$TELEGRAM_BOT_TOKEN/setWebhook" \
  -d "url=https://YOUR_DOMAIN/api/v1/telegram/webhook" \
  -d "secret_token=$TELEGRAM_WEBHOOK_SECRET"
```

Пользователь может отправить `/start`, затем ссылку на Kaspi. Бот покажет карточку с фото, ценой, оценкой потенциала и следующим действием. В меню уже есть точки входа для поиска идей, Китая, карго и прибыли.

## Подключение сервисов

1. **Supabase**: создай проект → SQL Editor → выполни `supabase/migrations/001_kaspi_scans.sql`. В Project Settings → API скопируй `SUPABASE_URL` и **service_role** key в `.env` локально или в Secrets Render. Никогда не используй service_role key в браузере.
2. **xAI**: отзови ключ, который был опубликован в чате, создай новый и укажи его только как `XAI_API_KEY`. Модель — `grok-4.3`.
3. **Render**: загрузи проект в приватный GitHub-репозиторий → New → Blueprint → выбери репозиторий. `render.yaml` создаст web service; секреты введи в панели Render, включая Telegram-переменные.

### Поиск поставщиков

Поиск сначала пытается получить публичную выдачу 1688. Если страница не отдаёт структурированные карточки, сервис использует публичную выдачу Made-in-China как запасной источник и явно помечает цену в USD. Защиту сайтов, CAPTCHA и авторизацию сервис не обходит. Для стабильных цен и MOQ с 1688 подключи лицензированный провайдер через `CHINA_PROVIDER_API_KEY` и `CHINA_PROVIDER_BASE_URL`.

`/health` показывает только статус подключения сервисов без раскрытия секретов. Render Blueprints берёт конфигурацию из `render.yaml`, а web service должен слушать `$PORT`; проект уже настроен под это. См. [документацию Render](https://render.com/docs/blueprint-spec).

## Следующая итерация

Хранение идей и поставщиков в Supabase, реальные тарифы и API карго-партнёров, разрешённый источник данных 1688/Alibaba, фоновый мониторинг карточек Kaspi и ежедневные AI-подборки.
