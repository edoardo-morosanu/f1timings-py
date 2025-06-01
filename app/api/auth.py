import logging
from fastapi import APIRouter, HTTPException, Request, Form, Depends
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel
from typing import Optional

from app.services.auth import (
    authenticate_user,
    create_session,
    delete_session,
    get_active_sessions_count,
    get_active_sessions_info,
    get_admin_users_list,
    add_admin_user,
    change_password,
)
from app.dependencies.auth import (
    get_current_user,
    get_session_id_from_request,
    require_auth,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Authentication"])


class LoginRequest(BaseModel):
    username: str
    password: str


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


class CreateUserRequest(BaseModel):
    username: str
    password: str


@router.post("/api/login")
async def login_api(login_data: LoginRequest):
    """API endpoint for login."""
    user = authenticate_user(login_data.username, login_data.password)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid username or password")

    session_id = create_session(user["username"])

    # Return success with session info
    response = JSONResponse(
        content={
            "success": True,
            "message": "Login successful",
            "username": user["username"],
        }
    )

    # Set session cookie
    response.set_cookie(
        key="session_id",
        value=session_id,
        max_age=24 * 60 * 60,  # 24 hours
        httponly=True,
        secure=False,  # Set to True in production with HTTPS
        samesite="lax",
    )

    return response


@router.post("/api/logout")
async def logout_api(request: Request):
    """API endpoint for logout."""
    session_id = get_session_id_from_request(request)
    if session_id:
        delete_session(session_id)

    response = JSONResponse(content={"success": True, "message": "Logout successful"})

    # Clear session cookie
    response.delete_cookie(key="session_id")

    return response


@router.get("/api/auth/status")
async def auth_status(request: Request):
    """Check authentication status."""
    user = get_current_user(request)
    if user:
        return {
            "authenticated": True,
            "username": user["username"],
            "active_sessions": get_active_sessions_count(),
            "session_info": "Multiple admins can be logged in simultaneously",
        }
    else:
        return {"authenticated": False}


@router.post("/api/auth/change-password")
async def change_password_api(
    request: ChangePasswordRequest, current_user=Depends(require_auth)
):
    """Change password for the current user."""
    # Verify current password
    if not authenticate_user(current_user["username"], request.current_password):
        raise HTTPException(status_code=400, detail="Current password is incorrect")

    # Change password
    success = change_password(current_user["username"], request.new_password)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to change password")

    return {"success": True, "message": "Password changed successfully"}


@router.post("/api/auth/create-user")
async def create_user_api(
    request: CreateUserRequest, current_user=Depends(require_auth)
):
    """Create a new admin user (requires existing admin)."""
    success = add_admin_user(request.username, request.password)
    if not success:
        raise HTTPException(status_code=400, detail="User already exists")

    return {
        "success": True,
        "message": f"User '{request.username}' created successfully",
    }


@router.get("/api/auth/sessions")
async def get_sessions_api(current_user=Depends(require_auth)):
    """Get information about all active sessions (admin only)."""
    return {
        "active_sessions": get_active_sessions_info(),
        "total_count": get_active_sessions_count(),
    }


@router.get("/api/auth/users")
async def get_admin_users_api(current_user=Depends(require_auth)):
    """Get list of all admin users (admin only)."""
    return {
        "admin_users": get_admin_users_list(),
        "current_user": current_user["username"],
    }
