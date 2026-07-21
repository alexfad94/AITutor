import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.storage.memory import MemoryStorage

from bot.handlers import router
from bot.middlewares import LoggingMiddleware
from config import get_settings
from database import create_engine, create_session_factory, init_db
from services import AITrainingService, TrainingService

logger = logging.getLogger(__name__)


def setup_logging(level: str) -> None:
    import logging.config

    logging.config.dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {
                "standard": {
                    "format": "%(asctime)s | %(levelname)s | %(name)s | %(message)s",
                }
            },
            "handlers": {
                "console": {
                    "class": "logging.StreamHandler",
                    "formatter": "standard",
                    "level": level.upper(),
                }
            },
            "root": {
                "handlers": ["console"],
                "level": level.upper(),
            },
        }
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("aiogram").setLevel(logging.INFO)


async def run_bot() -> None:
    settings = get_settings()
    setup_logging(settings.log_level)

    storage = MemoryStorage()
    bot = Bot(token=settings.bot_token, default=DefaultBotProperties())
    dp = Dispatcher(storage=storage)

    engine = create_engine(settings.database_url)
    session_factory = create_session_factory(engine)
    training_service = TrainingService()
    ai_training_service = AITrainingService(settings)

    await init_db(engine)

    dp.message.middleware(LoggingMiddleware())
    dp.include_router(router)
    dp["settings"] = settings
    dp["session_factory"] = session_factory
    dp["training_service"] = training_service
    dp["ai_training_service"] = ai_training_service

    logger.info("Starting AI training bot")
    try:
        await dp.start_polling(bot)
    finally:
        await ai_training_service.close()
        await engine.dispose()
        await bot.session.close()
