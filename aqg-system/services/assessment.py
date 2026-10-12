"""Automatic assessment: grading learner submissions and persisting the outcome.

Grading strategy per question type
----------------------------------
``multiple-choice`` / ``true-false`` / ``scenario`` (with options)
    Deterministic. The selected option label or text is matched against the
    authoritative answer, so scoring is exact and reproducible.

Open-response types (``short-answer``, ``fill-in-the-blank``, ``application``)
    Deterministic partial credit. The response is compared against the model
    answer on normalised content-word coverage, so a learner who names every key
    idea earns full marks even with different phrasing.

``essay`` / ``case-study``
    Structural partial credit. Content-word coverage is combined with how many of
    the supplied ``marking_criteria`` bullets are addressed. The result is always
    reported as provisional in the response so it is never presented as a human
    mark.
"""

from __future__ import annotations

import logging
import re
import uuid
from typing import Any, Iterable

from models.assessment import (
    AssessmentResult,
    AssessmentSubmission,
    QuestionReview,
    SubmittedAnswer,
    performance_band,
)
from models.question import (
    CHOICE_TYPES,
    LONG_FORM_TYPES,
    Question,
    QuestionType,
    normalize_answer_text,
)
from models.quiz import Assessment

logger = logging.getLogger("aqg.assessment")

MIN_WORD_LENGTH = 3

#: Additional words that carry no assessment signal in learner responses.
_ANSWER_STOPWORDS = frozenset(
    """
    a an the and or but if then than that this these those there here is are was were be been being am
    of in on at to for from by with without about into over under between among during per via as
    its it's their his her our your they them we you i he she it not no nor so such very can could
    would should may might must will shall do does did done have has had having what which who whom
    when where why how also too more most other another each every any some all both few many much
    """.split()
)

_WORD_PATTERN = re.compile(r"[a-z0-9]+")

#: Coverage at or above which a short-answer response earns full marks.
SHORT_ANSWER_FULL_CREDIT = 0.85
#: Coverage below which a short-answer response earns no marks.
SHORT_ANSWER_MINIMUM = 0.34

#: Weighted blend of coverage and criteria coverage for extended responses.
LONG_FORM_COVERAGE_WEIGHT = 0.6
LONG_FORM_CRITERIA_WEIGHT = 0.4
LONG_FORM_MINIMUM = 0.25


def content_tokens(text: str) -> set[str]:
    """Extracts meaningful, normalised content words from a free-text response."""
    return {
        token
        for token in _WORD_PATTERN.findall((text or "").lower())
        if len(token) >= MIN_WORD_LENGTH and token not in _ANSWER_STOPWORDS
    }


def _stem_variants(token: str) -> set[str]:
    """Crude morphological variants so 'clustering' matches 'cluster'."""
    variants = {token}
    for suffix, replacement in (("ing", ""), ("edly", ""), ("ed", ""), ("es", ""), ("s", ""), ("tion", "te")):
        if token.endswith(suffix) and len(token) > len(suffix) + 2:
            variants.add(token[: -len(suffix)] + replacement)
    return variants


def _expanded(tokens: set[str]) -> set[str]:
    expanded: set[str] = set()
    for token in tokens:
        expanded.update(_stem_variants(token))
    return expanded


def coverage_ratio(response: str, reference: str) -> float:
    """Fraction of the reference answer's content words present in the response."""
    reference_tokens = content_tokens(reference)
    if not reference_tokens:
        return 0.0

    response_tokens = _expanded(content_tokens(response))
    if not response_tokens:
        return 0.0

    hits = sum(1 for token in reference_tokens if _expanded({token}) & response_tokens)
    return round(hits / len(reference_tokens), 4)


def _criteria_hits(response: str, criteria: Iterable[str]) -> tuple[int, int]:
    response_tokens = _expanded(content_tokens(response))
    total = 0
    hits = 0
    for criterion in criteria:
        if not criterion:
            continue
        total += 1
        criterion_tokens = _expanded(content_tokens(criterion))
        if not criterion_tokens:
            continue
        if len(criterion_tokens & response_tokens) / len(criterion_tokens) >= 0.6:
            hits += 1
    return hits, total


class AssessmentGrader:
    """Grades one submission against a stored assessment."""

    def __init__(self, assessment: Assessment, submission: AssessmentSubmission):
        self.assessment = assessment
        self.submission = submission
        self.answers: dict[int, SubmittedAnswer] = submission.answer_map

    # -- Public API -------------------------------------------------------
    def grade(self) -> AssessmentResult:
        reviews: list[QuestionReview] = []
        type_totals: dict[str, list[float]] = {}
        earned = 0.0
        available = 0.0
        correct = 0
        incorrect = 0
        partial = 0
        unanswered = 0
        attempted = 0

        for question in self.assessment.questions:
            submitted = self.answers.get(question.id)
            awarded, is_correct, is_partial, was_attempted = self._grade_question(question, submitted)

            available += float(question.points)
            earned += awarded

            if is_correct:
                correct += 1
            elif is_partial:
                partial += 1
                incorrect += 1
            else:
                incorrect += 1

            if submitted is None or submitted.is_blank:
                unanswered += 1
            else:
                attempted += 1

            question_type = str(question.type)
            bucket = type_totals.setdefault(question_type, [0.0, 0.0])
            bucket[0] += awarded
            bucket[1] += float(question.points)

            reviews.append(self._build_review(question, submitted, awarded, is_correct, is_partial))

        percentage = round((earned / available) * 100, 1) if available > 0 else 0.0
        band, _ = performance_band(percentage)
        accuracy = round((correct / attempted) * 100, 1) if attempted > 0 else 0.0

        return AssessmentResult(
            attempt_id=str(uuid.uuid4()),
            quiz_id="",
            quiz_title=self.assessment.quiz_title,
            topic=self.assessment.topic,
            performance_band=band,
            score=round(earned, 2),
            total_score=round(available, 2),
            percentage=percentage,
            correct_answers=correct,
            incorrect_answers=incorrect,
            unanswered=unanswered,
            partial_answers=partial,
            total_questions=len(self.assessment.questions),
            attempted=attempted,
            accuracy=accuracy,
            time_spent_seconds=self.submission.time_spent_seconds,
            breakdown={
                qtype: {
                    "score": round(totals[0], 2),
                    "total": round(totals[1], 2),
                    "percentage": round((totals[0] / totals[1]) * 100, 1) if totals[1] else 0.0,
                }
                for qtype, totals in type_totals.items()
            },
            review=reviews,
        )

    # -- Internals --------------------------------------------------------
    def _grade_question(
        self,
        question: Question,
        submitted: SubmittedAnswer | None,
    ) -> tuple[float, bool, bool, bool]:
        """Returns (points_awarded, correct, partial, attempted)."""
        points = float(question.points)
        response = submitted.answer if submitted else ""
        was_attempted = bool(submitted and not submitted.is_blank)

        if not was_attempted:
            return 0.0, False, False, False

        question_type = QuestionType(question.type)

        if question_type in CHOICE_TYPES and question.options:
            if self._matches_choice(question, response):
                return points, True, False, True
            return 0.0, False, False, True

        ratio = coverage_ratio(response, question.correct_answer)

        if question_type in LONG_FORM_TYPES:
            criteria_hits, criteria_total = _criteria_hits(response, question.marking_criteria)
            criteria_ratio = criteria_hits / criteria_total if criteria_total else 0.0
            blended = LONG_FORM_COVERAGE_WEIGHT * ratio + LONG_FORM_CRITERIA_WEIGHT * criteria_ratio
            if blended >= 0.8:
                return points, True, False, True
            if blended >= LONG_FORM_MINIMUM:
                return round(points * blended, 2), False, True, True
            return 0.0, False, False, True

        if ratio >= SHORT_ANSWER_FULL_CREDIT:
            return points, True, False, True
        if ratio >= SHORT_ANSWER_MINIMUM:
            return round(points * ratio, 2), False, True, True
        return 0.0, False, False, True

    @staticmethod
    def _matches_choice(question: Question, response: str) -> bool:
        """Matches a learner response against the correct choice by label or text."""
        candidate = normalize_answer_text(response)
        if not candidate:
            return False

        correct_option_id = question.resolve_correct_option_id()
        if correct_option_id and candidate == normalize_answer_text(correct_option_id):
            return True
        if correct_option_id and candidate == normalize_answer_text(correct_option_id.lower()):
            return True

        return candidate == normalize_answer_text(question.correct_answer)

    @staticmethod
    def _build_review(
        question: Question,
        submitted: SubmittedAnswer | None,
        awarded: float,
        is_correct: bool,
        is_partial: bool,
    ) -> QuestionReview:
        auto_graded = QuestionType(question.type) not in LONG_FORM_TYPES
        return QuestionReview(
            question_id=question.id,
            question=question.question,
            type=str(question.type),
            difficulty=str(question.difficulty),
            topic=question.topic,
            scenario=question.scenario,
            your_answer=(submitted.answer if submitted else "") or "",
            correct_answer=question.correct_answer,
            explanation=question.explanation,
            marking_criteria=list(question.marking_criteria),
            correct=is_correct,
            partial=is_partial,
            points_awarded=round(awarded, 2),
            points_available=float(question.points),
            source_reference=question.source_reference,
            auto_graded=auto_graded,
        )


def grade_submission(
    assessment_payload: Any,
    submission: AssessmentSubmission,
    *,
    quiz_id: str,
    quiz_topic: str = "",
) -> tuple[AssessmentResult, list[dict[str, Any]]]:
    """Grades a submission and returns the result plus a serialisable answer log."""
    assessment = Assessment.from_payload(assessment_payload)
    assessment.topic = assessment.topic or quiz_topic

    grader = AssessmentGrader(assessment, submission)
    result = grader.grade()
    result.quiz_id = quiz_id

    answer_log = [
        {
            "question_id": answer.question_id,
            "answer": answer.answer,
            "time_spent_seconds": answer.time_spent_seconds,
        }
        for answer in submission.answers
    ]

    return result, answer_log


async def grade_and_persist(
    assessment_payload: Any,
    submission: AssessmentSubmission,
    *,
    quiz_id: str,
    quiz_topic: str = "",
) -> AssessmentResult:
    """Grades a submission and stores the attempt so it appears in history."""
    from services.database import async_save_assessment_attempt

    result, answer_log = grade_submission(
        assessment_payload,
        submission,
        quiz_id=quiz_id,
        quiz_topic=quiz_topic,
    )

    await async_save_assessment_attempt(
        attempt_id=result.attempt_id,
        quiz_id=result.quiz_id,
        score=result.score,
        total_score=result.total_score,
        percentage=result.percentage,
        correct_answers=result.correct_answers,
        incorrect_answers=result.incorrect_answers,
        unanswered=result.unanswered,
        partial_answers=result.partial_answers,
        total_questions=result.total_questions,
        attempted=result.attempted,
        answers=answer_log,
        review=[review.model_dump(mode="json") for review in result.review],
        topic=result.topic,
        time_spent_seconds=result.time_spent_seconds,
    )

    logger.info("Graded attempt %s for quiz %s (%.1f%%)", result.attempt_id, quiz_id, result.percentage)
    return result


__all__ = [
    "AssessmentGrader",
    "content_tokens",
    "coverage_ratio",
    "grade_and_persist",
    "grade_submission",
]