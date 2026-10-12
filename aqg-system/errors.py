"""Typed error hierarchy for the AQG platform.

Every error carries an HTTP status code and a message that is safe to surface
end-users. Technical details (stack traces, upstream payloads) are logged on the
server and never returned to the browser.
"""

from __future__ import annotations


class AQGError(Exception):
    """Base class for all user-facing platform errors."""

    status_code: int = 500
    error_code: str = "internal_error"
    default_message: str = "Something went wrong while processing your request."

    def __init__(self, message: str | None = None, *, detail: str | None = None) -> None:
        self.message = message or self.default_message
        # `detail` is developer-only context; it is logged, never serialised.
        self.detail = detail
        super().__init__(self.message)

    def to_payload(self) -> dict[str, str]:
        return {"error": self.error_code, "detail": self.message}


class DocumentError(AQGError):
    """Base class for upload and document-processing failures."""

    status_code = 400
    error_code = "document_error"
    default_message = "We could not read that document."


class UnsupportedFileTypeError(DocumentError):
    status_code = 400
    error_code = "unsupported_file_type"
    default_message = "That file type is not supported. Please upload a PDF or TXT document."


class FileTooLargeError(DocumentError):
    status_code = 413
    error_code = "file_too_large"
    default_message = "The selected file is larger than the maximum upload size."


class EmptyDocumentError(DocumentError):
    status_code = 400
    error_code = "empty_document"
    default_message = (
        "We could not find readable text in that document. "
        "Scanned or image-only PDFs need OCR before they can be processed."
    )


class DocumentParseError(DocumentError):
    status_code = 400
    error_code = "document_parse_failed"
    default_message = "We could not process that document. Please try another file."


class ValidationError(AQGError):
    """Request-level validation failures."""

    status_code = 400
    error_code = "validation_error"
    default_message = "Please check the values you entered and try again."


class InvalidQuestionCountError(ValidationError):
    error_code = "invalid_question_count"
    default_message = "The requested number of questions is outside the supported range."


class InvalidQuestionTypeError(ValidationError):
    error_code = "invalid_question_type"
    default_message = "That question type is not supported."


class GenerationError(AQGError):
    """Upstream AI generation failures."""

    status_code = 502
    error_code = "generation_failed"
    default_message = "We could not generate the assessment right now. Please try again."


class InvalidAIResponseError(GenerationError):
    status_code = 502
    error_code = "invalid_ai_response"
    default_message = "The AI returned an unexpected response. Please try generating again."


class DatabaseError(AQGError):
    status_code = 500
    error_code = "database_error"
    default_message = "We could not reach the study history database."


class NotFoundError(AQGError):
    status_code = 404
    error_code = "not_found"
    default_message = "We could not find that record."


class QuizNotFoundError(NotFoundError):
    error_code = "quiz_not_found"
    default_message = "This assessment could not be found in your history."


class DocumentNotFoundError(NotFoundError):
    error_code = "document_not_found"
    default_message = "This document could not be found."


class StudyMaterialNotFoundError(NotFoundError):
    error_code = "study_material_not_found"
    default_message = "This study material could not be found."


class RateLimitError(AQGError):
    status_code = 429
    error_code = "rate_limited"
    default_message = "Too many requests. Please wait a moment and try again."


class AssessmentError(AQGError):
    status_code = 400
    error_code = "assessment_error"
    default_message = "We could not process this assessment submission."


class AttemptNotSubmittedError(AQGError):
    """Raised when the answer key is requested without a matching attempt.

    This is what stops the key being read straight out of the network tab before
    an assessment has been submitted.
    """

    status_code = 403
    error_code = "answer_key_locked"
    default_message = "The answer key stays locked until this assessment has been submitted."