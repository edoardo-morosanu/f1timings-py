import logging
from fastapi import APIRouter, HTTPException, Path
from urllib.parse import unquote

from app.models.models import User, UserResponse, UserListResponse
from app.services.crud import get_all_users, add_user, delete_user

# Configure logging
logger = logging.getLogger(__name__)

# Create router
router = APIRouter(tags=["Users"])

@router.get("/api/users", response_model=UserListResponse)
async def get_users_endpoint():
    """Gets all defined users."""
    users_internal = await get_all_users()
    # Convert internal User model to UserResponse for the API
    users_response = {
        name: UserResponse(name=user.name, team=user.team)
        for name, user in users_internal.items()
    }
    return UserListResponse(users=users_response)

@router.post("/api/users", response_model=UserResponse, status_code=201)
async def add_user_endpoint(user_input: User):
    """Adds a new user or updates the team if the user already exists."""
    try:
        # The add_user crud function now handles adding/updating
        await add_user(user_input)
        # Return the details of the added/updated user
        return UserResponse(name=user_input.name, team=user_input.team)
    except ValueError as e:  # Catch potential validation errors from model
        logger.error(f"Value error adding user: {e}", exc_info=True)
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception(f"Error adding user {user_input.name}: {e}")
        raise HTTPException(status_code=500, detail="Failed to add user")

@router.delete("/api/users/{user_name}", status_code=200)
async def delete_user_endpoint(
    user_name: str = Path(..., description="The name of the user to delete")
):
    """Deletes a user by their name."""
    # URL Decode the name in case it contains special characters
    decoded_user_name = unquote(user_name)

    deleted = await delete_user(decoded_user_name)
    if deleted:
        return {"message": f"User '{decoded_user_name}' deleted successfully"}
    else:
        raise HTTPException(
            status_code=404, detail=f"User '{decoded_user_name}' not found"
        )
