import logging
from contextlib import asynccontextmanager
from typing import Dict, List

import uvicorn
from fastapi import FastAPI, HTTPException, Request, Path
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.exceptions import RequestValidationError

# Import models and CRUD operations
from models import (
    LapTimeInput,
    LapTimeDeleteInput,
    TrackNameInput,
    TrackNameResponse,
    ExportResponse,
    DriverResponse,
    User,
    UserResponse,
    UserListResponse,
    driver_to_response,
)
from crud import (
    get_all_drivers,
    add_or_update_lap_time,
    delete_driver_lap_time,
    get_track,
    set_track,
    get_all_users,
    add_user,
    delete_user,
    app_data,
    state_lock,
)
from helpers import export_to_files, update_overall_fastest_lap

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


# --- Lifespan Management ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Application startup...")
    # --- Add startup logic here ---
    # Example: Load initial state from a file, start UDP listener
    # udp_task = asyncio.create_task(run_udp_listener())
    yield
    # --- Add shutdown logic here ---
    logger.info("Application shutdown...")
    # Example: Save state to a file, cancel background tasks
    # udp_task.cancel()
    # try:
    #     await udp_task
    # except asyncio.CancelledError:
    #     logger.info("UDP listener task cancelled.")


app = FastAPI(title="F1 Telemetry API", version="1.0.0", lifespan=lifespan)

# --- Middleware ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow all origins for development
    # In production, restrict this to your frontend's origin:
    # allow_origins=["http://localhost:8080", "http://127.0.0.1:8080", "http://your_domain.com"],
    allow_credentials=True,
    allow_methods=["*"],  # Allow all standard methods
    allow_headers=["*"],  # Allow all headers
)


# --- Custom Exception Handlers ---
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    # Log the validation errors for debugging
    logger.error(f"Validation error for request {request.url}: {exc.errors()}")
    return JSONResponse(
        status_code=422,
        content={"detail": exc.errors()},
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    # Log HTTP exceptions that we raise intentionally
    logger.warning(
        f"HTTP Exception for request {request.url}: Status={exc.status_code}, Detail={exc.detail}"
    )
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail},
    )


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    # Catch-all for unexpected server errors
    logger.exception(
        f"Unhandled exception for request {request.url}: {exc}"
    )  # Log the full traceback
    return JSONResponse(
        status_code=500,
        content={"detail": "An internal server error occurred."},
    )


# --- API Routes ---

# --- User Management Routes ---


@app.get("/api/users", response_model=UserListResponse, tags=["Users"])
async def get_users_endpoint():
    """Gets all defined users."""
    users_internal = await get_all_users()
    # Convert internal User model to UserResponse for the API
    users_response = {
        name: UserResponse(name=user.name, team=user.team)
        for name, user in users_internal.items()
    }
    return UserListResponse(users=users_response)


@app.post("/api/users", response_model=UserResponse, status_code=201, tags=["Users"])
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


@app.delete("/api/users/{user_name}", status_code=200, tags=["Users"])
async def delete_user_endpoint(
    user_name: str = Path(..., description="The name of the user to delete")
):
    """Deletes a user by their name."""
    # URL Decode the name in case it contains special characters
    from urllib.parse import unquote

    decoded_user_name = unquote(user_name)

    deleted = await delete_user(decoded_user_name)
    if deleted:
        return {"message": f"User '{decoded_user_name}' deleted successfully"}
    else:
        raise HTTPException(
            status_code=404, detail=f"User '{decoded_user_name}' not found"
        )


# --- Driver/LapTime/Track Routes ---


@app.get("/api/drivers", response_model=Dict[str, DriverResponse], tags=["Drivers"])
async def get_drivers_endpoint():
    """Gets all current drivers and their fastest lap times."""
    drivers_internal = await get_all_drivers()
    # Convert internal Driver model to the DriverResponse model for the API
    drivers_response = {
        name: driver_to_response(driver) for name, driver in drivers_internal.items()
    }
    return drivers_response


@app.post(
    "/api/laptime",
    response_model=Dict[str, DriverResponse],
    status_code=200,
    tags=["Lap Times"],
)
async def add_lap_time_endpoint(lap_input: LapTimeInput):
    """
    Adds a lap time for a driver. Creates the driver if they don't exist.
    Only the fastest lap per driver is stored and returned.
    Updates the team if it has changed.
    """
    try:
        updated_drivers_internal = await add_or_update_lap_time(lap_input)
        updated_drivers_response = {
            name: driver_to_response(driver)
            for name, driver in updated_drivers_internal.items()
        }
        return updated_drivers_response
    except ValueError as e:  # Catch potential validation errors not caught by Pydantic
        logger.error(f"Value error adding lap time: {e}", exc_info=True)
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception(f"Error adding lap time for {lap_input.name}: {e}")
        raise HTTPException(status_code=500, detail="Failed to add lap time")


@app.delete("/api/laptime", status_code=200, tags=["Lap Times"])
async def delete_lap_time_endpoint(delete_input: LapTimeDeleteInput):
    """
    Deletes the specified lap time for a driver.
    Since only the fastest lap is stored, this removes the driver's time if it matches.
    """
    deleted = await delete_driver_lap_time(delete_input)
    if deleted:
        # Recalculate overall fastest after deletion (already done in crud, but good practice)
        # We don't need to return the full driver list here, just confirmation.
        async with state_lock:
            update_overall_fastest_lap(app_data.drivers)
        return {"message": "Lap time deleted successfully"}
    else:
        raise HTTPException(
            status_code=404, detail="Driver or specified lap time not found"
        )


@app.get("/api/track", response_model=TrackNameResponse, tags=["Track"])
async def get_track_name_endpoint():
    """Gets the currently set track name."""
    track_name = await get_track()
    return TrackNameResponse(name=track_name or "")  # Return empty string if None


@app.post(
    "/api/track", response_model=TrackNameResponse, status_code=200, tags=["Track"]
)
async def set_track_name_endpoint(track_input: TrackNameInput):
    """Sets the track name."""
    if not track_input.name or not track_input.name.strip():
        raise HTTPException(status_code=400, detail="Track name cannot be empty")
    updated_track_name = await set_track(track_input)
    return TrackNameResponse(name=updated_track_name)


@app.get("/api/export", response_model=ExportResponse, tags=["Export"])
async def export_lap_times_endpoint():
    """Exports the current fastest lap times to CSV and JSON files."""
    # Acquire lock only to safely read the necessary data
    async with state_lock:
        current_track = app_data.track_name
        # Pass a deep copy of drivers to the export function
        drivers_copy = {
            name: driver.model_copy(deep=True)
            for name, driver in app_data.drivers.items()
        }

    if not current_track:
        logger.warning("Export failed: Track name not set.")
        # Return a JSON response compatible with the ExportResponse model
        return JSONResponse(
            status_code=400,
            content=ExportResponse(
                success=False, message="No track name set"
            ).model_dump(),
        )

    if not drivers_copy:
        logger.warning("Export called with no driver data.")
        # Decide how to handle - allow empty export or return error?
        return JSONResponse(
            status_code=400,
            content=ExportResponse(
                success=False, message="No lap time data to export"
            ).model_dump(),
        )

    try:
        # Run the potentially blocking file I/O in a separate thread
        # Use the copied data, releasing the lock for the main thread
        primary_filename = await export_to_files(drivers_copy, current_track)
        logger.info(f"Export successful. Primary file: {primary_filename}")
        return ExportResponse(
            success=True, filename=primary_filename, message="Export successful"
        )
    except IOError as e:
        logger.error(f"Export failed during file write: {e}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content=ExportResponse(
                success=False, message=f"Export failed: {e}"
            ).model_dump(),
        )
    except Exception as e:
        logger.exception(f"Unexpected error during export: {e}")
        return JSONResponse(
            status_code=500,
            content=ExportResponse(
                success=False,
                message=f"An unexpected error occurred during export: {e}",
            ).model_dump(),
        )


# --- Static Files Serving ---
# Serve specific admin/display routes first
# Ensure the paths match your folder structure
app.mount("/admin", StaticFiles(directory="static/admin", html=True), name="admin")
app.mount(
    "/display", StaticFiles(directory="static/display", html=True), name="display"
)
app.mount(
    "/admin/users",
    StaticFiles(directory="static/admin/users", html=True),
    name="users",
)
# Serve shared assets (like images) or a root index.html from the main static folder
# This also acts as a fallback for other paths under /
app.mount("/", StaticFiles(directory="static", html=True), name="static")


# --- Run the application ---
if __name__ == "__main__":
    logger.info("Starting Uvicorn server...")
    # Use reload=True for development only
    uvicorn.run("main:app", host="0.0.0.0", port=8080, reload=True)
    # For production, use: uvicorn.run("main:app", host="0.0.0.0", port=8080, workers=4) # Adjust workers as needed
