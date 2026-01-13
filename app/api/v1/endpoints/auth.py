from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.schemas.auth import (
    UserRegister,
    UserLogin,
    TokenResponse,
    TokenRefreshResponse,
    RefreshTokenRequest,
    UserResponse,
    ErrorResponse
)
from app.services.auth_service import AuthService
from app.api.deps import get_current_user
from app.models.user import User

# ============================================================
# Router Setup
# ============================================================

router = APIRouter(tags=["Authentication"])


# ============================================================
# Registration Endpoint
# ============================================================

@router.post(
    "/register",
    response_model=TokenResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        201: {"description": "User created successfully"},
        400: {"model": ErrorResponse, "description": "Email already exists"},
        422: {"description": "Validation error"}
    }
)
async def register(
    user_data: UserRegister,
    db: AsyncSession = Depends(get_db)
):
    """
    Register a new user account.

    Returns access token, refresh token, and user info.
    """
    auth_service = AuthService(db)

    try:
        return await auth_service.register(user_data)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    

# ============================================================
# Login Endpoint
# ============================================================
@router.post(
    "/login",
    response_model=TokenResponse,
    responses={
        200: {"description": "Login successful"},
        401: {"model": ErrorResponse, "description": "Invalid credentials"},
    }
)
async def login(
    login_data: UserLogin,
    db: AsyncSession = Depends(get_db)
):
    """
    Authenticate user and get tokens.
    
    - **email**: Registered email address
    - **password**: Account password
    
    Returns access token (short-lived) and refresh token (long-lived).
    """
    auth_service = AuthService(db)
    
    try:
        return await auth_service.login(login_data)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(e),
            headers={"WWW-Authenticate": "Bearer"}
        )    
    
# ============================================================
# Token Refresh Endpoint
# ============================================================

@router.post(
    "/refresh",
    response_model=TokenRefreshResponse,
    responses={
        200: {"description": "Token refreshed successfully"},
        401: {"model": ErrorResponse, "description": "Invalid refresh token"},
    }
)
async def refresh_token(
    token_data: RefreshTokenRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    Get new access token using refresh token.
    
    Use this when access token expires to get a new one
    without requiring the user to log in again.
    """
    auth_service = AuthService(db)
    
    try:
        return auth_service.refresh_token(token_data.refresh_token)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(e)
        )
# ============================================================
# Get Current User Endpoint
# ============================================================

@router.get(
    "/me",
    response_model=UserResponse,
    responses={
        200: {"description": "Current user info"},
        401: {"model": ErrorResponse, "description": "Not authenticated"},
    }
)
async def get_me(
    current_user: User = Depends(get_current_user)
):
    """
    Get current authenticated user's information.
    
    Requires valid access token in Authorization header:
    `Authorization: Bearer <access_token>`
    """
    return UserResponse(
        id=str(current_user.id),
        email=current_user.email,
        full_name=current_user.full_name,
        is_active=current_user.is_active,
        default_socratic_mode=current_user.default_socratic_mode,
        created_at=current_user.created_at,
        last_login=current_user.last_login
    )    
