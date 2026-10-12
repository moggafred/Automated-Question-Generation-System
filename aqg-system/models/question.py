"""Question-level schemas for every supported assessment format.

These models are the single source of truth for generated content. Fields that
do not apply to a question type are optional (never mandatory) so a scenario
question can carry a `scenario` block while a plain short-answer question does
not have to invent one.
"""

from __future__ import annotations

import re
from enum import Enum
from typing import Any, Iterable

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

OPTION_LABELS = ("A", "B", "C", "D", "E", "F")


class QuestionType(str, Enum):
    """All assessment item formats the platform can generate."""

    MULTIPLE_CHOICE = "multiple-choice"
    TRUE_FALSE = "true-false"
    SHORT_ANSWER = "short-answer"
    FILL_IN_THE_BLANK = "fill-in-the-blank"
    ESSAY = "essay"
    SCENARIO = "scenario"
    CASE_STUDY = "case-study"
    APPLICATION = "application"


#: Types whose learner response is selected from a fixed option list.
CHOICE_TYPES: frozenset[QuestionType] = frozenset(
    {QuestionType.MULTIPLE_CHOICE, QuestionType.TRUE_FALSE, QuestionType.SCENARIO}
)

#: Types that must present a real-world situation before the question.
SCENARIO_TYPES: frozenset[QuestionType] = frozenset(
    {QuestionType.SCENARIO, QuestionType.CASE_STUDY}
)

#: Types requiring an extended written response.
LONG_FORM_TYPES: frozenset[QuestionType] = frozenset(
    {QuestionType.ESSAY, QuestionType.APPLICATION, QuestionType.CASE_STUDY}
)

#: Human readable labels reused by the API metadata endpoint and the UI.
QUESTION_TYPE_LABELS: dict[str, str] = {
    QuestionType.MULTIPLE_CHOICE.value: "Multiple Choice",
    QuestionType.TRUE_FALSE.value: "True / False",
    QuestionType.SHORT_ANSWER.value: "Short Answer",
    QuestionType.FILL_IN_THE_BLANK.value: "Fill in the Blank",
    QuestionType.ESSAY.value: "Essay",
    QuestionType.SCENARIO.value: "Scenario-Based",
    QuestionType.CASE_STUDY.value: "Case Study",
    QuestionType.APPLICATION.value: "Application",
}

#: Accepted aliases so legacy clients keep working with the new vocabulary.
QUESTION_TYPE_ALIASES: dict[str, QuestionType] = {
    "mcq": QuestionType.MULTIPLE_CHOICE,
    "multiple_choice": QuestionType.MULTIPLE_CHOICE,
    "multiplechoice": QuestionType.MULTIPLE_CHOICE,
    "true_false": QuestionType.TRUE_FALSE,
    "truefalse": QuestionType.TRUE_FALSE,
    "boolean": QuestionType.TRUE_FALSE,
    "short": QuestionType.SHORT_ANSWER,
    "shortanswer": QuestionType.SHORT_ANSWER,
    "fill": QuestionType.FILL_IN_THE_BLANK,
    "fill_in_blank": QuestionType.FILL_IN_THE_BLANK,
    "fillintheblank": QuestionType.FILL_IN_THE_BLANK,
    "fill-in-blank": QuestionType.FILL_IN_THE_BLANK,
    "long": QuestionType.ESSAY,
    "essay": QuestionType.ESSAY,
    "scenario_based": QuestionType.SCENARIO,
    "scenario-based": QuestionType.SCENARIO,
    "case": QuestionType.CASE_STUDY,
    "casestudy": QuestionType.CASE_STUDY,
    "apply": QuestionType.APPLICATION,
    "problem-solving": QuestionType.APPLICATION,
    "problem_solving": QuestionType.APPLICATION,
}


class Difficulty(str, Enum):
    EASY = "easy"
    MEDIUM = "medium"
    HARD = "hard"


DIFFICULTY_LABELS: dict[str, str] = {
    Difficulty.EASY.value: "Easy",
    Difficulty.MEDIUM.value: "Medium",
    Difficulty.HARD.value: "Hard",
}

DIFFICULTY_ALIASES: dict[str, Difficulty] = {
    "e": Difficulty.EASY,
    "easy": Difficulty.EASY,
    "basic": Difficulty.EASY,
    "beginner": Difficulty.EASY,
    "m": Difficulty.MEDIUM,
    "medium": Difficulty.MEDIUM,
    "moderate": Difficulty.MEDIUM,
    "intermediate": Difficulty.MEDIUM,
    "h": Difficulty.HARD,
    "hard": Difficulty.HARD,
    "advanced": Difficulty.HARD,
    "expert": Difficulty.HARD,
    "challenging": Difficulty.HARD,
}


def resolve_question_type(raw: str | None) -> QuestionType | None:
    """Maps a free-form user string onto a supported :class:`QuestionType`."""
    if raw is None:
        return None
    key = str(raw).strip().lower().replace(" ", "_")
    if not key:
        return None
    for candidate in QuestionType:
        if candidate.value == key:
            return candidate
    aliased = QUESTION_TYPE_ALIASES.get(key)
    if aliased is not None:
        return aliased
    return None


def resolve_difficulty(raw: str | None, default: Difficulty = Difficulty.MEDIUM) -> Difficulty:
    """Maps a free-form user string onto a supported :class:`Difficulty`."""
    if raw is None:
        return default
    key = str(raw).strip().lower()
    if not key:
        return default
    try:
        return Difficulty(key)
    except ValueError:
        return DIFFICULTY_ALIASES.get(key, default)


def normalize_answer_text(value: Any) -> str:
    """Case/whitespace/punctuation-insensitive normalisation used for grading."""
    if value is None:
        return ""
    text = str(value).strip().lower()
    text = re.sub(r"[\s ]+", " ", text)
    text = re.sub(r"[“”\"'`]", "", text)
    text = re.sub(r"[.,;:!?]+$", "", text)
    return text.strip()


class Option(BaseModel):
    """A single selectable answer choice.

    Accepts a bare string so older stored payloads (a flat list of strings)
    continue to validate without a migration.
    """

    model_config = ConfigDict(populate_by_name=True)

    id: str = Field(
        "",
        max_length=4,
        description="Option label such as A, B, C or D. Assigned positionally when absent.",
    )
    text: str = Field(..., min_length=1, description="The answer choice text.")
    is_correct: bool = Field(False, description="True only for the single correct choice.")

    @model_validator(mode="before")
    @classmethod
    def _accept_bare_string(cls, value: Any) -> Any:
        """Accepts legacy payloads where an option was just a string."""
        if isinstance(value, str):
            stripped = value.strip()
            if not stripped:
                raise ValueError("Option text cannot be empty.")
            return {"text": stripped}
        if isinstance(value, dict):
            data = dict(value)
            text = data.get("text", data.get("option", data.get("label")))
            if isinstance(text, str) and text.strip():
                data["text"] = text.strip()
            if not data.get("id"):
                legacy = data.get("label")
                if isinstance(legacy, str) and legacy.strip():
                    data["id"] = legacy.strip()[:4].upper()
            data.pop("option", None)
            data.pop("label", None)
            return data
        return value

    @model_validator(mode="after")
    def _require_text(self) -> "Option":
        """Guarantees the option carries readable text after coercion."""
        if not self.text or not self.text.strip():
            raise ValueError("Option text cannot be empty.")
        return self

    def __str__(self) -> str:  # pragma: no cover - convenience for logging
        return self.text


class Question(BaseModel):
    """A single assessment item.

    Optional fields stay optional so a type only carries what applies to it.
    """

    model_config = ConfigDict(use_enum_values=True)

    id: int = Field(..., ge=1, description="Sequential question number inside the assessment.")
    type: QuestionType = Field(..., description="Question format for this item.")
    question: str = Field(..., min_length=1, description="The question text shown to the learner.")
    options: list[Option] = Field(
        default_factory=list,
        description="Selectable choices. Empty for open-response question types.",
    )
    correct_answer: str = Field(..., min_length=1, description="Authoritative correct answer.")
    explanation: str = Field(
        default="",
        max_length=2000,
        description="Why the answer is correct; used for post-submission review.",
    )
    difficulty: Difficulty = Field(Difficulty.MEDIUM, description="Calibrated cognitive difficulty.")
    topic: str = Field("", max_length=160, description="Sub-topic this item assesses.")
    scenario: str | None = Field(
        None,
        max_length=4000,
        description="Realistic situation presented before the question (scenario items).",
    )
    case_description: str | None = Field(
        None,
        max_length=6000,
        description="Full case narrative (case-study items).",
    )
    case_id: str | None = Field(None, max_length=80, description="Groups sub-questions of one case study.")
    context: str | None = Field(
        None,
        max_length=4000,
        description="Problem framing or supporting context supplied with the item.",
    )
    marking_criteria: list[str] = Field(
        default_factory=list,
        description="Marking guidance bullets for extended written responses.",
    )
    hint: str | None = Field(None, max_length=600, description="Optional nudge shown before submission.")
    source_reference: str | None = Field(
        None,
        max_length=600,
        description="Grounding reference to the retrieved source context.",
    )
    correct_option_id: str | None = Field(
        None,
        max_length=4,
        description="Option id of the correct choice for choice-based items.",
    )
    points: float = Field(1.0, gt=0, le=100, description="Maximum marks available for this item.")

    @field_validator("question", "correct_answer", mode="before")
    @classmethod
    def _strip_text(cls, value: Any) -> Any:
        if isinstance(value, str):
            stripped = value.strip()
            if not stripped:
                raise ValueError("Question text cannot be empty.")
            return stripped
        return value

    @field_validator("topic", mode="before")
    @classmethod
    def _normalize_topic(cls, value: Any) -> Any:
        if isinstance(value, str):
            return value.strip()[:160]
        return ""

    @model_validator(mode="before")
    @classmethod
    def _accept_legacy_keys(cls, value: Any) -> Any:
        """Repairs payloads written by earlier releases of the platform.

        Older records used different key names and sometimes stored a question id
        as a string. Those rows still live in the history database, so they are
        remapped here instead of failing validation with a 500.
        """
        if not isinstance(value, dict):
            return value

        data = dict(value)

        if not str(data.get("type", "")).strip():
            for key in ("question_type", "format", "kind", "category"):
                resolved = resolve_question_type(data.get(key))
                if resolved is not None:
                    data["type"] = resolved.value
                    break

        for key in ("question_text", "text", "q", "prompt", "title"):
            if not str(data.get("question", "")).strip() and str(data.get(key, "")).strip():
                data["question"] = data[key]
                break

        for key in ("ans", "answer", "correct", "correct_answers", "solution"):
            if not str(data.get("correct_answer", "")).strip():
                candidate = data.get(key)
                if isinstance(candidate, (list, tuple)) and candidate:
                    candidate = candidate[0]
                if str(candidate or "").strip():
                    data["correct_answer"] = candidate
                    break

        # A non-numeric id ("q1", a uuid) is replaced by its position.
        try:
            data["id"] = int(str(data.get("id")).strip())
        except (TypeError, ValueError, AttributeError):
            data["id"] = 0

        return data

    @model_validator(mode="after")
    def _require_text(self) -> "Question":
        """Guarantees the question carries readable text after coercion."""
        if not self.question or not self.question.strip():
            raise ValueError("Question text cannot be empty.")
        return self

    @property
    def is_choice_based(self) -> bool:
        return QuestionType(self.type) in CHOICE_TYPES

    @property
    def has_scenario(self) -> bool:
        return QuestionType(self.type) in SCENARIO_TYPES

    @property
    def effective_text(self) -> str:
        """Question text prefixed with the scenario narrative when present."""
        if self.scenario:
            return f"{self.scenario.strip()}\n\n{self.question.strip()}"
        return self.question

    def resolve_correct_option_id(self) -> str | None:
        """Finds the option id matching ``correct_answer`` text."""
        if self.correct_option_id:
            return self.correct_option_id.upper()
        target = normalize_answer_text(self.correct_answer)
        for option in self.options:
            if normalize_answer_text(option.text) == target:
                return option.id.upper()
        return None

    def public_dict(self) -> dict[str, Any]:
        """Learner-safe payload with every answer key removed.

        The per-option ``is_correct`` flag is stripped too: the evaluator sets it
        during validation, so leaving it in place would hand the answer to anyone
        reading the JSON before submitting.
        """
        payload = self.model_dump(mode="json")
        for leaked in ("correct_answer", "correct_option_id", "explanation", "marking_criteria"):
            payload.pop(leaked, None)
        for option in payload.get("options", []):
            if isinstance(option, dict):
                option.pop("is_correct", None)
        return payload

    def is_answerable(self) -> bool:
        """False when the item is structurally incomplete and must not reach a learner."""
        qtype = QuestionType(self.type)
        if qtype in CHOICE_TYPES:
            return len(self.options) >= 2 and bool(self.correct_answer)
        return bool(self.correct_answer)


def normalize_options(options: Iterable[Any]) -> list[Option]:
    """Coerces loose option input (strings, mappings) into labelled :class:`Option` objects."""
    normalized: list[Option] = []
    seen: set[str] = set()
    for index, raw in enumerate(options or []):
        try:
            option = raw if isinstance(raw, Option) else Option.model_validate(raw)
        except Exception:  # noqa: BLE001 - malformed options are dropped, not fatal
            continue

        label = (option.id or "").strip().upper()
        if not label:
            label = OPTION_LABELS[index] if index < len(OPTION_LABELS) else f"P{index + 1}"
        suffix = 1
        while label in seen:
            label = f"{OPTION_LABELS[index] if index < len(OPTION_LABELS) else 'P'}{suffix}"
            suffix += 1
        seen.add(label)

        normalized.append(option.model_copy(update={"id": label}))
    return normalized


def mark_correct_option(options: list[Option], correct_answer: str) -> str | None:
    """Flags the single option matching ``correct_answer`` and returns its id."""
    target = normalize_answer_text(correct_answer)
    matched_id: str | None = None

    for option in options:
        option.is_correct = normalize_answer_text(option.text) == target
        if option.is_correct:
            matched_id = option.id

    if matched_id is None and options:
        # Guarantee a deterministic, unambiguous answer key.
        options[0].is_correct = True
        matched_id = options[0].id

    return matched_id