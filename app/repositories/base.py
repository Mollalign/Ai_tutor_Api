"""
Base Repository

Abstract base class for all repositories.
Provides common database operations.
"""

from typing import Generic, TypeVar, Type, Optional, List, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, delete

from app.db.database import Base

ModelType = TypeVar("ModelType", bound=[Base])

class BaseRepository(Generic[ModelType]):
    """
    Base repository class with common CRUD operations.
    
    All repositories should inherit from this class.
    """
    def __init__(self, model: Type[ModelType], db: AsyncSession):
        """
        Initialize repository.
        
        Args:
            model: SQLAlchemy model class
            db: Database session
        """
        self.model = model
        self.db = db

    # -----------------------------
    # Get Element By id
    # -----------------------------
    async def get_by_id(self, id: Any) -> Optional[ModelType]:
        """Get a record by ID (supports UUID, int, or string)."""
        result = await self.db.execute(
            select(self.model).where(self.model.id == id)
        )
        return result.scalar_one_or_none()
    
    # -----------------------------
    # Get all Records
    # -----------------------------
    async def get_all(
        self,
        skip: int = 0,
        limit: int = 100,
        order_by=None
    ) -> List[ModelType]:
        """Get all records with pagination."""
        query = select(self.model)

        if order_by:
            query = query.order_by(order_by)

        query = query.offset(skip).limit(limit)
        result = await self.db.execute(query)
        return list(result.scalars().all())    
    
    # -----------------------------
    # Create Single Record
    # -----------------------------
    async def create(self, **kwargs) -> ModelType:
        """Create a new record."""
        instance = self.model(**kwargs)
        self.db.add(instance)
        await self.db.commit()
        await self.db.refresh(instance)
        return instance

    # -----------------------------
    # Update record
    # -----------------------------
    async def update(self, id: Any, **kwargs) -> Optional[ModelType]:
        """Update a record by ID (supports UUID, int, or string)."""
        instance = await self.get_by_id(id)
        if not instance:
            return None
        
        for key, value in kwargs.items():
            setattr(instance, key, value)
        
        await self.db.commit()
        await self.db.refresh(instance)
        return instance
    
    # This used to Delete
    async def delete(self, id: Any) -> bool:
        """Delete a record by ID (supports UUID, int, or string)."""
        instance = await self.get_by_id(id)
        if not instance:
            return False
        
        await self.db.delete(instance)
        await self.db.commit()
        return True 
    
    # this used to count records
    async def count(self) -> int:
        """Count total records."""
        from sqlalchemy import func
        result = await self.db.execute(
            select(func.count(self.model.id))
        )
        return result.scalar() or 0