import asyncio
import logging
from typing import Dict, Optional

from models import (
    AppData,
    Driver,
    LapTime,
    LapTimeInput,
    LapTimeDeleteInput,
    TrackNameInput,
)
from helpers import update_overall_fastest_lap

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- State Management ---
# Simple in-memory storage with an asyncio Lock for async safety
# In a real app, you might use a database or a more robust state management solution
app_data = AppData()
# Lock to prevent race conditions when multiple requests modify the state
# Use asyncio.Lock because FastAPI runs in an async context
state_lock = asyncio.Lock()

# --- CRUD Functions (Interact with app_data) ---


async def get_all_drivers() -> Dict[str, Driver]:
    """Returns a copy of the current drivers dictionary."""
    async with state_lock:
        # Return a deep copy to prevent modifications outside the lock affecting state
        # Pydantic's model_copy is good for this
        return {
            name: driver.model_copy(deep=True)
            for name, driver in app_data.drivers.items()
        }


async def add_or_update_lap_time(lap_input: LapTimeInput) -> Dict[str, Driver]:
    """Adds a new driver or updates an existing driver's lap time."""
    async with state_lock:
        driver = app_data.drivers.get(lap_input.name)

        if not driver:
            # Create new driver
            driver = Driver(name=lap_input.name, team=lap_input.team)
            app_data.drivers[lap_input.name] = driver
            logger.info(f"Created new driver: {lap_input.name}")

        # Update the driver's lap time (only keeps fastest) and team
        updated = driver.update_lap(lap_input.time, lap_input.team)
        if updated:
            logger.info(
                f"Updated fastest lap for {driver.name} to {driver.fastest_lap.time if driver.fastest_lap else 'None'}"
            )
        else:
            logger.info(
                f"New lap {lap_input.time} not faster than existing {driver.fastest_lap.time if driver.fastest_lap else 'None'} for {driver.name}"
            )

        # Recalculate overall fastest lap across all drivers
        update_overall_fastest_lap(app_data.drivers)

        # Return a copy of the updated state
        return {name: d.model_copy(deep=True) for name, d in app_data.drivers.items()}


async def delete_driver_lap_time(delete_input: LapTimeDeleteInput) -> bool:
    """Deletes a specific lap time for a driver. Since we only store the
    fastest, this effectively removes the driver's time if it matches."""
    async with state_lock:
        driver = app_data.drivers.get(delete_input.name)
        lap_deleted = False

        if (
            driver
            and driver.fastest_lap
            and driver.fastest_lap.time == delete_input.time
        ):
            # Remove the fastest lap
            driver.fastest_lap = None
            lap_deleted = True
            logger.info(
                f"Deleted lap time {delete_input.time} for driver {delete_input.name}"
            )

            # Optional: Remove driver if they now have no lap time?
            # Check if you want to keep driver entries even without times
            # if not driver.fastest_lap: # Check other potential fields if needed
            #     del app_data.drivers[delete_input.name]
            #     logger.info(f"Removed driver {delete_input.name} as they have no laps.")

        if lap_deleted:
            # Recalculate overall fastest lap
            update_overall_fastest_lap(app_data.drivers)
            return True  # Indicate success

        return False  # Driver or specific lap time not found


async def get_track() -> Optional[str]:
    """Gets the current track name."""
    async with state_lock:
        return app_data.track_name


async def set_track(track_input: TrackNameInput) -> str:
    """Sets the current track name."""
    async with state_lock:
        app_data.track_name = track_input.name
        logger.info(f"Track name set to: {app_data.track_name}")
        return app_data.track_name
