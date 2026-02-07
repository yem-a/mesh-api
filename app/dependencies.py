# app/dependencies.py

"""
Authentication dependency for FastAPI.

Validates Supabase JWTs and extracts user_id for all protected endpoints.
"""

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from app.database import supabase_admin

security = HTTPBearer()


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> str:
    """
    Validate the Supabase JWT and return the user_id.

    Uses supabase_admin.auth.get_user() to verify the token.
    This is a sync function -- FastAPI auto-runs it in a threadpool.
    """
    token = credentials.credentials

    try:
        user_response = supabase_admin.auth.get_user(token)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if user_response is None or user_response.user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return user_response.user.id
