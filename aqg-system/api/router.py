"""Router aggregation for the API layer.

Kept in its own module so importing a single router never pulls in the whole
application, which keeps tests and tooling fast and avoids import cycles.
"""

from __future__ import annotations

from fastapi import FastAPI

from api.routers.assessments import router as assessments_router
from api.routers.auth import router as auth_router
from api.routers.documents import router as documents_router
from api.routers.generation import router as generation_router
from api.routers.history import router as history_router
from api.routers.quiz import router as quiz_router
from api.routers.study import router as study_router
from api.routers.system import router as system_router

#: Registration order determines the OpenAPI tag order.
ALL_ROUTERS = (
    system_router,
    auth_router,
    generation_router,
    study_router,
    quiz_router,
    history_router,
    assessments_router,
    documents_router,
)


def register_routers(app: FastAPI) -> None:
    """Mounts every API router onto the application."""
    for router in ALL_ROUTERS:
        app.include_router(router)


__all__ = ["ALL_ROUTERS", "register_routers"]