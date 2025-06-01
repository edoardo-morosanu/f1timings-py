from fastapi import HTTPException, Request, Depends, status
from fastapi.responses import RedirectResponse
from typing import Optional, Dict, Any
import logging

from app.services.auth import get_session

logger = logging.getLogger(__name__)


def get_session_id_from_request(request: Request) -> Optional[str]:
    """Extract session ID from request cookies."""
    return request.cookies.get("session_id")


def get_current_user(request: Request) -> Optional[Dict[str, Any]]:
    """Get current authenticated user from session."""
    session_id = get_session_id_from_request(request)
    if not session_id:
        return None

    session_data = get_session(session_id)
    if not session_data:
        return None

    return {"username": session_data["username"]}


def require_auth(request: Request) -> Dict[str, Any]:
    """Dependency that requires authentication. Raises HTTP 401 if not authenticated."""
    user = get_current_user(request)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated"
        )
    return user


def require_auth_redirect(request: Request) -> Dict[str, Any]:
    """
    Dependency that requires authentication but redirects to login instead of raising HTTP error.
    Useful for HTML pages.
    """
    user = get_current_user(request)
    if not user:
        # For admin pages, redirect to login with the current path as 'next'
        login_url = f"/login?next={request.url.path}"
        raise HTTPException(
            status_code=status.HTTP_302_FOUND,
            detail="Redirecting to login",
            headers={"Location": login_url},
        )
    return user


async def check_admin_auth_middleware(request: Request, call_next):
    """
    Middleware to check authentication for admin routes.
    Redirects to login page if not authenticated.
    """
    path = request.url.path

    # Only check auth for admin paths (but not the login page itself)
    if path.startswith("/admin") and not path.startswith("/login"):
        user = get_current_user(request)
        if not user:
            # Redirect to login with the current path as 'next'
            login_url = f"/login?next={path}"
            return RedirectResponse(url=login_url, status_code=302)

    # Continue with the request
    response = await call_next(request)
    return response
