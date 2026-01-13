from pydantic import BaseModel, EmailStr, Field, field_validator
from typing import Optional
from datetime import datetime
import re


# ============================================================
# Request Schemas (What client sends)
# ============================================================

class UserRegister(BaseModel):
    """Schema for user registration request"""
    
    email: EmailStr  # Pydantic validates this is a valid email
    password: str = Field(
        min_length=8,
        max_length=100,
        description="Password must be 8-100 characters"
    )
    full_name: str = Field(
        min_length=2,
        max_length=100,
        description="Full name must be 2-100 characters"
    )
    
    @field_validator("password")
    @classmethod
    def validate_password_strength(cls, v: str) -> str:
        """
        Validate password meets strength requirements.
        
        Requirements:
        - At least 8 characters (already checked by min_length)
        - At least one uppercase letter
        - At least one lowercase letter
        - At least one digit
        """
        if not re.search(r"[A-Z]", v):
            raise ValueError("Password must contain at least one uppercase letter")
        if not re.search(r"[a-z]", v):
            raise ValueError("Password must contain at least one lowercase letter")
        if not re.search(r"\d", v):
            raise ValueError("Password must contain at least one digit")
        return v
    
    @field_validator("full_name")
    @classmethod
    def validate_full_name(cls, v: str) -> str:
        """Remove extra whitespace from name"""
        return " ".join(v.split())
    
    class Config:
        json_schema_extra = {
            "example": {
                "email": "student@university.edu",
                "password": "SecurePass123",
                "full_name": "Abebe Kebede"
            }
        }


class UserLogin(BaseModel):
    """Schema for user login request"""
    
    email: EmailStr
    password: str
    
    class Config:
        json_schema_extra = {
            "example": {
                "email": "student@university.edu",
                "password": "SecurePass123"
            }
        }


class RefreshTokenRequest(BaseModel):
    """Schema for token refresh request"""
    
    refresh_token: str


# ============================================================
# Response Schemas (What server sends back)
# ============================================================

class PasswordResetRequest(BaseModel):
    """Schema for password reset request"""
    email: EmailStr


class PasswordResetConfirm(BaseModel):
    """Schema for setting new password after reset"""
    email: EmailStr
    code: str = Field(
        min_length=6,
        max_length=6,
        description="6-digit reset code"
    )
    new_password: str = Field(
        min_length=8,
        max_length=100,
        description="Password must be 8-100 characters"
    )

    @field_validator("new_password")
    @classmethod
    def validate_password_strength(cls, v: str) -> str:
        if not re.search(r"[A-Z]", v):
            raise ValueError("Password must contain at least one uppercase letter")
        if not re.search(r"[a-z]", v):
            raise ValueError("Password must contain at least one lowercase letter")
        if not re.search(r"\d", v):
            raise ValueError("Password must contain at least one digit")
        return v

    class Config:
        json_schema_extra = {
            "example": {
                "email": "student@university.edu",
                "code": "123456",
                "new_password": "NewSecurePass123"
            }
        }


class VerifyResetCodeRequest(BaseModel):
    """Schema for verifying reset code"""
    email: EmailStr
    code: str = Field(
        min_length=6,
        max_length=6,
        description="6-digit reset code"
    )

    class Config:
        json_schema_extra = {
            "example": {
                "email": "student@university.edu",
                "code": "123456"
            }
        }


# ============================================================
# Response Schemas (What server sends back)
# ============================================================

class MessageResponse(BaseModel):
    """Schema for simple message responses"""
    message: str
    success: bool = True

    class Config:
        json_schema_extra = {
            "example": {
                "message": "Password reset code sent to your email",
                "success": True
            }
        }


class UserResponse(BaseModel):
    """Schema for user data in responses (NO password!)"""
    
    id: str
    email: str
    full_name: str
    avatar_url: Optional[str] = None
    is_active: bool
    default_socratic_mode: bool
    created_at: datetime
    last_login: Optional[datetime] = None
    
    class Config:
        from_attributes = True  # Allow creating from ORM model


class TokenResponse(BaseModel):
    """Schema for authentication token response"""
    
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int  # Seconds until access token expires
    user: UserResponse
    
    class Config:
        json_schema_extra = {
            "example": {
                "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
                "refresh_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
                "token_type": "bearer",
                "expires_in": 3600,
                "user": {
                    "id": "550e8400-e29b-41d4-a716-446655440000",
                    "email": "student@university.edu",
                    "full_name": "Abebe Kebede",
                    "is_active": True,
                    "default_socratic_mode": True,
                    "created_at": "2024-01-01T00:00:00Z"
                }
            }
        }


class TokenRefreshResponse(BaseModel):
    """Schema for token refresh response"""
    
    access_token: str
    token_type: str = "bearer"
    expires_in: int


# ============================================================
# Error Schemas
# ============================================================

class ErrorResponse(BaseModel):
    """Schema for error responses"""
    
    detail: str
    
    class Config:
        json_schema_extra = {
            "example": {
                "detail": "Invalid email or password"
            }
        }