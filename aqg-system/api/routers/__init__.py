"""API router modules grouped by domain.

Each module owns one domain and is assembled by :func:`api.router.register_routers`.
"""

from api.routers.assessments import router as assessments_router
from api.routers.documents import router as documents_router
from api.routers.generation import router as generation_router
from api.routers.history import router as history_router
from api.routers.quiz import router as quiz_router
from api.routers.study import router as study_router
from api.routers.system import router as system_router

__all__ = [
    "assessments_router",
    "documents_router",
    "generation_router",
    "history_router",
    "quiz_router",
    "study_router",
    "system_router",
]