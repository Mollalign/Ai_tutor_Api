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
    ErrorResponse,
    PasswordResetRequest,
    PasswordResetConfirm,
    VerifyResetCodeRequest,
    MessageResponse,
    GoogleAuthRequest,
    UserUpdateRequest,
    ChangePasswordRequest,
    FcmTokenRequest,
    NotificationPreferencesUpdate,
    NotificationPreferencesResponse,
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
# Google Sign-In Endpoint
# ============================================================

@router.post(
    "/google",
    response_model=TokenResponse,
    responses={
        200: {"description": "Google authentication successful"},
        401: {"model": ErrorResponse, "description": "Invalid Google token"},
    }
)
async def google_auth(
    request_data: GoogleAuthRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Authenticate or register via Google Sign-In.

    The client sends the Google ID token obtained from the Google Sign-In SDK.
    The backend verifies it with Google, finds or creates the user, and returns
    JWT tokens.
    """
    auth_service = AuthService(db)

    try:
        return await auth_service.google_auth(request_data.id_token)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(e),
            headers={"WWW-Authenticate": "Bearer"},
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
        return await auth_service.refresh_token(token_data.refresh_token)
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
        avatar_color=current_user.avatar_color,
        is_active=current_user.is_active,
        default_socratic_mode=current_user.default_socratic_mode,
        created_at=current_user.created_at,
        last_login=current_user.last_login
    )


# ============================================================
# Update Profile Endpoint
# ============================================================

@router.patch(
    "/me",
    response_model=UserResponse,
    responses={
        200: {"description": "Profile updated"},
        401: {"model": ErrorResponse, "description": "Not authenticated"},
    },
)
async def update_me(
    update_data: UserUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update the current user's profile fields."""
    if update_data.full_name is not None:
        current_user.full_name = update_data.full_name
    if update_data.default_socratic_mode is not None:
        current_user.default_socratic_mode = update_data.default_socratic_mode
    if update_data.avatar_color is not None:
        current_user.avatar_color = update_data.avatar_color

    await db.commit()
    await db.refresh(current_user)

    return UserResponse(
        id=str(current_user.id),
        email=current_user.email,
        full_name=current_user.full_name,
        avatar_color=current_user.avatar_color,
        is_active=current_user.is_active,
        default_socratic_mode=current_user.default_socratic_mode,
        created_at=current_user.created_at,
        last_login=current_user.last_login,
    )


# ============================================================
# Change Password Endpoint
# ============================================================

@router.post(
    "/change-password",
    response_model=MessageResponse,
    responses={
        200: {"description": "Password changed"},
        400: {"model": ErrorResponse, "description": "Invalid current password"},
    },
)
async def change_password(
    request_data: ChangePasswordRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Change password for email-authenticated users."""
    from app.core.security import verify_password, get_password_hash

    if current_user.auth_provider != "email" or current_user.password_hash is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This account uses Google Sign-In and has no password to change.",
        )

    if not verify_password(request_data.current_password, current_user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password is incorrect.",
        )

    current_user.password_hash = get_password_hash(request_data.new_password)
    await db.commit()

    return MessageResponse(message="Password changed successfully.", success=True)


# ============================================================
# Forgot Password Endpoint
# ============================================================

@router.post(
    "/forgot-password",
    response_model=MessageResponse,
    responses={
        200: {"description": "Reset code sent if email exists"},
    }
)
async def forgot_password(
    request_data: PasswordResetRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    Request a password reset code.
    
    - **email**: Registered email address
    
    A 6-digit reset code will be sent to the email if it exists.
    For security, always returns success even if email doesn't exist.
    """
    auth_service = AuthService(db)
    await auth_service.request_password_reset(request_data.email)
    
    return MessageResponse(
        message="If an account with this email exists, a reset code has been sent.",
        success=True
    )


# ============================================================
# Verify Reset Code Endpoint
# ============================================================

@router.post(
    "/verify-reset-code",
    response_model=MessageResponse,
    responses={
        200: {"description": "Code verification result"},
        400: {"model": ErrorResponse, "description": "Invalid or expired code"},
    }
)
async def verify_reset_code(
    request_data: VerifyResetCodeRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    Verify a password reset code is valid.
    
    - **email**: Email address that requested the reset
    - **code**: 6-digit reset code from email
    
    Use this to validate the code before allowing password reset.
    """
    auth_service = AuthService(db)
    is_valid = await auth_service.verify_reset_code(
        request_data.email,
        request_data.code
    )
    
    if not is_valid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired reset code"
        )
    
    return MessageResponse(
        message="Reset code is valid",
        success=True
    )


# ============================================================
# Reset Password Endpoint
# ============================================================

@router.post(
    "/reset-password",
    response_model=MessageResponse,
    responses={
        200: {"description": "Password reset successfully"},
        400: {"model": ErrorResponse, "description": "Invalid or expired code"},
    }
)
async def reset_password(
    request_data: PasswordResetConfirm,
    db: AsyncSession = Depends(get_db)
):
    """
    Reset password using a valid reset code.
    
    - **email**: Email address that requested the reset
    - **code**: 6-digit reset code from email
    - **new_password**: New password (must meet strength requirements)
    
    After successful reset, the user can log in with the new password.
    """
    auth_service = AuthService(db)
    
    try:
        await auth_service.reset_password(
            request_data.email,
            request_data.code,
            request_data.new_password
        )
        
        return MessageResponse(
            message="Password has been reset successfully. You can now log in with your new password.",
            success=True
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )


# ============================================================
# FCM Token Endpoint
# ============================================================

@router.post(
    "/fcm-token",
    response_model=MessageResponse,
    summary="Save or update FCM token for push notifications",
)
async def save_fcm_token(
    request_data: FcmTokenRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Save the device's FCM token for push notifications."""
    current_user.fcm_token = request_data.fcm_token
    await db.commit()
    return MessageResponse(message="FCM token saved.", success=True)


# ============================================================
# Notification Preferences Endpoints
# ============================================================

@router.get(
    "/notification-preferences",
    response_model=NotificationPreferencesResponse,
    summary="Get notification preferences",
)
async def get_notification_preferences(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get the current user's notification preferences."""
    from sqlalchemy import select
    from app.models.notification_preference import NotificationPreference

    result = await db.execute(
        select(NotificationPreference).where(
            NotificationPreference.user_id == current_user.id
        )
    )
    pref = result.scalar_one_or_none()

    if pref is None:
        return NotificationPreferencesResponse()

    return NotificationPreferencesResponse(
        study_reminders_enabled=pref.study_reminders_enabled,
        reminder_time=pref.reminder_time.strftime("%H:%M") if pref.reminder_time else None,
        quiz_results_enabled=pref.quiz_results_enabled,
    )


@router.patch(
    "/notification-preferences",
    response_model=NotificationPreferencesResponse,
    summary="Update notification preferences",
)
async def update_notification_preferences(
    update_data: NotificationPreferencesUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update the current user's notification preferences."""
    from datetime import time
    from sqlalchemy import select
    from app.models.notification_preference import NotificationPreference

    result = await db.execute(
        select(NotificationPreference).where(
            NotificationPreference.user_id == current_user.id
        )
    )
    pref = result.scalar_one_or_none()

    if pref is None:
        pref = NotificationPreference(user_id=current_user.id)
        db.add(pref)

    if update_data.study_reminders_enabled is not None:
        pref.study_reminders_enabled = update_data.study_reminders_enabled
    if update_data.reminder_time is not None:
        parts = update_data.reminder_time.split(":")
        pref.reminder_time = time(int(parts[0]), int(parts[1]))
    if update_data.quiz_results_enabled is not None:
        pref.quiz_results_enabled = update_data.quiz_results_enabled

    await db.commit()
    await db.refresh(pref)

    return NotificationPreferencesResponse(
        study_reminders_enabled=pref.study_reminders_enabled,
        reminder_time=pref.reminder_time.strftime("%H:%M") if pref.reminder_time else None,
        quiz_results_enabled=pref.quiz_results_enabled,
    )
