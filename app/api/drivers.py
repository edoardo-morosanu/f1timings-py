import logging
from typing import Dict, List
from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import JSONResponse, Response

from app.models.models import (
    LapTimeInput,
    LapTimeDeleteInput,
    DriverResponse,
    ExportResponse,
    TrackNameInput,
    TrackNameResponse,
    TrackData,
    # driver_to_response, # No longer needed here, telemetry helper returns DriverResponse
)
from app.services.crud import (
    # get_all_drivers, # No longer used by this endpoint
    add_or_update_lap_time,
    delete_driver_lap_time,
    get_track,
    set_track,
    app_data,
    state_lock,
)
from app.utils.helpers import generate_csv_content, update_overall_fastest_lap
from app.services.track_service import track_service
from app.dependencies.auth import require_auth
from app.api.telemetry import get_live_driver_data_for_api  # Import new helper

# Configure logging
logger = logging.getLogger(__name__)

# Create router
router = APIRouter()


@router.get("/api/drivers", response_model=Dict[str, DriverResponse], tags=["Drivers"])
async def get_drivers_endpoint():
    """Gets all current drivers and their live telemetry data (name, team, last lap time)."""
    # Fetch live driver data compiled from telemetry stores
    drivers_response = await get_live_driver_data_for_api()
    return drivers_response


@router.post(
    "/api/laptime",
    response_model=Dict[str, DriverResponse],
    status_code=200,
    tags=["Lap Times"],
)
async def add_lap_time_endpoint(
    lap_input: LapTimeInput, current_user=Depends(require_auth)
):
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
async def delete_lap_time_endpoint(
    delete_input: LapTimeDeleteInput, current_user=Depends(require_auth)
):
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
async def get_track_name_endpoint(current_user=Depends(require_auth)):
    """Gets the currently set track name with case matching to available tracks."""
    stored_track_name = await get_track()

    if not stored_track_name:
        return TrackNameResponse(name="")

    # Try to find a matching track name from available tracks
    matched_track_name = track_service.find_matching_track_name(stored_track_name)

    if matched_track_name:
        # Update the stored track name to match the actual available track
        if matched_track_name != stored_track_name:
            logger.debug(
                f"Updating stored track name from '{stored_track_name}' to '{matched_track_name}'"
            )
            from app.models.models import TrackNameInput

            await set_track(TrackNameInput(name=matched_track_name))
        return TrackNameResponse(name=matched_track_name)
    else:
        # Return the original name if no match found
        logger.warning(f"No matching track found for stored name '{stored_track_name}'")
        return TrackNameResponse(name=stored_track_name)


@router.post(
    "/api/track", response_model=TrackNameResponse, status_code=200, tags=["Track"]
)
async def set_track_name_endpoint(
    track_input: TrackNameInput, current_user=Depends(require_auth)
):
    """Sets the track name with case matching to available tracks."""
    if not track_input.name or not track_input.name.strip():
        raise HTTPException(status_code=400, detail="Track name cannot be empty")

    input_name = track_input.name.strip()

    # Try to find a matching track name from available tracks
    matched_track_name = track_service.find_matching_track_name(input_name)

    if matched_track_name:
        # Use the matched track name
        from app.models.models import TrackNameInput

        updated_track_name = await set_track(TrackNameInput(name=matched_track_name))
        logger.debug(
            f"Set track to matched name: '{input_name}' -> '{matched_track_name}'"
        )
        return TrackNameResponse(name=updated_track_name)
    else:
        # No match found, but still allow setting (maybe it's a new track)
        updated_track_name = await set_track(track_input)
        logger.warning(f"No matching track found for '{input_name}', using as-is")
        return TrackNameResponse(name=updated_track_name)


@router.get("/api/track/data", response_model=TrackData, tags=["Track"])
async def get_track_data_endpoint(track: str = None):
    """Gets the track data for the specified track or currently set track (no auth required for display)."""
    track_name = track if track else await get_track()
    if not track_name:
        raise HTTPException(status_code=404, detail="No track name set or specified")

    track_data = await track_service.load_track_data(track_name)
    if not track_data:
        raise HTTPException(
            status_code=404, detail=f"Track data not found for '{track_name}'"
        )

    return track_data


@router.get("/api/tracks", response_model=List[str], tags=["Track"])
async def get_available_tracks_endpoint():
    """Gets list of available tracks (no auth required for display)."""
    return track_service.get_available_tracks()


@router.get("/api/export", tags=["Export"])
async def export_lap_times_endpoint(current_user=Depends(require_auth)):
    """Exports the current fastest lap times as a downloadable CSV file."""
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
        return JSONResponse(
            status_code=400,
            content={"error": "No track name set"},
        )

    if not drivers_copy:
        logger.warning("Export called with no driver data.")
        return JSONResponse(
            status_code=400,
            content={"error": "No lap time data to export"},
        )

    try:
        # Generate CSV content
        filename, csv_content = await generate_csv_content(drivers_copy, current_track)
        logger.debug(f"Export successful. Filename: {filename}")

        # Return CSV as downloadable file
        return Response(
            content=csv_content,
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )
    except Exception as e:
        logger.exception(f"Unexpected error during export: {e}")
        return JSONResponse(
            status_code=500,
            content={"error": f"An unexpected error occurred during export: {e}"},
        )


# @router.get("/api/session", tags=["Session"])
# async def get_session_endpoint():
#     """Temporary endpoint to get current session data (no auth required)."""
#     try:
#         # Import here to avoid circular imports
#         from app.api.telemetry import enhanced_session_data_store
        
#         async with state_lock:
#             session_data = {
#                 "track_name": app_data.track_name,
#                 "drivers_count": len(app_data.drivers),
#                 "drivers": {
#                     name: {
#                         "name": driver.name,
#                         "team": driver.team,
#                         "fastest_lap": driver.fastest_lap,
#                         "position": driver.position,
#                         "car_number": driver.car_number
#                     }
#                     for name, driver in app_data.drivers.items()
#                 },
#                 "session_info": enhanced_session_data_store if enhanced_session_data_store else None
#             }
        
#         logger.debug("Session data retrieved successfully")
#         return session_data
        
#     except Exception as e:
#         logger.exception(f"Error retrieving session data: {e}")
#         raise HTTPException(status_code=500, detail="Failed to retrieve session data")
