from fastapi import APIRouter
from app.api.v1.endpoints import auth, projects, documents, conversations, sharing, quizzes, topics, knowledge, notifications

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

# Conversation/Chat routes
api_router.include_router(
    conversations.router,
    prefix="/conversations"
)

# Sharing routes
api_router.include_router(
    sharing.router,
    prefix=""  # Routes define their own prefixes (/shares, /shared, etc.)
)


api_router.include_router(
    quizzes.router,
    prefix=""  # Routes define their own prefixes (/projects/{id}/quizzes, /quizzes/{id})
)

api_router.include_router(
    topics.router,
    prefix=""  # Routes define their own prefixes (/projects/{id}/topics)
)

api_router.include_router(
    knowledge.router,
    prefix=""  # Routes define their own prefixes (/projects/{id}/knowledge, /progress/stats)
)

api_router.include_router(
    notifications.router,
    prefix=""  # Routes define own prefix (/notifications)
)