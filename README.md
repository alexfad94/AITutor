# onboard

AI-driven Telegram-бот для обучения сотрудников новому материалу и автоматического тестирования.

Бот работает полностью через LLM:
- объясняет материал простыми сообщениями;
- отвечает на вопросы сотрудника по заданной теме;
- сам решает, когда можно переходить к тесту;
- задает вопросы по одному;
- проверяет ответы по материалу;
- сохраняет результат теста в Postgres.

## Что умеет бот

- попросить имя сотрудника;
- провести обучение по `TRAINING_TOPIC` и `TRAINING_MATERIAL`;
- провести тест из `QUIZ_QUESTION_COUNT` вопросов;
- посчитать количество верных ответов и процент;
- сохранить результат в таблицу `training_results`.

## Как работает

1. Пользователь отправляет `/start`.
2. Бот просит имя сотрудника.
3. После этого AI-наставник начинает обучение по заданному материалу.
4. Когда сотрудник готов, AI переходит к тестированию.
5. После завершения теста бот сохраняет результат в Postgres.

## Структура результата в БД

Таблица `training_results` содержит:
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

```env
BOT_TOKEN=your_telegram_bot_token
DATABASE_URL=postgresql+asyncpg://postgres:postgres@db:5432/onboarding
OPENAI_API_KEY=your_openai_api_key
OPENAI_MODEL=gpt-4.1-mini
OPENAI_BASE_URL=https://api.openai.com/v1
TRAINING_TOPIC=Регламент работы команды
TRAINING_MATERIAL=Команда использует асинхронную коммуникацию по умолчанию. Все задачи фиксируются в трекере. Блокеры нужно эскалировать в течение 30 минут. Перед релизом обязательны code review, зеленые тесты и запись в changelog.
TRAINING_MATERIAL_FILE=./material.txt
QUIZ_QUESTION_COUNT=5
LOG_LEVEL=INFO
```

Если указан `TRAINING_MATERIAL_FILE`, бот читает материал из файла. Иначе использует текст из `TRAINING_MATERIAL`.

## Локальный запуск

```powershell
cd C:\Users\daniil\Desktop\prompt_cases\onboard
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
Copy-Item .env.example .env
python main.py
```

## Запуск через Docker

1. Заполните `.env`
2. Выполните:

```powershell
docker compose up --build
```

## Пример сценария

```text
Пользователь: /start
Бот: Напишите имя сотрудника, которого нужно обучить.
Пользователь: Иван Петров
Бот: Сегодня разберем материал по регламенту команды...
Пользователь: А когда нужно эскалировать блокер?
Бот: В течение 30 минут. Готовы перейти к тесту?
Пользователь: Да
Бот: Вопрос 1. Где должны фиксироваться задачи?
...
Бот: Тест завершен. Результат сохранен в Postgres.
```
