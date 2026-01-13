from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime, timezone

from app.models import User
from app.repositories.user_repo import UserRepository
from app.repositories.password_reset_repo import PasswordResetRepository
from app.schemas.auth import UserRegister, UserLogin, TokenResponse, UserResponse
from app.core.security import (
    verify_password,
    get_password_hash,
    create_access_token,
    create_refresh_token,
    verify_refresh_token,
    verify_token,
)
from app.utils.email import send_password_reset_code

from app.core.config import settings


class AuthService:
    """
    Service class for authentication operations.

    """
    def __init__(self, db: AsyncSession):
        """
        Initialize with database session.
        
        Args:
            db: AsyncSession instance
        """
        self.db = db
        self.user_repo = UserRepository(db)
        self.password_reset_repo = PasswordResetRepository(db)

    # ============================================================
    # User Registration
    # ============================================================
    async def register(self, user_data: UserRegister) -> TokenResponse:
        """
        Register a new user.
        
        Args:
            user_data: Validated registration data
            
        Returns:
            TokenResponse with tokens and user info
            
        Raises:
            ValueError: If email already exists
        """
        # Check if email already exists
        existing_user = await self.user_repo.get_by_email(user_data.email)

        if existing_user:
            raise ValueError("A user with this email already exists")
        
        # Create new user
        user = self.user_repo.create_user(user_data)

        # Generate tokens
        return self._create_token_response(user)
    

    # ============================================================
    # User Login
    # ============================================================
    async def login(self, login_data: UserLogin) -> TokenResponse:
        """
        Authenticate user and return tokens.
        
        Args:
            login_data: Email and password
            
        Returns:
            TokenResponse with tokens and user info
            
        Raises:
            ValueError: If credentials are invalid
        """
        # Find user by email
        user = await self.user_repo.get_by_email(login_data.email)

        # Check if user exists and password is correct
        if not user or not verify_password(login_data.password, user.password_hash):
            raise ValueError("Invalid email or password")
        
        # Check if user is active
        if not user.is_active:
            raise ValueError("This account has been deactivated")

        # Update last login time
        user.last_login = datetime.now(timezone.utc)
        await self.db.commit()

        # Generate tokens
        return self._create_token_response(user)
    

    # ============================================================
    # Token Refresh
    # ============================================================
    
    async def refresh_token(self, refresh_token: str) -> dict:
        """
        Create new access token from refresh token.
        
        Args:
            refresh_token: Valid refresh token
            
        Returns:
            Dict with new access token
            
        Raises:
            ValueError: If refresh token is invalid
        """
        # Verify refresh token
        user_id = verify_refresh_token(refresh_token)
        
        if not user_id:
            raise ValueError("Invalid or expired refresh token")
        
        # Verify user still exists and is active
        user = await self.user_repo.get_by_id(user_id)
        
        if not user or not user.is_active:
            raise ValueError("User not found or inactive")
        
        # Create new access token
        new_access_token = create_access_token(subject=str(user.id))
        
        return {
            "access_token": new_access_token,
            "token_type": "bearer",
            "expires_in": settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60
        }
    
    # ============================================================
    # Get Current User
    # ============================================================
    
    async def get_current_user(self, token: str) -> User:
        """
        Get user from access token.
        
        Args:
            token: Access token from request
            
        Returns:
            User object
            
        Raises:
            ValueError: If token is invalid
        """
        payload = verify_token(token)
        
        if not payload:
            raise ValueError("Invalid or expired token")
        
        if payload.get("type") != "access":
            raise ValueError("Invalid token type")
        
        user_id = payload.get("sub")
        user = await self.user_repo.get_by_id(user_id)
        
        if not user:
            raise ValueError("User not found")
        
        if not user.is_active:
            raise ValueError("User account is deactivated")
        
        return user

    # ============================================================
    # Password Reset - Request
    # ============================================================
    
    async def request_password_reset(self, email: str) -> bool:
        """
        Request a password reset for an email.
        
        Generates a 6-digit code and sends it via email.
        Always returns True to prevent email enumeration attacks.
        
        Args:
            email: User's email address
            
        Returns:
            True (always, for security)
        """
        # Find user by email
        user = await self.user_repo.get_by_email(email)
        
        if not user:
            # Return True anyway to prevent email enumeration
            return True
        
        if not user.is_active:
            # Return True anyway for security
            return True
        
        # Create reset code
        reset = await self.password_reset_repo.create_reset_code(str(user.id))
        
        # Send email with code
        send_password_reset_code(
            email=email,
            code=reset.reset_code,
            expires_in_minutes=settings.PASSWORD_RESET_TOKEN_EXPIRE_MINUTES
        )
        
        return True

    # ============================================================
    # Password Reset - Verify Code
    # ============================================================
    
    async def verify_reset_code(self, email: str, code: str) -> bool:
        """
        Verify a password reset code is valid.
        
        Args:
            email: User's email address
            code: 6-digit reset code
            
        Returns:
            True if code is valid, False otherwise
        """
        reset = await self.password_reset_repo.verify_code(email, code)
        return reset is not None

    # ============================================================
    # Password Reset - Reset Password
    # ============================================================
    
    async def reset_password(self, email: str, code: str, new_password: str) -> bool:
        """
        Reset user's password using a valid reset code.
        
        Args:
            email: User's email address
            code: 6-digit reset code
            new_password: New password to set
            
        Returns:
            True if password was reset successfully
            
        Raises:
            ValueError: If code is invalid or expired
        """
        # Verify code
        reset = await self.password_reset_repo.verify_code(email, code)
        
        if not reset:
            raise ValueError("Invalid or expired reset code")
        
        # Get user
        user = await self.user_repo.get_by_email(email)
        
        if not user:
            raise ValueError("User not found")
        
        # Update password
        user.password_hash = get_password_hash(new_password)
        await self.db.commit()
        
        # Mark code as used
        await self.password_reset_repo.mark_code_used(str(reset.id))
        
        return True
    

    # ============================================================
    # Helper Methods
    # ============================================================
    
    def _create_token_response(self, user: User) -> TokenResponse:
        """
        Create token response for a user.
        
        Args:
            user: User object
            
        Returns:
            TokenResponse with access token, refresh token, and user info
        """
        access_token = create_access_token(subject=str(user.id))
        refresh_token = create_refresh_token(subject=str(user.id))
        
        return TokenResponse(
            access_token=access_token,
            refresh_token=refresh_token,
            token_type="bearer",
            expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
            user=UserResponse(
                id=str(user.id),
                email=user.email,
                full_name=user.full_name,
                is_active=user.is_active,
                default_socratic_mode=user.default_socratic_mode,
                created_at=user.created_at,
                last_login=user.last_login
            )
        )




