from fastapi import HTTPException, Depends, Header, Request
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional, Dict, Any
import uuid
from datetime import datetime, timezone

from app.db.database import get_db
from app.core.security import verify_access_token, get_token_remaining_time
# from app.services.auth_service import AuthService



# =====================================================
# Get Current user
# =====================================================
async def get_current_user(
    authorization: Optional[str] = Header(None),
    db: AsyncSession = Depends(get_db)
) -> str:
    """Get current authenticated user from JWT access token."""
    if not authorization:
        raise HTTPException(status_code=401, detail="Authorization header missing")
    
    try:
        scheme, token = authorization.split()
        if scheme.lower() != "bearer":
            raise HTTPException(status_code=401, detail="Invalid authentication scheme")
    except ValueError:
        raise HTTPException(status_code=401, detail="Invalid authorization header format")
    
    # Verify access token (not refresh token)
    user_id = verify_access_token(token)
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    
    return user_id

# =====================================================
# Get Current User With Info
# =====================================================

# async def get_current_user_with_info(
#     current_user: str = Depends(get_current_user),
#     db: AsyncSession = Depends(get_db)
# ) -> Dict[str, Any]:
#     """Get current user with detailed information."""
#     auth_service = AuthService(db)
    
#     user_info = await auth_service.validate_user_access(current_user)
#     if not user_info:
#         raise HTTPException(status_code=401, detail="Invalid token")
    
#     return user_info


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
