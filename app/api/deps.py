from fastapi import HTTPException, Depends, Header, status
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from typing import Optional, Dict, Any
import uuid
from datetime import datetime, timezone

from app.db.database import get_db
from app.models import User
from app.core.security import get_token_remaining_time
from app.services.auth_service import AuthService

# Security scheme for Swagger UI
security = HTTPBearer()

# =====================================================
# Get Current user
# =====================================================
async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncSession = Depends(get_db)
) -> User:
    """
    Dependency that validates JWT token and returns current user.
    
    Raises:
        HTTPException 401: If token is invalid or missing
    """
    token = credentials.credentials

    auth_service = AuthService(db)

    try:
        user = await auth_service.get_current_user(token)
        return user
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(e),
            headers={"WWW-Authenticate": "Bearer"}
        )

async def get_current_active_user(
    current_user: User = Depends(get_current_user)
) -> User:
    """
    Dependency that ensures user is active.
    
    Builds on get_current_user, adds active check.
    """
    if not current_user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Inactive user"
        )
    return current_user

# =====================================================
# Get Token info
# =====================================================
async def get_token_info(
    authorization: Optional[str] = Header(None)
) -> Dict[str, Any]:
    """Get token information including remaining time."""
    if not authorization:
        raise HTTPException(status_code=401, detail="Authorization header missing")
    
    try:
        scheme, token = authorization.split()
        if scheme.lower() != "bearer":
            raise HTTPException(status_code=401, detail="Invalid authentication scheme")
    except ValueError:
        raise HTTPException(status_code=401, detail="Invalid authorization header format")
    
    # Get token remaining time
    remaining_time = get_token_remaining_time(token)
    if remaining_time is None:
        raise HTTPException(status_code=401, detail="Invalid token")
    
    return {
        "token": token,
        "remaining_time": remaining_time,
        "expires_at": datetime.now(timezone.utc).timestamp() + remaining_time
    }
