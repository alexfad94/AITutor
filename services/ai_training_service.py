import json
import logging
import re

import httpx

from config import Settings
from schemas import TrainingAssistantTurn, TrainingSessionDraft
from services.ai_training_prompts import AI_TRAINING_RESPONSE_SCHEMA, build_training_system_prompt

logger = logging.getLogger(__name__)

_STATEMENT_PREFIXES = (
    "да.",
    "верно",
    "нужно ",
    "необходимо ",
    "открой",
    "открывай",
    "используй",
    "запомни",
)


class AITrainingService:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._training_material = settings.get_training_material()
        self._client = httpx.AsyncClient(
            base_url=settings.openai_base_url,
            timeout=httpx.Timeout(120.0, connect=30.0),
            headers={
                "Authorization": f"Bearer {settings.openai_api_key}",
                "Content-Type": "application/json",
            },
        )

    async def generate_turn(
        self,
        draft: TrainingSessionDraft,
        user_message: str,
        is_new_dialogue: bool,
    ) -> TrainingAssistantTurn:
        turn = await self._request_turn(
            draft=draft,
            user_message=user_message,
            is_new_dialogue=is_new_dialogue,
        )
        return await self._ensure_valid_testing_turn(draft, turn, user_message)

    async def close(self) -> None:
        await self._client.aclose()

    async def _ensure_valid_testing_turn(
        self,
        draft: TrainingSessionDraft,
        turn: TrainingAssistantTurn,
        user_message: str,
    ) -> TrainingAssistantTurn:
        answered_after = draft.questions_answered
        evaluated_current = bool(
            turn.latest_answer_evaluated and draft.phase == "testing" and draft.current_question
        )
        if evaluated_current:
            answered_after += 1

        if evaluated_current:
            turn = await self._ensure_fresh_feedback(draft, turn, user_message)

        if answered_after >= draft.total_questions:
            summary = (turn.final_summary or "").strip() or "Тест завершён."
            return TrainingAssistantTurn(
                reply=turn.reply,
                phase="completed",
                latest_answer_evaluated=True if evaluated_current else turn.latest_answer_evaluated,
                answer_is_correct=turn.answer_is_correct,
                answer_feedback=turn.answer_feedback,
                next_question=None,
                final_summary=summary,
            )

        entered_testing = turn.phase == "testing" or draft.phase == "testing"
        evaluated_with_remaining = evaluated_current and answered_after < draft.total_questions
        needs_question = entered_testing or evaluated_with_remaining

        if not needs_question:
            return turn

        if self._is_valid_question(turn.next_question):
            if turn.phase != "testing":
                return turn.model_copy(update={"phase": "testing"})
            return turn

        logger.warning(
            "AI testing turn missing a valid question (answered=%s/%s); requesting next question",
            answered_after,
            draft.total_questions,
        )
        question_turn = await self._request_next_question(draft, answered_after)
        question = question_turn.next_question
        if not self._is_valid_question(question):
            question = (
                f"Ситуация из материала по теме «{self._settings.training_topic}». "
                "Что вы сделаете и почему? Ответьте своими словами."
            )

        parts: list[str] = []
        if turn.latest_answer_evaluated and turn.answer_feedback:
            parts.append(turn.answer_feedback)
        parts.append(question)

        return TrainingAssistantTurn(
            reply="\n\n".join(parts),
            phase="testing",
            latest_answer_evaluated=turn.latest_answer_evaluated,
            answer_is_correct=turn.answer_is_correct,
            answer_feedback=turn.answer_feedback,
            next_question=question,
            final_summary=None,
        )

    async def _ensure_fresh_feedback(
        self,
        draft: TrainingSessionDraft,
        turn: TrainingAssistantTurn,
        user_message: str,
    ) -> TrainingAssistantTurn:
        previous = (draft.last_answer_feedback or "").strip()
        feedback = (turn.answer_feedback or "").strip()
        if feedback and feedback != previous:
            return turn

        logger.warning("AI reused or omitted answer feedback; requesting fresh feedback")
        fresh = await self._request_answer_feedback(draft, user_message, turn)
        return turn.model_copy(update={"answer_feedback": fresh, "latest_answer_evaluated": True})

    async def _request_answer_feedback(
        self,
        draft: TrainingSessionDraft,
        user_message: str,
        turn: TrainingAssistantTurn,
    ) -> str:
        previous = draft.last_answer_feedback or ""
        correctness = (
            "верный"
            if turn.answer_is_correct is True
            else "неверный"
            if turn.answer_is_correct is False
            else "не определён"
        )
        prompt = (
            "Нужна только краткая обратная связь по последнему ответу теста.\n"
            f"Вопрос, на который отвечал сотрудник:\n{draft.current_question}\n\n"
            f"Ответ сотрудника:\n{user_message}\n\n"
            f"Оценка: {correctness}\n"
            f"Запрещено копировать этот старый текст: {previous or '—'}\n\n"
            "Верни JSON того же формата:\n"
            "- phase = testing\n"
            "- latest_answer_evaluated = true\n"
            "- answer_is_correct оставь как есть по смыслу оценки выше\n"
            "- answer_feedback: 1-2 предложения строго про этот вопрос и этот ответ\n"
            "- next_question = null\n"
            "- final_summary = null\n"
            "- reply = тот же текст, что answer_feedback"
        )
        feedback_turn = await self._request_turn_raw(draft=draft, user_content=prompt)
        feedback = (feedback_turn.answer_feedback or feedback_turn.reply or "").strip()
        if not feedback or feedback == previous:
            if turn.answer_is_correct is True:
                return "Верно: ответ соответствует правилу из материала."
            if turn.answer_is_correct is False:
                return "Неверно: перечитайте правило по этому вопросу в материале."
            return "Ответ принят."
        return feedback

    async def _request_next_question(
        self,
        draft: TrainingSessionDraft,
        answered_after: int,
    ) -> TrainingAssistantTurn:
        next_number = answered_after + 1
        prompt = (
            f"Текущее состояние сессии:\n"
            f"{json.dumps(draft.model_dump(), ensure_ascii=False, indent=2)}\n\n"
            f"Уже проверено ответов: {answered_after} из {draft.total_questions}.\n"
            f"Сейчас нужен вопрос номер {next_number}.\n\n"
            "Сформируй ТОЛЬКО следующий вопрос теста.\n"
            "- phase = testing\n"
            "- next_question обязателен и должен быть вопросом/кейсом с «?»\n"
            "- reply должен содержать тот же вопрос\n"
            "- latest_answer_evaluated = false\n"
            "- answer_feedback = null\n"
            "- не пиши правильный ответ и не продолжай обучение\n"
            "- вопрос должен отличаться от current_question, если он был"
        )
        return await self._request_turn_raw(draft=draft, user_content=prompt)

    async def _request_turn(
        self,
        draft: TrainingSessionDraft,
        user_message: str,
        is_new_dialogue: bool,
    ) -> TrainingAssistantTurn:
        return await self._request_turn_raw(
            draft=draft,
            user_content=self._build_prompt(
                draft=draft,
                user_message=user_message,
                is_new_dialogue=is_new_dialogue,
            ),
        )

    async def _request_turn_raw(
        self,
        draft: TrainingSessionDraft,
        user_content: str,
    ) -> TrainingAssistantTurn:
        payload = {
            "model": self._settings.openai_model,
            "temperature": 0.2,
            "messages": [
                {
                    "role": "system",
                    "content": build_training_system_prompt(
                        topic=self._settings.training_topic,
                        material=self._training_material,
                        total_questions=draft.total_questions,
                    ),
                },
                {
                    "role": "user",
                    "content": user_content,
                },
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": AI_TRAINING_RESPONSE_SCHEMA,
            },
        }

        response = await self._client.post("/chat/completions", json=payload)
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]
        return TrainingAssistantTurn.model_validate(json.loads(content))

    @staticmethod
    def _is_valid_question(value: str | None) -> bool:
        if not value:
            return False
        cleaned = " ".join(value.split()).strip()
        if len(cleaned) < 12:
            return False
        if "?" not in cleaned and "？" not in cleaned:
            return False
        lowered = cleaned.lower()
        if any(lowered.startswith(prefix) for prefix in _STATEMENT_PREFIXES):
            return False
        if re.match(r"^(да|нет)[\s,.!:—-]", lowered):
            return False
        return True

    @staticmethod
    def _build_prompt(
        draft: TrainingSessionDraft,
        user_message: str,
        is_new_dialogue: bool,
    ) -> str:
        serialized_draft = json.dumps(draft.model_dump(), ensure_ascii=False, indent=2)
        remaining = draft.remaining_questions()
        current_q = draft.current_question or "—"
        return (
            f"Новая сессия: {str(is_new_dialogue).lower()}\n"
            f"Текущее состояние сессии:\n{serialized_draft}\n\n"
            f"Текущий вопрос для проверки (если есть):\n{current_q}\n\n"
            f"Последнее сообщение сотрудника:\n{user_message}\n\n"
            "Важно:\n"
            "- если phase сейчас learning, сначала обучай и только потом переводи в testing;\n"
            "- если сотрудник готов к тесту, сразу переходи в phase=testing и задай первый вопрос "
            "(next_question обязателен, вопрос должен быть и в reply);\n"
            "- если phase сейчас testing и current_question заполнен, оцени именно ответ на current_question;\n"
            "- answer_feedback пиши заново только про current_question и последний ответ; "
            "запрещено копировать last_answer_feedback;\n"
            "- после оценки, если вопросы ещё остались, сразу задай следующий вопрос в next_question и reply "
            f"(осталось вопросов после текущей проверки: максимум {remaining});\n"
            "- если это был последний вопрос, поставь phase=completed, заполни answer_feedback по последнему "
            "ответу и отдельно final_summary; не пропускай комментарий к последнему ответу;\n"
            "- если phase сейчас testing, а current_question пустой и вопросы ещё не закончены — "
            "сразу задай следующий вопрос, не продолжай обучение;\n"
            "- в testing запрещено вместо вопроса писать правильный ответ или учебный абзац;\n"
            "- questions_answered уже содержит число проверенных ответов."
        )
