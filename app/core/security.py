from datetime import datetime, timezone, timedelta
from typing import Any, Union, Optional, Dict
import uuid

from jose import JWTError, jwt

# Use bcrypt directly to avoid passlib/bcrypt version conflicts
import bcrypt

# =====================================================
# Application Settings
# =====================================================
from app.core.config import settings


# =====================================================
# Password Hashing Context
# =====================================================
class PasswordContext:
    """
    Simple password hashing and verification utility.
    Replaces passlib to avoid version conflicts.
    """

    @staticmethod
    def hash(password: str) -> str:
        """
        Hash a plain-text password using bcrypt.
        """
        return bcrypt.hashpw(
            password.encode("utf-8"),
            bcrypt.gensalt()
        ).decode("utf-8")

    @staticmethod
    def verify(plain_password: str, hashed_password: str) -> bool:
        """
        Verify a plain-text password against a bcrypt hash.
        """
        return bcrypt.checkpw(
            plain_password.encode("utf-8"),
            hashed_password.encode("utf-8")
        )


# Password context instance
pwd_context = PasswordContext()


# =====================================================
# Token Type Constants
# =====================================================
TOKEN_TYPE_ACCESS = "access"
TOKEN_TYPE_REFRESH = "refresh"


# =====================================================
# JWT Creation Functions
# =====================================================
def create_access_token(
    subject: Union[str, Any],
    expires_delta: Optional[timedelta] = None
) -> str:
    """
    Create a JWT access token.
    """
    # Current UTC time (timezone-aware)
    now = datetime.now(timezone.utc)

    # Determine expiration time
    if expires_delta:
        expire = now + expires_delta
    else:
        expire = now + timedelta(
            minutes=settings.access_token_expire_minutes
        )

    # JWT payload
    to_encode = {
        "exp": expire,                     # Expiration time
        "sub": str(subject),               # Subject (usually user ID)
        "type": TOKEN_TYPE_ACCESS,         # Token type
        "iat": now,                        # Issued at
        "jti": str(uuid.uuid4())           # Unique token ID
    }

    # Encode JWT
    encoded_jwt = jwt.encode(
        to_encode,
        settings.SECRET_KEY,
        algorithm=settings.ALGORITHM
    )
    return encoded_jwt


def create_refresh_token(
    subject: Union[str, Any],
    expires_delta: Optional[timedelta] = None
) -> str:
    """
    Create a JWT refresh token.
    """
    # Current UTC time (timezone-aware)
    now = datetime.now(timezone.utc)

    # Determine expiration time
    if expires_delta:
        expire = now + expires_delta
    else:
        expire = now + timedelta(
            days=settings.REFRESH_TOKEN_EXPIRE_DAYS
        )

    # JWT payload
    to_encode = {
        "exp": expire,                     # Expiration time
        "sub": str(subject),               # Subject
        "type": TOKEN_TYPE_REFRESH,        # Token type
        "iat": now,                        # Issued at
        "jti": str(uuid.uuid4())            # JWT ID (used for revocation)
    }

    # Encode JWT
    encoded_jwt = jwt.encode(
        to_encode,
        settings.SECRET_KEY,
        algorithm=settings.ALGORITHM
    )
    return encoded_jwt


# =====================================================
# Token Verification Functions
# =====================================================
def verify_token(
    token: str,
    token_type: str = TOKEN_TYPE_ACCESS
) -> Optional[Dict[str, Any]]:
    """
    Verify a JWT token and return its payload if valid.
    """
    try:
        # Decode JWT
        payload = jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=[settings.ALGORITHM]
        )

        # Validate token type
        if payload.get("type") != token_type:
            return None

        # Validate expiration time
        exp = payload.get("exp")
        if exp and datetime.now(timezone.utc).timestamp() > exp:
            return None

        return payload

    except JWTError:
        return None


def verify_access_token(token: str) -> Optional[str]:
    """
    Verify access token and return the subject.
    """
    payload = verify_token(token, TOKEN_TYPE_ACCESS)
    return payload.get("sub") if payload else None


def verify_refresh_token(token: str) -> Optional[str]:
    """
    Verify refresh token and return the subject.
    """
    payload = verify_token(token, TOKEN_TYPE_REFRESH)
    return payload.get("sub") if payload else None


# =====================================================
# Password Utility Functions
# =====================================================
def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Verify a password against its hashed value.
    """
    if not plain_password or not hashed_password:
        return False
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    """
    Hash a password.
    """
    if not password:
        raise ValueError("Password cannot be empty")
    return pwd_context.hash(password)


# =====================================================
# Token Helper Functions
# =====================================================
def create_token_pair(subject: Union[str, Any]) -> Dict[str, Any]:
    """
    Create and return access + refresh token pair.
    """
    access_token = create_access_token(subject)
    refresh_token = create_refresh_token(subject)

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "expires_in": settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60
    }


def is_token_expired(token: str) -> bool:
    """
    Check whether a token is expired using timezone-aware timestamps.
    """
    try:
        payload = jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=[settings.ALGORITHM],
            options={"verify_exp": False}
        )

        exp = payload.get("exp")
        if exp:
            return datetime.now(timezone.utc).timestamp() > exp
        return True

    except JWTError:
        return True


def get_token_remaining_time(token: str) -> Optional[int]:
    """
    Get remaining time (in seconds) before token expiration.
    """
    try:
        payload = jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=[settings.ALGORITHM],
            options={"verify_exp": False}
        )

        exp = payload.get("exp")
        if exp:
            remaining = exp - datetime.now(timezone.utc).timestamp()
            return max(0, int(remaining))
        return None

    except JWTError:
        return None
