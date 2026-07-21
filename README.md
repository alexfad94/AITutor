# AITutor

Telegram-бот для обучения сотрудников и автоматического тестирования через LLM.

По умолчанию тема — **Основы кибербезопасности** (пароли, MFA, фишинг, данные, VPN, реакция на инциденты). Тему и материал можно сменить через переменные окружения.

Бот работает через LLM:
- объясняет материал простыми сообщениями;
- отвечает на вопросы сотрудника только по заданному материалу;
- сам решает, когда переходить к тесту;
- задаёт вопросы по одному (мини-кейсы);
- проверяет ответы и даёт обратную связь по каждому;
- сохраняет итог теста в PostgreSQL.

## Что умеет бот

- запросить имя сотрудника;
- провести обучение по `TRAINING_TOPIC` и `TRAINING_MATERIAL`;
- провести тест из `QUIZ_QUESTION_COUNT` вопросов;
- посчитать число верных ответов и процент;
- сохранить результат в таблицу `training_results`.

## Как работает

1. Пользователь отправляет `/start`.
2. Бот просит имя сотрудника.
3. AI-наставник проводит обучение по материалу.
4. Когда сотрудник готов, бот переходит к тестированию.
5. После всех вопросов бот комментирует последний ответ, даёт итог и сохраняет результат в БД.

Команды:
- `/start` — начать сессию;
- `/cancel` — отменить текущую сессию.

## Структура результата в БД

Таблица `training_results`:
- `employee_name`
- `telegram_user_id`
- `telegram_chat_id`
- `topic`
- `total_questions`
- `correct_answers`
- `score_percent`
- `final_summary`
- `created_at`

## Переменные окружения

Скопируйте `.env.example` в `.env` и заполните значения:

```env
BOT_TOKEN=your_telegram_bot_token
DATABASE_URL=postgresql+asyncpg://postgres:postgres@db:5432/onboarding
OPENAI_API_KEY=your_openai_api_key
OPENAI_MODEL=gpt-5.4-mini-2026-03-17
OPENAI_BASE_URL=https://api.openai.com/v1
TRAINING_TOPIC=Основы кибербезопасности
TRAINING_MATERIAL=Пароли должны быть длинными (от 12 символов), уникальными для каждого сервиса и храниться в менеджере паролей; ...
QUIZ_QUESTION_COUNT=5
LOG_LEVEL=INFO
```

Опционально: `TRAINING_MATERIAL_FILE=./material.txt` — если указан, материал читается из файла вместо `TRAINING_MATERIAL`.

## Локальный запуск

Нужен доступный PostgreSQL (локально или через Docker-сервис `db`).

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
Copy-Item .env.example .env
# заполните BOT_TOKEN, OPENAI_API_KEY и DATABASE_URL в .env
python main.py
```

## Запуск через Docker

1. Заполните `.env` (как минимум `BOT_TOKEN` и `OPENAI_API_KEY`).
2. Запустите:

```powershell
docker compose up --build
```

Сервисы:
- `db` — PostgreSQL 16;
- `bot` — приложение (стартует после healthcheck БД).

## Пример сценария

```text
Пользователь: /start
Бот: Напишите имя сотрудника, которого нужно обучить.
Пользователь: Иван Петров
Бот: Разберём основы кибербезопасности: пароли, MFA, фишинг...
Пользователь: готов к тесту
Бот: Вопрос 1/5: ...
...
Бот: Неверно: на публичном Wi‑Fi нужен VPN.
     Тест завершён. ...
     Результат сохранен в БД.
     Итог: 4/5 (80%).
```

## Структура проекта

```text
main.py                 # точка входа
bot/                    # aiogram: handlers, keyboards, middlewares
config/                 # настройки из .env
database/               # модели, репозиторий, async SQLAlchemy
services/               # TrainingService, AITrainingService, промпты
schemas/                # pydantic-схемы сессии и результатов
docker-compose.yml      # bot + postgres
```
