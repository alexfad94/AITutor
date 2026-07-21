from database.models import TrainingResult
from database.repository import TrainingResultRepository
from schemas import TrainingAssistantTurn, TrainingResultCreate, TrainingSessionDraft


class TrainingService:
    @staticmethod
    def validate_employee_name(value: str) -> str:
        cleaned = " ".join(value.split()).strip()
        if len(cleaned) < 2:
            raise ValueError("Укажите имя сотрудника хотя бы из двух символов.")
        return cleaned

    def start_session(self, total_questions: int) -> TrainingSessionDraft:
        return TrainingSessionDraft(total_questions=total_questions)

    def register_employee_name(self, draft: TrainingSessionDraft, employee_name: str) -> TrainingSessionDraft:
        updated = TrainingSessionDraft.model_validate(draft.model_dump())
        updated.employee_name = self.validate_employee_name(employee_name)
        updated.phase = "learning"
        return updated

    def apply_ai_turn(
        self,
        current: TrainingSessionDraft,
        ai_turn: TrainingAssistantTurn,
    ) -> TrainingSessionDraft:
        updated = TrainingSessionDraft.model_validate(current.model_dump())
        updated.phase = ai_turn.phase

        if ai_turn.latest_answer_evaluated and current.phase == "testing" and current.current_question:
            updated.questions_answered += 1
            if ai_turn.answer_is_correct:
                updated.correct_answers += 1

        if ai_turn.latest_answer_evaluated and ai_turn.answer_feedback:
            previous = (current.last_answer_feedback or "").strip()
            incoming = ai_turn.answer_feedback.strip()
            if incoming and incoming != previous:
                updated.last_answer_feedback = incoming

        updated.current_question = ai_turn.next_question

        if ai_turn.final_summary is not None:
            updated.final_summary = ai_turn.final_summary

        # Do not drop back to learning mid-test; complete when all answers are checked.
        if updated.questions_answered >= updated.total_questions:
            updated.phase = "completed"
            updated.current_question = None
        elif updated.questions_answered > 0 and updated.phase == "learning":
            updated.phase = "testing"

        return updated

    @staticmethod
    def resolve_answer_feedback(
        ai_turn: TrainingAssistantTurn,
        draft_before: TrainingSessionDraft,
    ) -> str | None:
        """Pick feedback for the latest answer; drop stale copies of the previous feedback."""
        if not ai_turn.latest_answer_evaluated:
            return None

        previous = (draft_before.last_answer_feedback or "").strip() or None
        feedback = (ai_turn.answer_feedback or "").strip() or None
        if feedback and previous and feedback == previous:
            feedback = None

        if feedback:
            return feedback

        reply = ai_turn.reply.strip()
        if ai_turn.next_question and ai_turn.next_question in reply:
            reply = reply.replace(ai_turn.next_question, "").strip()
        for marker in ("Тест завершён.", "Тест завершен."):
            reply = reply.replace(marker, "").strip()

        chunk = reply.split("\n\n")[0].strip() if reply else ""
        if chunk and previous and chunk == previous:
            chunk = ""
        if chunk and ("?" in chunk and len(chunk) > 80):
            chunk = ""
        if len(chunk) >= 8:
            return chunk

        if ai_turn.answer_is_correct is True:
            return "Верно."
        if ai_turn.answer_is_correct is False:
            return "Неверно. Сверьте ответ с правилом из материала."
        return "Ответ принят."

    @staticmethod
    def format_turn_message(
        ai_turn: TrainingAssistantTurn,
        draft: TrainingSessionDraft,
        answer_feedback: str | None = None,
    ) -> str:
        """Build the text shown to the user; always surface the quiz question in testing."""
        if ai_turn.phase != "testing" or not ai_turn.next_question:
            return ai_turn.reply

        question_number = draft.questions_answered + 1
        question_block = f"Вопрос {question_number}/{draft.total_questions}:\n{ai_turn.next_question}"

        parts: list[str] = []
        feedback = answer_feedback
        if feedback is None and ai_turn.latest_answer_evaluated:
            feedback = ai_turn.answer_feedback

        if feedback:
            parts.append(feedback)
        else:
            intro = ai_turn.reply.strip()
            if (
                intro
                and ai_turn.next_question not in intro
                and len(intro) <= 100
                and ("тест" in intro.lower() or "вопрос" in intro.lower())
            ):
                parts.append(intro)

        parts.append(question_block)
        return "\n\n".join(parts)

    @staticmethod
    def format_completion_message(
        *,
        answer_feedback: str | None,
        final_summary: str,
        correct_answers: int,
        total_questions: int,
        score_percent: int,
    ) -> str:
        parts: list[str] = []
        if answer_feedback:
            parts.append(answer_feedback)
        parts.append(final_summary)
        parts.append(
            "Результат сохранен в БД.\n"
            f"Итог: {correct_answers}/{total_questions} ({score_percent}%)."
        )
        return "\n\n".join(parts)

    async def create_result(
        self,
        repository: TrainingResultRepository,
        draft: TrainingSessionDraft,
        topic: str,
        telegram_user_id: int,
        telegram_chat_id: int,
    ) -> TrainingResult:
        result_in = TrainingResultCreate(
            employee_name=draft.employee_name or "Неизвестный сотрудник",
            telegram_user_id=telegram_user_id,
            telegram_chat_id=telegram_chat_id,
            topic=topic,
            total_questions=draft.total_questions,
            correct_answers=draft.correct_answers,
            score_percent=draft.score_percent(),
            final_summary=draft.final_summary,
        )
        return await repository.create(result_in)
