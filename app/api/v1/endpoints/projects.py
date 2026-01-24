"""
Project Endpoints
HTTP API for project management.
"""

from typing import List
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.database import get_db
from app.api.deps import get_current_user
from app.models.user import User
from app.schemas.project import ProjectCreate, ProjectUpdate, ProjectResponse
from app.services.project_service import ProjectService
from app.services.document_service import DocumentService

# ============================================================
# Router Setup
# ============================================================
router = APIRouter(tags=["Projects"])

# ============================================================
# Create Project
# ============================================================

@router.post(
    "",
    response_model=ProjectResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        201: {"description": "Project created successfully"},
        401: {"description": "Not authenticated"},
    }
)
async def create_project(
    project_data: ProjectCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Create a new project.
    
    The project will be owned by the authenticated user.
    """
    project_service = ProjectService(db)
    project = await project_service.create_project(project_data, current_user.id)
    return project


# ============================================================
# List Projects
# ============================================================
@router.get(
    "",
    response_model=List[ProjectResponse],
    responses={
        200: {"description": "List of user's projects"},
        401: {"description": "Not authenticated"},
    }
)
async def list_projects(
    skip: int = Query(0, ge=0, description="Number of projects to skip"),
    limit: int = Query(20, ge=1, le=100, description="Max projects to return"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Get all projects for the authenticated user.
    
    Results are paginated and ordered by most recently updated.
    """
    project_service = ProjectService(db)
    projects = await project_service.get_user_projects(current_user.id, skip, limit)
    return projects


# ============================================================
# Get Single Project
# ============================================================
@router.get(
    "/{project_id}",
    response_model=ProjectResponse,
    responses={
        200: {"description": "Project details"},
        401: {"description": "Not authenticated"},
        404: {"description": "Project not found"},
    }
)
async def get_project(
    project_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Get a specific project by ID.
    
    Only returns the project if owned by the authenticated user.
    """
    project_service = ProjectService(db)
    try:
        project = await project_service.get_project(project_id, current_user.id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return project


# ============================================================
# Update Project
# ============================================================
@router.patch(
    "/{project_id}",
    response_model=ProjectResponse,
    responses={
        200: {"description": "Project updated successfully"},
        401: {"description": "Not authenticated"},
        404: {"description": "Project not found"},
    }
)
async def update_project(
    project_id: UUID,
    project_data: ProjectUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Update a project.
    
    Only the owner can update the project.
    Only provided fields will be updated.
    """
    project_service = ProjectService(db)
    try:
        project = await project_service.update_project(project_id, project_data, current_user.id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return project

# ============================================================
# Delete Project
# ============================================================
@router.delete(
    "/{project_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={
        204: {"description": "Project deleted successfully"},
        401: {"description": "Not authenticated"},
        404: {"description": "Project not found"},
    }
)
async def delete_project(
    project_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Delete a project.
    
    Only the owner can delete the project.
    This permanently removes the project and all related data.
    """
    project_service = ProjectService(db)
    document_service = DocumentService(db)
    try:
        await project_service.delete_project(project_id, current_user.id)

        # delete associated document with this project
        await document_service.delete_project_documents(project_id, current_user.id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return None