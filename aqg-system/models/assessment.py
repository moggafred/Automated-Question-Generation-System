"""Schemas describing a learner's answer and the graded outcome."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from models.question import Difficulty, QuestionType, normalize_answer_text


class SubmittedAnswer(BaseModel):
    """A single learner response, keyed by the question id it belongs to."""

    question_id: int = Field(..., ge=1, description="Id of the question being answered.")
    answer: str = Field(default="", max_length=20000, description="Selected option, label or free text.")
    time_spent_seconds: float = Field(0.0, ge=0, le=86400, description="Optional time-on-question metric.")

    @field_validator("answer", mode="before")
    @classmethod
    def _coerce_answer(cls, value: Any) -> Any:
        if value is None:
            return ""
        if isinstance(value, (int, float, bool)):
            return str(value)
        return str(value)

    @property
    def normalized(self) -> str:
        return normalize_answer_text(self.answer)

    @property
    def is_blank(self) -> bool:
        return not self.normalized


class AssessmentSubmission(BaseModel):
    """The payload accepted by ``POST /api/assessment/{quiz_id}/submit``."""

    answers: list[SubmittedAnswer] = Field(..., min_length=1, description="All answered questions.")
    time_spent_seconds: float = Field(0.0, ge=0, le=86400, description="Total session duration.")
    learner_note: str = Field("", max_length=1000, description="Optional self-reflection note.")

    @property
    def answer_map(self) -> dict[int, SubmittedAnswer]:
        return {answer.question_id: answer for answer in self.answers}


class QuestionReview(BaseModel):
    """Per-question feedback shown after submission."""

    question_id: int = Field(..., description="Id of the reviewed question.")
    question: str = Field(..., description="Question text as shown to the learner.")
    type: str = Field(..., description="Question type label.")
    difficulty: str = Field(..., description="Difficulty label.")
    topic: str = Field(default="", description="Assessed sub-topic.")
    scenario: str | None = Field(default=None, description="Scenario narrative when applicable.")
    your_answer: str = Field(default="", description="What the learner submitted.")
    correct_answer: str = Field(..., description="Authoritative answer revealed after grading.")
    explanation: str = Field(default="", description="Explanation of the correct answer.")
    marking_criteria: list[str] = Field(default_factory=list, description="Guidance for extended responses.")
    correct: bool = Field(..., description="True when full marks were awarded.")
    partial: bool = Field(default=False, description="True when partial credit was awarded.")
    points_awarded: float = Field(0.0, description="Marks earned for this item.")
    points_available: float = Field(1.0, description="Maximum marks for this item.")
    source_reference: str | None = Field(default=None, description="Grounding reference for the item.")
    auto_graded: bool = Field(default=True, description="False for types needing human marking.")


class AssessmentResult(BaseModel):
    """The complete graded outcome of a submission."""

    model_config = ConfigDict(use_enum_values=True)

    attempt_id: str = Field(..., description="UUID4 of the stored assessment attempt.")
    quiz_id: str = Field(..., description="UUID4 of the graded assessment.")
    quiz_title: str = Field(default="Assessment", description="Title of the graded assessment.")
    topic: str = Field(default="", description="Topic label of the assessment.")
    performance_band: str = Field(..., description="Human readable performance summary.")
    score: float = Field(..., description="Marks earned.")
    total_score: float = Field(..., description="Marks available.")
    percentage: float = Field(..., ge=0, le=100, description="Percentage score rounded to one decimal.")
    correct_answers: int = Field(..., description="Items answered fully correctly.")
    incorrect_answers: int = Field(..., description="Items answered incorrectly.")
    unanswered: int = Field(..., description="Items left blank.")
    partial_answers: int = Field(default=0, description="Items that earned partial credit.")
    total_questions: int = Field(..., description="Number of items in the assessment.")
    attempted: int = Field(..., description="Items the learner actually answered.")
    accuracy: float = Field(..., ge=0, le=100, description="Percentage of attempted items answered correctly.")
    time_spent_seconds: float = Field(default=0.0, description="Total time spent on the assessment.")
    breakdown: dict[str, dict[str, float]] = Field(
        default_factory=dict,
        description="Average percentage per question type.",
    )
    review: list[QuestionReview] = Field(default_factory=list, description="Question-by-question review.")
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="microseconds"),
        description="ISO-8601 UTC grading timestamp.",
    )


def performance_band(percentage: float) -> tuple[str, str]:
    """Maps a percentage onto a band label and a short verdict."""
    if percentage >= 90:
        return "excellent", "Outstanding mastery of this material."
    if percentage >= 80:
        return "very-good", "Very Good — a strong grasp with a few gaps to review."
    if percentage >= 70:
        return "good", "Good — solid understanding, revisit the missed topics."
    if percentage >= 60:
        return "satisfactory", "Satisfactory — review the material and retake for a better result."
    if percentage >= 40:
        return "needs-improvement", "Needs Improvement — work through the study materials again."
    return "unsatisfactory", "Unsatisfactory — rebuild the fundamentals before moving on."


def is_choice_type(question_type: str | QuestionType) -> bool:
    return question_type in (
        QuestionType.MULTIPLE_CHOICE.value,
        QuestionType.TRUE_FALSE.value,
        QuestionType.SCENARIO.value,
    )


__all__ = [
    "AssessmentResult",
    "AssessmentSubmission",
    "Difficulty",
    "QuestionReview",
    "SubmittedAnswer",
    "is_choice_type",
    "performance_band",
]