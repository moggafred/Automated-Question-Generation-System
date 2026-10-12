"""Assessment container schemas: quiz payloads and case-study groupings."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from models.question import (
    DIFFICULTY_LABELS,
    QUESTION_TYPE_LABELS,
    Difficulty,
    Option,
    Question,
    QuestionType,
    normalize_options,
    resolve_question_type,
)


def repair_question_item(raw: Any, index: int) -> dict[str, Any] | None:
    """Normalises one stored question into a shape :class:`Question` accepts.

    Stored history predates the current schema, so items arrive with missing
    types, legacy key names or string ids. Anything that still cannot be made
    answerable is dropped rather than served to a learner.
    """
    if isinstance(raw, Question):
        return raw.model_dump(mode="json")
    if not isinstance(raw, dict):
        return None

    data = dict(raw)

    if not isinstance(data.get("id"), int) or int(data.get("id", 0)) < 1:
        data["id"] = index

    data["options"] = normalize_options(data.get("options") or [])

    if resolve_question_type(data.get("type")) is None:
        # Fall back to the shape of the item itself: options imply a choice type.
        inferred = (
            QuestionType.MULTIPLE_CHOICE
            if len(data["options"]) >= 2
            else QuestionType.SHORT_ANSWER
        )
        data["type"] = inferred.value
    else:
        data["type"] = resolve_question_type(data["type"]).value

    # QuestionType/Option coercion above rewrites legacy keys, so re-read them.
    for key in ("question_text", "text", "q", "prompt"):
        if not str(data.get("question", "")).strip() and str(data.get(key, "")).strip():
            data["question"] = data[key]
            break

    if not str(data.get("correct_answer", "")).strip():
        answer_key = None
        for key in ("ans", "answer", "correct", "solution"):
            if str(data.get(key, "")).strip():
                answer_key = data[key]
                break
        if answer_key is None and data["options"]:
            # No stored key: the first option is the best available fallback.
            answer_key = data["options"][0].text
        if not str(answer_key or "").strip():
            # Nothing gradeable survives, so the item is dropped.
            return None
        data["correct_answer"] = answer_key

    if not str(data.get("question", "")).strip():
        # The answer is intact but the wording was never stored: keep the item
        # so numbering and previous attempts stay aligned.
        data["question"] = f"Question {data['id']}"

    return data


class CaseStudy(BaseModel):
    """A grounded case with narrative, framing and its assessment questions."""

    model_config = ConfigDict(use_enum_values=True)

    id: str = Field(default_factory=lambda: f"case-{uuid.uuid4().hex[:8]}", description="Case identifier.")
    title: str = Field("", max_length=200, description="Short case title.")
    description: str = Field(
        "",
        max_length=6000,
        description="The realistic case narrative drawn from the source document.",
    )
    context: str = Field("", max_length=4000, description="Problem framing or professional setting.")
    expected_answer: str = Field("", max_length=4000, description="Expected outcome of the analysis.")
    marking_guidance: list[str] = Field(
        default_factory=list,
        description="Bullets describing what a strong answer must contain.",
    )
    question_ids: list[int] = Field(
        default_factory=list,
        description="Ids of the questions belonging to this case.",
    )
    source_reference: str | None = Field(None, max_length=600, description="Grounding reference.")
    difficulty: Difficulty = Field(Difficulty.MEDIUM, description="Calibrated difficulty.")
    topic: str = Field("", max_length=160, description="Case topic.")

    def to_public_dict(self) -> dict[str, Any]:
        payload = self.model_dump(mode="json")
        payload.pop("expected_answer", None)
        payload.pop("marking_guidance", None)
        return payload


class Assessment(BaseModel):
    """A complete generated assessment (legacy alias kept for compatibility)."""

    model_config = ConfigDict(use_enum_values=True, populate_by_name=True)

    quiz_title: str = Field(default="Generated Assessment", max_length=240, description="Assessment title.")
    questions: list[Question] = Field(default_factory=list, description="Ordered assessment items.")
    summary: str = Field("", max_length=2000, description="Short orientation summary for learners.")
    topic: str = Field("", max_length=200, description="Topic label supplied by the learner.")
    difficulty: Difficulty = Field(Difficulty.MEDIUM, description="Requested difficulty calibration.")
    question_type: str = Field("", max_length=60, description="Requested question format label.")
    case_studies: list[CaseStudy] = Field(
        default_factory=list,
        description="Grouped case studies when the case-study format was requested.",
    )

    @field_validator("questions", mode="before")
    @classmethod
    def _coerce_questions(cls, value: Any) -> Any:
        if not isinstance(value, list):
            return value
        repaired: list[dict[str, Any]] = []
        for index, raw in enumerate(value, start=1):
            item = repair_question_item(raw, index)
            if item is not None:
                repaired.append(item)
        return repaired

    @field_validator("topic", "quiz_title", mode="before")
    @classmethod
    def _strip_text(cls, value: Any) -> Any:
        return value.strip() if isinstance(value, str) else value

    # -- Derived helpers -------------------------------------------------
    @property
    def question_count(self) -> int:
        return len(self.questions)

    @property
    def total_points(self) -> float:
        return round(sum(float(question.points) for question in self.questions), 2)

    @property
    def is_empty(self) -> bool:
        return not self.questions

    def question_types(self) -> list[str]:
        return [str(question.type) for question in self.questions]

    def to_dict(self) -> dict[str, Any]:
        """Full canonical payload, including the answer key."""
        return self.model_dump(mode="json")

    def to_public_dict(self) -> dict[str, Any]:
        """Learner-safe payload used before submission (no answer keys)."""
        return {
            "quiz_title": self.quiz_title,
            "summary": self.summary,
            "topic": self.topic,
            "difficulty": str(self.difficulty),
            "question_type": self.question_type,
            "question_count": self.question_count,
            "total_points": self.total_points,
            "questions": [question.public_dict() for question in self.questions],
            "case_studies": [case.to_public_dict() for case in self.case_studies],
        }

    @classmethod
    def from_payload(cls, payload: Any) -> "Assessment":
        """Builds an assessment from a stored/raw quiz payload, repairing structure."""
        if isinstance(payload, cls):
            return payload
        if not isinstance(payload, dict):
            return cls(questions=[])

        data = dict(payload)
        data.pop("quiz_id", None)
        data["questions"] = list(data.get("questions") or [])
        data.setdefault("quiz_title", "Generated Assessment")
        return cls.model_validate(data)


class Quiz(Assessment):
    """Named alias of :class:`Assessment` for readability in service code."""

    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Tracking metadata such as quiz_id, created_at and source filename.",
    )

    def response_payload(self) -> dict[str, Any]:
        payload = self.to_dict()
        payload.update(self.metadata)
        return payload

    @classmethod
    def with_metadata(cls, payload: Any, metadata: dict[str, Any]) -> "Quiz":
        return cls.model_validate(
            Assessment.from_payload(payload).to_dict() | {"metadata": metadata}
        )


def build_metadata(
    *,
    quiz_id: str | None = None,
    topic: str = "",
    quiz_type: str = "",
    num_questions: int = 0,
    source_filename: str | None = None,
    created_at: datetime | None = None,
    difficulty: str = "",
    document_id: str | None = None,
) -> dict[str, Any]:
    """Assembles the tracking block echoed back with every generation response."""
    stamp = created_at or datetime.now(timezone.utc)
    metadata: dict[str, Any] = {
        "quiz_id": quiz_id,
        "topic": topic,
        "quiz_type": quiz_type,
        "num_questions": num_questions,
        "difficulty": difficulty,
        "question_count": num_questions,
        "question_type_labels": QUESTION_TYPE_LABELS,
        "difficulty_labels": DIFFICULTY_LABELS,
        "source_filename": source_filename,
        "document_id": document_id,
        "created_at": stamp.isoformat(timespec="microseconds"),
    }
    return metadata


def group_case_studies(assessment: Assessment) -> list[CaseStudy]:
    """Builds :class:`CaseStudy` records from the case-study items inside an assessment."""
    grouped: dict[str, CaseStudy] = {}

    for question in assessment.questions:
        if question.type != QuestionType.CASE_STUDY:
            continue
        key = question.case_id or f"case-{question.id}"
        case = grouped.get(key)
        if case is None:
            case = CaseStudy(
                id=key,
                title=(question.topic or assessment.quiz_title).strip()[:200],
                description=(question.case_description or question.scenario or "").strip(),
                context=(question.context or "").strip(),
                expected_answer=question.correct_answer,
                marking_guidance=list(question.marking_criteria),
                source_reference=question.source_reference,
                difficulty=Difficulty(question.difficulty),
                topic=question.topic,
            )
            grouped[key] = case
        case.question_ids.append(question.id)
        if question.context and question.context not in case.context:
            case.context = f"{case.context}\n\n{question.context}".strip()

    return list(grouped.values())


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


__all__ = [
    "Assessment",
    "CaseStudy",
    "Option",
    "Question",
    "QuestionType",
    "Difficulty",
    "Quiz",
    "build_metadata",
    "group_case_studies",
    "utc_now_iso",
]