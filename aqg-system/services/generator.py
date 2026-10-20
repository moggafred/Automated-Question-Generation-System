"""AI generation layer for assessments and study materials.

Prompts are built per question type so the model is told exactly what a scenario
item, a case study or an application item must look like. Every prompt carries the
same three hard rules: use only the retrieved context, never invent facts that
contradict it, and return JSON matching the requested schema.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Callable, Iterable

from langchain_core.output_parsers import JsonOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

from config.settings import settings
from errors import GenerationError, InvalidAIResponseError
from models.question import (
    CHOICE_TYPES,
    DIFFICULTY_LABELS,
    SCENARIO_TYPES,
    Difficulty,
    QuestionType,
)
from models.study import StudyMaterialType

logger = logging.getLogger("aqg.generator")

JSON_BLOCK_PATTERN = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)

GROUNDING_RULES = (
    "Ground every statement in the CONTEXT provided. Never introduce facts that "
    "contradict or go beyond it. If the context does not contain enough material "
    "for the requested number of questions, produce fewer rather than inventing content."
)

QUALITY_RULES = (
    "Write academically meaningful items that test understanding, not trivia.\n"
    "Make each question distinct: no two questions may probe the same point.\n"
    "Match the requested difficulty exactly.\n"
    "Do not write meta-phrasing such as 'According to the passage' or 'Based on the text'. "
    "Ask the question directly.\n"
    "Return only JSON matching the required schema, with no commentary outside it."
)


# ==========================================================================
# Schemas handed to the LLM as format instructions
# ==========================================================================
class QuestionSchema(BaseModel):
    """Loose question contract requested from the model.

    Kept intentionally permissive: option lists arrive as plain strings and are
    converted into :class:`~models.question.Option` objects by the evaluator, so
    the model is never asked to compute labels or correctness flags.
    """

    id: int = Field(..., description="Sequential identifier for the question.")
    type: str = Field(..., description="Type of question generated.")
    question: str = Field(..., description="The specific question text derived from the source content.")
    options: list[str] = Field(
        default_factory=list,
        description="Exactly 4 items for multiple-choice, 2 for true-false. Empty for all open types."
    )
    correct_answer: str = Field(..., description="The correct answer option text, or the expected answer.")
    explanation: str = Field(..., description="Why the correct answer is right and why the distractors fail.")
    difficulty: str = Field("medium", description="easy, medium or hard.")
    topic: str = Field("", description="Sub-topic this question assesses.")
    scenario: str = Field("", description="A realistic situation, required for scenario-based questions.")
    case_description: str = Field("", description="Full case narrative, required for case-study questions.")
    case_id: str = Field("", description="Shared id grouping sub-questions of one case study.")
    context: str = Field("", description="Problem framing shown alongside the question.")
    marking_criteria: list[str] = Field(
        default_factory=list,
        description="Bullets describing what a strong answer must include (extended responses)."
    )
    hint: str = Field("", description="Optional short nudge shown before submission.")
    source_reference: str = Field(
        "", description="Short quote or section pointer from the context that supports this item."
    )
    points: float = Field(1.0, description="Marks available for this item.")


class AssessmentSchema(BaseModel):
    """The assessment contract requested from the model."""

    quiz_title: str = Field(..., description="A concise title reflecting the subject matter.")
    summary: str = Field("", description="One or two sentences orienting the learner.")
    questions: list[QuestionSchema] = Field(..., description="The generated questions.")


class SummarySchema(BaseModel):
    title: str = Field(..., description="Heading for the summary.")
    overview: str = Field(..., description="A concise explanation of the document.")
    points: list[str] = Field(default_factory=list, description="Ordered bullet points of essential content.")
    learning_outcomes: list[str] = Field(
        default_factory=list, description="What the learner should be able to do afterwards."
    )


class KeyConceptSchema(BaseModel):
    title: str = Field(..., description="Name of the concept.")
    description: str = Field(..., description="What the concept means.")
    why_it_matters: str = Field("", description="Practical relevance.")


class DefinitionSchema(BaseModel):
    term: str = Field(..., description="The defined term.")
    definition: str = Field(..., description="Its meaning according to the document.")
    example: str = Field("", description="A concrete example when the document provides one.")


class FlashcardSchema(BaseModel):
    front: str = Field(..., description="A focused prompt side of the card.")
    back: str = Field(..., description="The concise answer side of the card.")
    hint: str = Field("", description="Optional memory aid.")
    topic: str = Field("", description="Concept the card reinforces.")


class RevisionNoteSchema(BaseModel):
    heading: str = Field(..., description="Note heading.")
    body: str = Field(..., description="Note content.")
    key_takeaway: str = Field("", description="The single most important takeaway.")


class StudyMaterialSchema(BaseModel):
    summary: SummarySchema | None = Field(None, description="Concise document summary.")
    key_concepts: list[KeyConceptSchema] = Field(default_factory=list, description="Key concepts list.")
    definitions: list[DefinitionSchema] = Field(default_factory=list, description="Important definitions.")
    flashcards: list[FlashcardSchema] = Field(default_factory=list, description="Revision flashcards.")
    revision_notes: list[RevisionNoteSchema] = Field(default_factory=list, description="Revision notes.")


# ==========================================================================
# Per-type prompt guidance
# ==========================================================================
TYPE_GUIDANCE: dict[str, str] = {
    QuestionType.MULTIPLE_CHOICE.value: (
        "Generate MULTIPLE-CHOICE questions.\n"
        "- Provide exactly 4 options.\n"
        "- Exactly one option is correct and must appear verbatim in options.\n"
        "- Distractors must be plausible and map to real conceptual errors a student would make, "
        "not filler or joke answers.\n"
        "- Set options and correct_answer to short, parallel phrases."
    ),
    QuestionType.TRUE_FALSE.value: (
        "Generate TRUE/FALSE questions.\n"
        "- options must be exactly ['True', 'False'] and correct_answer must be one of them.\n"
        "- Roughly half the statements should be false, and each false statement must be false "
        "for a reason a learner can reason about from the context, not because of a trivial negation."
    ),
    QuestionType.SHORT_ANSWER.value: (
        "Generate SHORT-ANSWER questions.\n"
        "- options must be an empty array.\n"
        "- Each answer must be a specific term, value or short phrase that the document states clearly.\n"
        "- Keep correct_answer under 15 words."
    ),
    QuestionType.FILL_IN_THE_BLANK.value: (
        "Generate FILL-IN-THE-BLANK questions.\n"
        "- options must be an empty array.\n"
        "- Replace exactly the critical term, value or metric in the question with '_______'.\n"
        "- correct_answer is the exact missing text taken from the document."
    ),
    QuestionType.ESSAY.value: (
        "Generate ESSAY questions.\n"
        "- options must be an empty array.\n"
        "- Each question must ask for an argument, comparison or critical discussion rather than recall.\n"
        "- Fill marking_criteria with 3-4 bullets describing what a strong answer must contain.\n"
        "- correct_answer is a model answer of 2-4 sentences."
    ),
    QuestionType.SCENARIO.value: (
        "Generate SCENARIO-BASED questions that test APPLICATION of the document's concepts.\n"
        "- Write a realistic, concrete situation of 2-4 sentences in the 'scenario' field. Use real-sounding "
        "organisations, roles, datasets or constraints, but keep every fact consistent with the CONTEXT.\n"
        "- The 'question' field asks which concept, method or decision applies, and why. Never repeat the scenario in it.\n"
        "- For multiple-choice items give 4 options and set correct_answer to the correct option text.\n"
        "- For open items leave options empty and give a concise expected answer.\n"
        "- The scenario must be plausible from the context alone; do not invent named studies, statistics or results."
    ),
    QuestionType.CASE_STUDY.value: (
        "Generate CASE-STUDY questions built around a single extended situation.\n"
        "- Write a detailed case narrative (4-8 sentences) in 'case_description' describing an organisation, "
        "its data or process, the constraints it faces and why that situation matters.\n"
        "- Use 'context' for the specific problem the learner must analyse.\n"
        "- Group the questions of one case with the same 'case_id' so the platform can present them together.\n"
        "- Each question must require analysis or decision making, not definition recall.\n"
        "- options must be an empty array; use marking_criteria bullets and a model answer instead."
    ),
    QuestionType.APPLICATION.value: (
        "Generate APPLICATION / PROBLEM-SOLVING questions.\n"
        "- Describe a concrete task, dataset or system in the question itself, for example "
        "'An algorithm examines every element in a list of n items. What is its time complexity "
        "and what does that imply as the input grows?'\n"
        "- The learner must reason, interpret, compute or decide; do not ask for a definition.\n"
        "- options must be an empty array unless the application is best served by fixed choices.\n"
        "- Include 2-4 marking_criteria bullets and a worked model answer in correct_answer."
    ),
    "mixed": (
        "Generate a MIXED assessment covering several formats.\n"
        "- Include at least two of: multiple-choice, true-false, short-answer, scenario, application.\n"
        "- Set each item's 'type' to its actual format and follow that format's option rules.\n"
        "- Keep a balanced spread and avoid asking about the same point twice."
    ),
}

DIFFICULTY_GUIDANCE: dict[str, str] = {
    Difficulty.EASY.value: (
        "DIFFICULTY: easy. Recall and recognition of clearly stated facts, terms and single steps. "
        "One correct option must be unmistakable."
    ),
    Difficulty.MEDIUM.value: (
        "DIFFICULTY: medium. Understanding and application of stated concepts, requiring one inference "
        "beyond what is literally written. Distractors must be defensible but wrong."
    ),
    Difficulty.HARD.value: (
        "DIFFICULTY: hard. Multi-step reasoning, interpretation of trade-offs, or application to an "
        "unfamiliar situation. Every item must be solvable from the context alone."
    ),
}


def build_quiz_instruction(
    *,
    question_type: str,
    quantity: int,
    difficulty: Difficulty,
    topic: str = "",
    custom_instructions: str = "",
) -> str:
    """Assembles the system instruction for an assessment generation request."""
    key = str(question_type or QuestionType.MULTIPLE_CHOICE.value).strip().lower()
    guidance = TYPE_GUIDANCE.get(key) or TYPE_GUIDANCE[QuestionType.MULTIPLE_CHOICE.value]

    lines = [
        "You are a senior academic assessor creating grounded evaluation content for an education platform.",
        guidance,
        DIFFICULTY_GUIDANCE.get(difficulty.value, DIFFICULTY_GUIDANCE[Difficulty.MEDIUM.value]),
        f"Produce exactly {quantity} questions, using the 'type' value '{key}' unless the format "
        "definition above allows a different, more suitable type.",
        f"Use difficulty '{difficulty.value}' for every item.",
    ]

    if topic.strip():
        lines.append(
            f"The learner asked for content focused on: '{topic.strip()}'. Prioritise context that "
            "relates to that focus while staying faithful to the CONTEXT."
        )
    if custom_instructions.strip():
        lines.append(
            "Additional instructions from the learner (honour them, but never at the cost of grounding "
            f"in the CONTEXT or of the requested format): {custom_instructions.strip()}"
        )

    lines.extend([GROUNDING_RULES, QUALITY_RULES])
    return "\n".join(f"{index}. {line}" for index, line in enumerate(lines, start=1))


def build_user_prompt(context: str, *, title_hint: str = "") -> str:
    """Wraps retrieved context in a clearly delimited block for the model."""
    hint = f"\nA suitable assessment title relates to: {title_hint}.\n" if title_hint else ""
    return (
        f"{hint}"
        "Use ONLY the CONTEXT below.\n"
        "--- START CONTEXT ---\n"
        f"{context}\n"
        "--- END CONTEXT ---"
    )


STUDY_TYPE_GUIDANCE: dict[str, str] = {
    StudyMaterialType.SUMMARY.value: (
        f"Produce a SUMMARY only. Write one overview paragraph of 3-5 sentences, then 4-7 bullet points "
        "covering the essential content, then 3-5 learning outcomes phrased as what the learner can do. "
        "Populate only the 'summary' field."
    ),
    StudyMaterialType.KEY_CONCEPTS.value: (
        f"Produce KEY CONCEPTS only. List the most important concepts (5-10) as objects with 'title', "
        "'description' (1-2 sentences grounded in the context) and 'why_it_matters'. Populate only the "
        "'key_concepts' field."
    ),
    StudyMaterialType.FLASHCARDS.value: (
        f"Produce FLASHCARDS only. Create 8-16 self-contained cards. Each 'front' is a focused prompt and "
        "each 'back' is a concise answer. Cards must work in isolation. Populate only the 'flashcards' field."
    ),
    StudyMaterialType.DEFINITIONS.value: (
        "Produce IMPORTANT DEFINITIONS only. List 6-12 terms the learner must memorise with 'term', "
        "'definition' and an 'example' where the context supports one. Populate only the 'definitions' field."
    ),
    StudyMaterialType.REVISION_NOTES.value: (
        "Produce REVISION NOTES only. Create 4-8 notes with 'heading', a concise 'body' and a single "
        "'key_takeaway'. Populate only the 'revision_notes' field."
    ),
    StudyMaterialType.ALL.value: (
        "Produce a COMPLETE STUDY PACK: populate 'summary', 'key_concepts', 'definitions', 'flashcards' "
        "and 'revision_notes' together, keeping every item faithful to the context."
    ),
}


# ==========================================================================
# Service
# ==========================================================================
class QuestionGeneratorService:
    """Thin, testable wrapper around the configured chat model."""

    def __init__(self, llm: ChatOpenAI | None = None):
        self.llm = llm if llm is not None else self._build_client()
        self.output_parser = JsonOutputParser(pydantic_object=AssessmentSchema)
        self.study_output_parser = JsonOutputParser(pydantic_object=StudyMaterialSchema)

    @staticmethod
    def _build_client() -> ChatOpenAI:
        """Constructs the chat client for the configured provider."""
        kwargs: dict[str, Any] = {
            "model": settings.LLM_MODEL,
            "openai_api_key": settings.OPENAI_API_KEY,
            "temperature": settings.LLM_TEMPERATURE,
            "timeout": settings.LLM_REQUEST_TIMEOUT,
            "max_retries": settings.LLM_MAX_RETRIES,
        }
        if settings.LLM_BASE_URL:
            kwargs["base_url"] = settings.LLM_BASE_URL

        if settings.LLM_PROVIDER == "local":
            kwargs = {
                "model": settings.LOCAL_LLM_MODEL,
                "base_url": settings.LOCAL_LLM_BASE_URL,
                "openai_api_key": "EMPTY",
                "temperature": settings.LLM_TEMPERATURE,
                "timeout": settings.LLM_REQUEST_TIMEOUT,
                "max_retries": settings.LLM_MAX_RETRIES,
            }

        try:
            return ChatOpenAI(**kwargs)
        except Exception as exc:  # noqa: BLE001 - surfaced as a friendly generation error
            raise GenerationError(
                "The AI provider is not configured correctly. Check your environment settings.",
                detail=f"client construction failed: {exc}",
            ) from exc

    # -- Assessment generation -------------------------------------------
    def generate_quiz(
        self,
        context_chunk: str,
        question_type: str,
        quantity: int,
        difficulty: str = Difficulty.MEDIUM.value,
        topic: str = "",
        custom_instructions: str = "",
    ) -> dict:
        """Generates a structured assessment grounded in the retrieved context.

        Kept backwards compatible: the first three positional arguments and the
        returned plain-dict shape are unchanged from the original service.
        """
        if not (context_chunk or "").strip():
            raise GenerationError("There was no source material to generate questions from.")

        resolved_difficulty = (
            difficulty if isinstance(difficulty, Difficulty) else Difficulty(str(difficulty or "medium").lower())
        )
        if isinstance(resolved_difficulty, str):
            try:
                resolved_difficulty = Difficulty(resolved_difficulty)
            except ValueError:
                resolved_difficulty = Difficulty.MEDIUM

        instruction = build_quiz_instruction(
            question_type=question_type,
            quantity=quantity,
            difficulty=resolved_difficulty,
            topic=topic,
            custom_instructions=custom_instructions,
        )

        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", instruction + "\n{format_instructions}"),
                ("user", build_user_prompt(context_chunk, title_hint=topic)),
            ]
        )

        chain = prompt | self.llm | self.output_parser
        return self._invoke(
            chain,
            {
                "format_instructions": self.output_parser.get_format_instructions(),
                "context": context_chunk,
                "topic": topic,
            },
            label="assessment",
        )

    # -- Study material generation ---------------------------------------
    def generate_study_material(
        self,
        context_chunk: str,
        material_type: str,
        topic: str = "",
    ) -> dict:
        """Generates a study resource bundle grounded in the retrieved context."""
        if not (context_chunk or "").strip():
            raise GenerationError("There was no source material to build study materials from.")

        resolved = StudyMaterialType.resolve(material_type) or StudyMaterialType.SUMMARY
        instruction = "\n".join(
            [
                "You are an expert learning-design specialist who turns source material into "
                "high-quality revision resources for students.",
                STUDY_TYPE_GUIDANCE[resolved.value],
                GROUNDING_RULES,
                "Use plain, accurate academic English. Avoid filler and avoid inventing details.",
                "Return only JSON matching the required schema.",
            ]
        )

        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", instruction + "\n{format_instructions}"),
                ("user", build_user_prompt(context_chunk, title_hint=topic)),
            ]
        )

        chain = prompt | self.llm | self.study_output_parser
        return self._invoke(
            chain,
            {
                "format_instructions": self.study_output_parser.get_format_instructions(),
                "context": context_chunk,
            },
            label="study material",
        )

    # -- Shared plumbing --------------------------------------------------
    def _invoke(self, chain: Any, payload: dict[str, Any], *, label: str) -> dict:
        """Runs a prompt chain and normalises every failure into a typed error."""
        try:
            result = chain.invoke(payload)
        except Exception as exc:  # noqa: BLE001 - provider errors are opaque by nature
            logger.exception("LLM %s generation failed: %s", label, exc)
            raise GenerationError(
                "We could not reach the AI provider while generating content. Please try again.",
                detail=f"{label} chain invocation failed: {exc}",
            ) from exc

        return self._coerce_payload(result, label=label)

    @staticmethod
    def _coerce_payload(result: Any, *, label: str) -> dict:
        """Ensures the chain output is a usable dictionary before validation."""
        if isinstance(result, dict):
            return result

        if isinstance(result, str):
            return QuestionGeneratorService._parse_json_text(result, label=label)

        dump = getattr(result, "model_dump", None)
        if callable(dump):
            return dump(mode="json")

        raise InvalidAIResponseError(
            "The AI returned an unexpected response. Please try generating again.",
            detail=f"{label} produced unsupported type {type(result)!r}",
        )

    @staticmethod
    def _parse_json_text(raw: str, *, label: str) -> dict:
        """Recovers a JSON object from a model response that ignored the schema."""
        candidate = raw.strip()
        if not candidate:
            raise InvalidAIResponseError("The AI returned an empty response.", detail=f"{label}: empty string")

        if candidate.startswith("```"):
            match = JSON_BLOCK_PATTERN.search(candidate)
            candidate = (match.group(1) if match else candidate).strip()

        if not candidate.startswith("{"):
            start, end = candidate.find("{"), candidate.rfind("}")
            if start == -1 or end <= start:
                raise InvalidAIResponseError(
                    "The AI returned an unexpected response. Please try generating again.",
                    detail=f"{label}: no JSON object found in {candidate[:200]!r}",
                )
            candidate = candidate[start : end + 1]

        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError as exc:
            raise InvalidAIResponseError(
                "The AI returned an unexpected response. Please try generating again.",
                detail=f"{label}: malformed JSON ({exc})",
            ) from exc

        if not isinstance(parsed, dict):
            raise InvalidAIResponseError(
                "The AI returned an unexpected response. Please try generating again.",
                detail=f"{label}: JSON root was {type(parsed)!r}",
            )
        return parsed


def default_retrieval_query(topic: str = "") -> str:
    """The RAG query used when the learner does not supply a topic."""
    return topic.strip() if topic and topic.strip() else "key concepts and main summaries"


_shared_generator: QuestionGeneratorService | None = None


def get_generator_service() -> QuestionGeneratorService:
    """Returns the process-wide generator so the LLM client is built once."""
    global _shared_generator
    if _shared_generator is None:
        _shared_generator = QuestionGeneratorService()
    return _shared_generator


def sanitize_for_context(chunks: Iterable[str], max_chars: int) -> str:
    """Joins retrieved chunks, truncating cleanly at the configured ceiling."""
    joined = "\n\n".join(chunk.strip() for chunk in chunks if chunk and chunk.strip())
    if len(joined) <= max_chars:
        return joined
    return joined[:max_chars].rsplit(" ", 1)[0]


__all__ = [
    "AssessmentSchema",
    "DIFFICULTY_LABELS",
    "CHOICE_TYPES",
    "QuestionGeneratorService",
    "QuestionSchema",
    "SCENARIO_TYPES",
    "StudyMaterialSchema",
    "build_quiz_instruction",
    "build_user_prompt",
    "default_retrieval_query",
    "get_generator_service",
    "sanitize_for_context",
]