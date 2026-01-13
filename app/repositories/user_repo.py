"""
User Repository

Data access layer for User model.
All user-related database operations.
"""

from typing import Optional, List
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.repositories.base import BaseRepository
from app.models import User
from app.schemas.auth import UserRegister
from app.core.security import get_password_hash

class UserRepository(BaseRepository[User]):
    """Repository for User model."""

    def __init__(self, db: AsyncSession):
        super().__init__(User, db)

    # =================
    # Get by email
    # =================
    async def get_by_email(self, email: str) -> Optional[User]:
        """Get a user by email address."""
        result = await self.db.execute(
            select(User).where(User.email == email)
        )
        return result.scalar_one_or_none()
    
    # =================
    # Get all users
    # =================
    async def get_all_users(self, skip: int = 0, limit: int = 100) -> List[User]:
        """Get all users ordered by creation date."""
        result = await self.db.execute(
            select(User)
            .order_by(User.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        return list(result.scalars().all())
    
    # =================
    # Create user
    # =================
    async def create_user(self, user_data: UserRegister):
        """Create a new user."""
        
        # Create new user
        user = User(
           email=user_data.email,
           password=get_password_hash(user_data.password),
           full_name=user_data.full_name,
           is_active=True,
           default_socratic_mode=True
        )

        # Save to database
        self.db.add(user)
        await self.db.commit()
        await self.db.refresh(user)

        return user

    # =================
    # Update user
    # =================
    async def update_user(self, user_id, **kwargs) -> Optional[User]:
        """Update user fields."""
        return await self.update(user_id, **kwargs)
    
    # =================
    # Delete user
    # =================
    async def delete_user(self, user_id) -> bool:
        """Delete a user by ID."""
        return await self.delete(user_id) 

