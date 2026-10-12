"""Local validation guardrail that runs after AI generation.

The LLM is told the schema, but models still drift: they emit three options for a
multiple-choice item, forget to mark an answer, repeat themselves, or hand back a
wall of prose for a scenario item. :class:`QuizEvaluationAgent` repairs the
recoverable cases and drops the items that cannot be fixed, so a learner never
sees a structurally broken question.
"""

from __future__ import annotations

import re
from typing import Any, Iterable

from models.question import (
    CHOICE_TYPES,
    SCENARIO_TYPES,
    Difficulty,
    Option,
    Question,
    QuestionType,
    mark_correct_option,
    normalize_answer_text,
    normalize_options,
)

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")
_TRUTHY = {"true", "yes", "correct", "t", "y"}
_FALSY = {"false", "no", "incorrect", "f", "n"}

MIN_OPTIONS = 2
MAX_OPTIONS = 8
MIN_QUESTION_CHARS = 12
MIN_EXPLANATION_CHARS = 12


def _normalize_boolean_text(value: str) -> str | None:
    """Maps loose truthy/falsy phrasings onto canonical True/False."""
    token = normalize_answer_text(value)
    if token in _TRUTHY:
        return "True"
    if token in _FALSY:
        return "False"
    return None


def _as_list(value: Any) -> list[str]:
    """Flattens strings, bullet lists and nested payloads into a clean list."""
    if value is None:
        return []
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return []
        if "\n" in stripped or stripped.startswith(("-", "*", "•")):
            parts = re.split(r"\n+|^\s*[-*•]\s*", stripped)
            return [part.strip(" -*\t") for part in parts if part.strip(" -*\t")]
        return [stripped]
    if isinstance(value, dict):
        text = value.get("text") or value.get("description") or value.get("body") or value.get("value")
        return [str(text)] if text else []
    if isinstance(value, Iterable):
        collected: list[str] = []
        for item in value:
            collected.extend(_as_list(item))
        return collected
    return [str(value)]


def _normalize_marking_criteria(value: Any) -> list[str]:
    items = [item for item in _as_list(value) if item]
    return items[:8]


class QuizEvaluationAgent:
    """Structural quality sweep applied to every generated assessment."""

    @staticmethod
    def audit_assessment(quiz_data: dict) -> dict:
        """Normalises, deduplicates and validates a generated assessment payload.

        The payload is mutated in place and returned so the caller can keep the
        existing call signature.
        """
        if not isinstance(quiz_data, dict):
            return {"quiz_title": "Generated Assessment", "questions": []}

        raw_questions = quiz_data.get("questions")
        if not isinstance(raw_questions, list):
            raw_questions = []

        cleaned: list[dict[str, Any]] = []
        seen_signatures: set[str] = set()

        for index, item in enumerate(raw_questions, start=1):
            normalized = QuizEvaluationAgent._normalize_question(item, index)
            if normalized is None:
                continue

            signature = QuizEvaluationAgent._signature(normalized)
            if signature in seen_signatures:
                continue
            seen_signatures.add(signature)
            cleaned.append(normalized)

        quiz_data["questions"] = cleaned
        quiz_data.setdefault("quiz_title", "Generated Assessment")
        quiz_data["question_count"] = len(cleaned)
        return quiz_data

    # -- Internals --------------------------------------------------------
    @staticmethod
    def _signature(question: dict[str, Any]) -> str:
        """Normalised question fingerprint used to drop near-duplicate items."""
        return normalize_answer_text(
            f"{question.get('question', '')} {question.get('scenario', '')} {question.get('case_description', '')}"
        )[:220]

    @staticmethod
    def _normalize_question(item: Any, index: int) -> dict[str, Any] | None:
        if not isinstance(item, dict):
            return None

        try:
            question_type = QuestionType(str(item.get("type") or QuestionType.SHORT_ANSWER).strip().lower())
        except ValueError:
            question_type = QuestionType.SHORT_ANSWER

        raw_text = str(item.get("question") or "").strip()
        scenario = _first_text(item.get("scenario"), item.get("case_description"))
        combined = raw_text if raw_text else scenario
        if len(combined) < MIN_QUESTION_CHARS:
            return None

        correct_answer = str(item.get("correct_answer") or "").strip()
        options = normalize_options(item.get("options") or [])

        if question_type is QuestionType.TRUE_FALSE:
            options = _force_true_false_options(options)
            canonical = _normalize_boolean_text(correct_answer) or _normalize_boolean_text(
                next((opt.text for opt in options if opt.is_correct), "")
            )
            if canonical:
                correct_answer = canonical

        if question_type in CHOICE_TYPES:
            options = _trim_options(options)
            if len(options) < MIN_OPTIONS:
                return None
            if not correct_answer:
                correct_answer = options[0].text
            correct_option_id = mark_correct_option(options, correct_answer)
        else:
            options = []
            correct_option_id = None

        if not correct_answer:
            return None

        explanation = str(item.get("explanation") or "").strip()
        if len(explanation) < MIN_EXPLANATION_CHARS:
            explanation = (
                f"The correct answer is {correct_answer}. This item is grounded in the "
                "retrieved source material for the selected topic."
            )

        try:
            difficulty = Difficulty(str(item.get("difficulty") or Difficulty.MEDIUM).strip().lower())
        except ValueError:
            difficulty = Difficulty.MEDIUM

        case_description = _first_text(item.get("case_description"))
        if question_type is QuestionType.CASE_STUDY and not case_description:
            case_description = scenario or ""

        return {
            "id": index,
            "type": question_type.value,
            "question": raw_text or scenario,
            "options": [option.model_dump(mode="json") for option in options],
            "correct_answer": correct_answer,
            "correct_option_id": correct_option_id,
            "explanation": explanation[:2000],
            "difficulty": difficulty.value,
            "topic": str(item.get("topic") or "").strip()[:160],
            "scenario": scenario if question_type in SCENARIO_TYPES else None,
            "case_description": case_description if question_type is QuestionType.CASE_STUDY else None,
            "case_id": _first_text(item.get("case_id")) if question_type is QuestionType.CASE_STUDY else None,
            "context": _first_text(item.get("context")),
            "marking_criteria": _normalize_marking_criteria(item.get("marking_criteria")),
            "hint": _first_text(item.get("hint")),
            "source_reference": _first_text(item.get("source_reference")),
            "points": _safe_points(item.get("points")),
        }


def _first_text(*values: Any) -> str | None:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _safe_points(value: Any) -> float:
    try:
        points = float(value)
    except (TypeError, ValueError):
        return 1.0
    if points <= 0 or points > 100:
        return 1.0
    return round(points, 2)


def _trim_options(options: list[Option]) -> list[Option]:
    """Drops duplicate option texts and caps the list at a sane length."""
    seen: set[str] = set()
    unique: list[Option] = []
    for option in options:
        key = normalize_answer_text(option.text)
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(option)
    return unique[:MAX_OPTIONS]


def _force_true_false_options(options: list[Option]) -> list[Option]:
    """Guarantees a canonical True/False option pair regardless of what arrived."""
    text_by_label = {option.id.strip().lower(): option.text.strip() for option in options}
    true_text = next((text for label, text in text_by_label.items() if label in ("a", "true", "t", "yes")), "True")
    false_text = next((text for label, text in text_by_label.items() if label in ("b", "false", "f", "no")), "False")

    return [
        Option(id="A", text=_normalize_boolean_text(true_text) or "True"),
        Option(id="B", text=_normalize_boolean_text(false_text) or "False"),
    ]


__all__ = ["QuizEvaluationAgent"]