from fastapi import APIRouter
from app.api.v1.endpoints import auth, projects, documents

# ============================================================
# Main API v1 Router
# ============================================================

api_router = APIRouter()

# Include auth routes at /auth
api_router.include_router(
    auth.router,
    prefix="/auth"
)

# Include project routes at /projects
api_router.include_router(
    projects.router,
    prefix="/projects"
)

# Include document routes at /projects/{project_id}/documents
# Note: Documents are nested under projects
api_router.include_router(
    documents.router,
    prefix="/projects/{project_id}/documents"
)

# Future routes will be added here:
# api_router.include_router(documents.router, prefix="/documents")
# api_router.include_router(conversations.router, prefix="/conversations")
# api_router.include_router(quizzes.router, prefix="/quizzes")