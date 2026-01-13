"""
Password Reset Repository

Data access layer for PasswordReset model.
All password reset-related database operations.
"""

import secrets
from typing import Optional
from datetime import datetime, timezone, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_

from app.repositories.base import BaseRepository
from app.models.password_reset import PasswordReset
from app.models.user import User
from app.core.config import settings


class PasswordResetRepository(BaseRepository[PasswordReset]):
    """Repository for PasswordReset model."""

    def __init__(self, db: AsyncSession):
        super().__init__(PasswordReset, db)

    # =================
    # Generate reset code
    # =================
    @staticmethod
    def generate_reset_code() -> str:
        """Generate a 6-digit reset code."""
        return ''.join([str(secrets.randbelow(10)) for _ in range(6)])

    # =================
    # Create reset code
    # =================
    async def create_reset_code(self, user_id: str) -> PasswordReset:
        """
        Create a new password reset code for a user.
        Invalidates any existing unused codes for this user.
        
        Args:
            user_id: The user's ID
            
        Returns:
            PasswordReset instance with the new code
        """
        # Invalidate existing unused codes for this user
        await self.invalidate_user_codes(user_id)
        
        # Generate new code
        code = self.generate_reset_code()
        expires_at = datetime.now(timezone.utc) + timedelta(
            minutes=settings.PASSWORD_RESET_TOKEN_EXPIRE_MINUTES
        )
        
        # Create new reset record
        reset = PasswordReset(
            user_id=user_id,
            reset_code=code,
            expires_at=expires_at,
            is_used=False
        )
        
        self.db.add(reset)
        await self.db.commit()
        await self.db.refresh(reset)
        
        return reset

    # =================
    # Invalidate user codes
    # =================
    async def invalidate_user_codes(self, user_id: str) -> None:
        """
        Mark all existing unused codes for a user as used.
        
        Args:
            user_id: The user's ID
        """
        result = await self.db.execute(
            select(PasswordReset).where(
                and_(
                    PasswordReset.user_id == user_id,
                    PasswordReset.is_used == False
                )
            )
        )
        codes = result.scalars().all()
        
        for code in codes:
            code.is_used = True
        
        await self.db.commit()

    # =================
    # Verify reset code
    # =================
    async def verify_code(self, email: str, code: str) -> Optional[PasswordReset]:
        """
        Verify a password reset code.
        
        Args:
            email: User's email address
            code: The 6-digit reset code
            
        Returns:
            PasswordReset if valid, None otherwise
        """
        # Find user by email first
        user_result = await self.db.execute(
            select(User).where(User.email == email)
        )
        user = user_result.scalar_one_or_none()
        
        if not user:
            return None
        
        # Find valid reset code
        result = await self.db.execute(
            select(PasswordReset).where(
                and_(
                    PasswordReset.user_id == user.id,
                    PasswordReset.reset_code == code,
                    PasswordReset.is_used == False,
                    PasswordReset.expires_at > datetime.now(timezone.utc)
                )
            )
        )
        
        return result.scalar_one_or_none()

    # =================
    # Mark code as used
    # =================
    async def mark_code_used(self, reset_id: str) -> None:
        """
        Mark a reset code as used.
        
        Args:
            reset_id: The PasswordReset record ID
        """
        reset = await self.get_by_id(reset_id)
        if reset:
            reset.is_used = True
            await self.db.commit()

    # =================
    # Get active code for user
    # =================
    async def get_active_code(self, user_id: str) -> Optional[PasswordReset]:
        """
        Get the active (unused and not expired) reset code for a user.
        
        Args:
            user_id: The user's ID
            
        Returns:
            PasswordReset if exists, None otherwise
        """
        result = await self.db.execute(
            select(PasswordReset).where(
                and_(
                    PasswordReset.user_id == user_id,
                    PasswordReset.is_used == False,
                    PasswordReset.expires_at > datetime.now(timezone.utc)
                )
            ).order_by(PasswordReset.created_at.desc())
        )
        
        return result.scalar_one_or_none()

