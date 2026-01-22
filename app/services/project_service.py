"""
Project Service
Business logic for project operations.
"""

from typing import List
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.project_repo import ProjectRepository
from app.models.project import Project
from app.schemas.project import ProjectCreate, ProjectUpdate

class ProjectService:
    """Service class for project operations."""

    def __init__(self, db: AsyncSession):
        """Initialize with database session."""
        self.db = db
        self.project_repo = ProjectRepository(db)

    # ============================================================
    # Create Project
    # ============================================================  
    async def create_project(
        self,
        project_data: ProjectCreate,
        user_id: UUID
    ) -> Project:
        """
        Create a new project for a user.
        
        Args:
            project_data: Validated project creation data
            user_id: ID of the user creating the project
            
        Returns:
            Created project
        """
        return await self.project_repo.create(
            name=project_data.name,
            description=project_data.description,
            user_id=user_id,
            is_archived=False
        )
    
    # ============================================================
    # Get Single Project
    # ============================================================
    async def get_project(
        self, 
        project_id: UUID, 
        user_id: UUID
    ) -> Project:
        """
        Get a project by ID, verifying ownership.
        
        Args:
            project_id: ID of the project to retrieve
            user_id: ID of the requesting user
            
        Returns:
            The project if found and owned by user
            
        Raises:
            ValueError: If project not found or not owned by user
        """
        project = await self.project_repo.get_by_id(project_id)

        if not project or project.user_id != user_id:
            raise ValueError("Project not found")

        return project

    # ============================================================
    # Get User's Projects
    # ============================================================    
    async def get_user_projects(
        self, 
        user_id: UUID, 
        skip: int = 0, 
        limit: int = 100
    ) -> List[Project]:
        """
        Get all projects for a user.
        
        Args:
            user_id: ID of the user
            skip: Pagination offset
            limit: Maximum results
            
        Returns:
            List of user's projects
        """
        projects = await self.project_repo.get_all_for_user(user_id, skip, limit)
        return projects

    # ============================================================
    # Update Project
    # ============================================================
    async def update_project(
        self, 
        project_id: UUID, 
        project_data: ProjectUpdate, 
        user_id: UUID
    ) -> Project:
        """
        Update a project, verifying ownership.
        
        Args:
            project_id: ID of the project to update
            project_data: Fields to update
            user_id: ID of the requesting user
            
        Returns:
            Updated project
            
        Raises:
            ValueError: If project not found or not owned by user
        """
        project = await self.get_project(project_id, user_id)
        
        update_data = project_data.model_dump(exclude_unset=True)
        
        if update_data:
            return await self.project_repo.update(project_id, **update_data)
        else:
            return project 
        
    
    # ============================================================
    # Get User's Projects Count
    # ============================================================    
    async def get_user_projects_count(self, user_id: UUID) -> int:
        """
        Get the count of projects for a user.
        
        Args:
            user_id: ID of the user
            
        Returns:
            Count of user's projects
        """
        return await self.project_repo.count_for_user(user_id)


    # ============================================================
    # Delete Project
    # ============================================================
    async def delete_project(
        self, 
        project_id: UUID, 
        user_id: UUID
    ) -> bool:
        """
        Delete a project, verifying ownership.
        
        Args:
            project_id: ID of the project to delete
            user_id: ID of the requesting user
            
        Returns:
            True if deleted successfully
            
        Raises:
            ValueError: If project not found or not owned by user
        """
        project = await self.get_project(project_id, user_id)
        return await self.project_repo.delete(project_id)    