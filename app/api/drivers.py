import logging
from typing import Dict
from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

from app.models.models import (
    LapTimeInput, 
    LapTimeDeleteInput, 
    DriverResponse, 
    ExportResponse, 
    TrackNameInput, 
    TrackNameResponse,
    driver_to_response
)
from app.services.crud import (
    get_all_drivers, 
    add_or_update_lap_time, 
    delete_driver_lap_time, 
    get_track, 
    set_track,
    app_data,
    state_lock
)
from app.utils.helpers import export_to_files, update_overall_fastest_lap

# Configure logging
logger = logging.getLogger(__name__)

# Create router
router = APIRouter()

@router.get("/api/drivers", response_model=Dict[str, DriverResponse], tags=["Drivers"])
async def get_drivers_endpoint():
    """Gets all current drivers and their fastest lap times."""
    drivers_internal = await get_all_drivers()
    # Convert internal Driver model to the DriverResponse model for the API
    drivers_response = {
        name: driver_to_response(driver) for name, driver in drivers_internal.items()
    }
    return drivers_response

@router.post(
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

@router.delete("/api/laptime", status_code=200, tags=["Lap Times"])
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

@router.get("/api/track", response_model=TrackNameResponse, tags=["Track"])
async def get_track_name_endpoint():
    """Gets the currently set track name."""
    track_name = await get_track()
    return TrackNameResponse(name=track_name or "")  # Return empty string if None

@router.post(
    "/api/track", response_model=TrackNameResponse, status_code=200, tags=["Track"]
)
async def set_track_name_endpoint(track_input: TrackNameInput):
    """Sets the track name."""
    if not track_input.name or not track_input.name.strip():
        raise HTTPException(status_code=400, detail="Track name cannot be empty")
    updated_track_name = await set_track(track_input)
    return TrackNameResponse(name=updated_track_name)

@router.get("/api/export", response_model=ExportResponse, tags=["Export"])
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
