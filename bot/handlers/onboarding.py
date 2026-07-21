import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bot.keyboards import cancel_keyboard, remove_keyboard
from config import Settings
from database import TrainingResultRepository
from schemas import TrainingSessionDraft
from services import AITrainingService, TrainingService

logger = logging.getLogger(__name__)
router = Router()


class TrainingStates(StatesGroup):
    active = State()


@router.message(Command("start"))
async def handle_start(message: Message, state: FSMContext, settings: Settings, training_service: TrainingService) -> None:
    await state.clear()
    await state.set_state(TrainingStates.active)
    await state.update_data(
        draft=training_service.start_session(settings.quiz_question_count).model_dump(),
        result_id=None,
        name_collected=False,
    )
    await message.answer(
        "Здравствуйте! Я помогу изучить новый материал, а затем проведу тестирование.\n\n"
        "Напишите имя сотрудника, которого нужно обучить.",
        reply_markup=cancel_keyboard(),
    )


@router.message(Command("cancel"))
async def handle_cancel(message: Message, state: FSMContext) -> None:
    current_state = await state.get_state()
    if current_state is None:
        await message.answer("Сейчас нет активной сессии обучения.", reply_markup=remove_keyboard())
        return

    await state.clear()
    await message.answer(
        "Сессия обучения отменена. Чтобы начать заново, отправьте /start.",
        reply_markup=remove_keyboard(),
    )


@router.message(TrainingStates.active, F.text)
async def process_ai_training(
    message: Message,
    state: FSMContext,
    settings: Settings,
    training_service: TrainingService,
    ai_training_service: AITrainingService,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    state_data = await state.get_data()
    draft = TrainingSessionDraft.model_validate(state_data.get("draft", {}))
    name_collected = bool(state_data.get("name_collected"))
    user_text = message.text or ""

    try:
        draft_before_turn = draft
        answer_feedback: str | None = None

        if not name_collected:
            updated_draft = training_service.register_employee_name(draft=draft, employee_name=user_text)
            await state.update_data(draft=updated_draft.model_dump(), name_collected=True)
            draft_before_turn = updated_draft
            ai_turn = await ai_training_service.generate_turn(
                draft=updated_draft,
                user_message="Сотрудник готов начать обучение.",
                is_new_dialogue=True,
            )
            answer_feedback = training_service.resolve_answer_feedback(ai_turn, draft_before_turn)
            if answer_feedback and ai_turn.latest_answer_evaluated:
                ai_turn = ai_turn.model_copy(update={"answer_feedback": answer_feedback})
            updated_draft = training_service.apply_ai_turn(updated_draft, ai_turn)
            await state.update_data(draft=updated_draft.model_dump())
        else:
            ai_turn = await ai_training_service.generate_turn(
                draft=draft,
                user_message=user_text,
                is_new_dialogue=False,
            )
            answer_feedback = training_service.resolve_answer_feedback(ai_turn, draft_before_turn)
            if answer_feedback and ai_turn.latest_answer_evaluated:
                ai_turn = ai_turn.model_copy(update={"answer_feedback": answer_feedback})
            updated_draft = training_service.apply_ai_turn(draft, ai_turn)
            await state.update_data(draft=updated_draft.model_dump())

        if updated_draft.phase == "completed":
            async with session_factory() as session:
                repository = TrainingResultRepository(session)
                await training_service.create_result(
                    repository=repository,
                    draft=updated_draft,
                    topic=settings.training_topic,
                    telegram_user_id=message.from_user.id if message.from_user else 0,
                    telegram_chat_id=message.chat.id,
                )

            await state.clear()
            await message.answer(
                training_service.format_completion_message(
                    answer_feedback=answer_feedback,
                    final_summary=updated_draft.final_summary or ai_turn.reply,
                    correct_answers=updated_draft.correct_answers,
                    total_questions=updated_draft.total_questions,
                    score_percent=updated_draft.score_percent(),
                ),
                reply_markup=remove_keyboard(),
            )
            return

        await message.answer(
            training_service.format_turn_message(
                ai_turn,
                updated_draft,
                answer_feedback=answer_feedback,
            ),
            reply_markup=cancel_keyboard(),
        )
    except ValueError as exc:
        await message.answer(str(exc), reply_markup=cancel_keyboard())
    except Exception:
        logger.exception("Failed to process AI training")
        await message.answer(
            "Не удалось обработать сообщение. Попробуйте еще раз или отправьте /cancel.",
            reply_markup=cancel_keyboard(),
        )


@router.message(TrainingStates.active)
async def handle_invalid_collecting_input(message: Message) -> None:
    await message.answer("Пожалуйста, отправьте ответ текстом.", reply_markup=cancel_keyboard())


@router.message(F.text)
async def handle_text_without_flow(message: Message) -> None:
    await message.answer("Чтобы начать обучение и тестирование, отправьте /start.")


@router.message()
async def handle_unsupported_input(message: Message) -> None:
    await message.answer("Пожалуйста, используйте текстовые сообщения или команду /start.")
