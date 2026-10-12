"""Pydantic schema package for the AQG educational assessment platform.

Sub-modules
-----------
* :mod:`models.question` -- question, option and type vocabulary
* :mod:`models.quiz`    -- assessment container and case-study grouping
* :mod:`models.study`   -- study material resources
* :mod:`models.assessment` -- submission and grading schemas
* :mod:`models.document`   -- uploaded document records
"""

from models.assessment import (
    AssessmentResult,
    AssessmentSubmission,
    QuestionReview,
    SubmittedAnswer,
    performance_band,
)
from models.document import DocumentSummary, ParsedDocument, humanize_bytes, validate_extension
from models.question import (
    DIFFICULTY_LABELS,
    QUESTION_TYPE_LABELS,
    Difficulty,
    Option,
    Question,
    QuestionType,
    normalize_answer_text,
    normalize_options,
    resolve_difficulty,
    resolve_question_type,
)
from models.quiz import Assessment, CaseStudy, Quiz, build_metadata, group_case_studies, utc_now_iso
from models.study import (
    STUDY_MATERIAL_LABELS,
    Definition,
    Flashcard,
    KeyConcept,
    RevisionNote,
    StudyMaterial,
    StudyMaterialType,
    Summary,
)

__all__ = [
    "Assessment",
    "AssessmentResult",
    "AssessmentSubmission",
    "CaseStudy",
    "DIFFICULTY_LABELS",
    "Definition",
    "Difficulty",
    "DocumentSummary",
    "Flashcard",
    "KeyConcept",
    "Option",
    "ParsedDocument",
    "QUESTION_TYPE_LABELS",
    "Question",
    "QuestionReview",
    "QuestionType",
    "Quiz",
    "RevisionNote",
    "STUDY_MATERIAL_LABELS",
    "SubmittedAnswer",
    "StudyMaterial",
    "StudyMaterialType",
    "Summary",
    "build_metadata",
    "group_case_studies",
    "humanize_bytes",
    "normalize_answer_text",
    "normalize_options",
    "performance_band",
    "resolve_difficulty",
    "resolve_question_type",
    "utc_now_iso",
    "validate_extension",
]