import asyncio
import logging
from typing import Dict, Optional
from models import (
    LapTimeInput,
    LapTimeDeleteInput,
    TrackNameInput,
    Driver,
    LapTime,
    User,
    UserResponse,
)
from helpers import update_overall_fastest_lap

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- Application State ---
class AppData:
    """Holds the application's in-memory state."""

    def __init__(self):
        self.drivers: Dict[str, Driver] = {}
        self.track_name: Optional[str] = None
        self.users: Dict[str, User] = {}

app_data = AppData()
state_lock = asyncio.Lock()

# WebSocket connection manager will be imported and used for broadcasting
# This is a forward reference which will be populated at runtime
websocket_manager = None

def set_websocket_manager(manager):
    """Set the WebSocket manager to be used for broadcasting.
    This function is called from main.py during startup."""
    global websocket_manager
    websocket_manager = manager
    print(f"WebSocket manager set: {manager}")

# --- User CRUD Operations ---

async def get_all_users() -> Dict[str, User]:
    """Returns all defined users."""
    async with state_lock:
        return app_data.users.copy()

async def add_user(user_input: User) -> Dict[str, User]:
    """Adds a new user or updates the team if the user exists."""
    global websocket_manager
    
    async with state_lock:
        user_key = user_input.name
        if user_key in app_data.users:
            logger.info(
                f"Updating team for existing user '{user_key}' to '{user_input.team}'."
            )
        else:
            logger.info(f"Adding new user '{user_key}' with team '{user_input.team}'.")
        app_data.users[user_key] = user_input
        
        # Broadcast the update to all connected clients
        if websocket_manager:
            await websocket_manager.broadcast({
                "type": "user_update",
                "action": "add",
                "data": {
                    "name": user_input.name,
                    "team": user_input.team
                }
            })
        
        return app_data.users.copy()

async def delete_user(user_name: str) -> bool:
    """Deletes a user by name. Returns True if deleted, False otherwise."""
    global websocket_manager
    
    async with state_lock:
        if user_name in app_data.users:
            del app_data.users[user_name]
            logger.info(f"Deleted user '{user_name}'.")
            
            # Broadcast the deletion to all connected clients
            if websocket_manager:
                await websocket_manager.broadcast({
                    "type": "user_update",
                    "action": "delete",
                    "data": {
                        "name": user_name
                    }
                })
            
            return True
        else:
            logger.warning(f"Attempted to delete non-existent user '{user_name}'.")
            return False

# --- Driver/LapTime/Track CRUD Operations ---

async def get_all_drivers() -> Dict[str, Driver]:
    """Returns all current drivers and their data."""
    async with state_lock:
        return {
            name: driver.model_copy(deep=True)
            for name, driver in app_data.drivers.items()
        }

async def add_or_update_lap_time(lap_input: LapTimeInput) -> Dict[str, Driver]:
    """Adds or updates a lap time for a driver."""
    global websocket_manager
    
    async with state_lock:
        driver_name = lap_input.name
        try:
            new_lap = LapTime(time=lap_input.time, is_fastest=False)
        except ValueError as e:
            logger.error(
                f"Invalid time format provided for {driver_name}: {lap_input.time} - {e}"
            )
            raise ValueError(f"Invalid time format: {lap_input.time}")

        is_new_driver = driver_name not in app_data.drivers
        is_faster_lap = False
        
        if is_new_driver:
            app_data.drivers[driver_name] = Driver(
                name=driver_name, team=lap_input.team, fastest_lap=new_lap
            )
            logger.info(
                f"Created new driver '{driver_name}' with lap time {new_lap.time}."
            )
        else:
            driver = app_data.drivers[driver_name]
            team_updated = False
            
            if driver.team != lap_input.team:
                logger.info(
                    f"Updating team for driver '{driver_name}' from '{driver.team}' to '{lap_input.team}'."
                )
                driver.team = lap_input.team
                team_updated = True

            if (
                driver.fastest_lap is None
                or new_lap.time_seconds < driver.fastest_lap.time_seconds
            ):
                driver.fastest_lap = new_lap
                logger.info(
                    f"Updated fastest lap for '{driver_name}' to {new_lap.time}."
                )
                is_faster_lap = True
            else:
                logger.info(
                    f"New lap time {new_lap.time} for '{driver_name}' is not faster than existing {driver.fastest_lap.time}."
                )

        update_overall_fastest_lap(app_data.drivers)
        
        # Broadcast the update to all connected clients
        if websocket_manager:
            await websocket_manager.broadcast({
                "type": "laptime_update",
                "action": "add" if is_new_driver else "update",
                "data": {
                    "name": driver_name,
                    "team": lap_input.team,
                    "time": new_lap.time,
                    "time_seconds": new_lap.time_seconds,
                    "is_faster": is_faster_lap,
                    "is_overall_fastest": new_lap.is_fastest
                }
            })
        
        return {
            name: driver.model_copy(deep=True)
            for name, driver in app_data.drivers.items()
        }

async def delete_driver_lap_time(delete_input: LapTimeDeleteInput) -> bool:
    """
    Deletes the stored lap time for a driver if the provided time matches.
    Returns True if the lap was found and deleted, False otherwise.
    """
    global websocket_manager
    
    async with state_lock:
        driver_name = delete_input.name
        time_to_delete_str = delete_input.time

        if driver_name in app_data.drivers:
            driver = app_data.drivers[driver_name]
            if driver.fastest_lap:
                try:
                    temp_lap_for_comparison = LapTime(time=time_to_delete_str)
                    time_to_delete_sec = temp_lap_for_comparison.time_seconds
                except ValueError:
                    logger.warning(
                        f"Invalid time format '{time_to_delete_str}' provided for deletion for driver '{driver_name}'."
                    )
                    return False

                if abs(driver.fastest_lap.time_seconds - time_to_delete_sec) < 0.0001:
                    logger.info(
                        f"Deleting lap time {driver.fastest_lap.time} for driver '{driver_name}'."
                    )
                    driver.fastest_lap = None
                    update_overall_fastest_lap(app_data.drivers)
                    
                    # Broadcast the deletion to all connected clients
                    if websocket_manager:
                        await websocket_manager.broadcast({
                            "type": "laptime_update",
                            "action": "delete",
                            "data": {
                                "name": driver_name,
                                "time": time_to_delete_str
                            }
                        })
                    
                    return True
                else:
                    logger.warning(
                        f"Lap time '{time_to_delete_str}' provided for deletion does not match stored time '{driver.fastest_lap.time}' for driver '{driver_name}'."
                    )
                    return False
            else:
                logger.warning(
                    f"Attempted to delete lap time for driver '{driver_name}' but they have no recorded lap."
                )
                return False
        else:
            logger.warning(
                f"Attempted to delete lap time for non-existent driver '{driver_name}'."
            )
            return False

async def get_track() -> Optional[str]:
    """Gets the current track name."""
    async with state_lock:
        return app_data.track_name

async def set_track(track_input: TrackNameInput) -> str:
    """Sets the track name and clears existing driver data."""
    global websocket_manager
    
    async with state_lock:
        new_track_name = track_input.name.strip()
        if app_data.track_name != new_track_name:
            logger.info(
                f"Setting track to '{new_track_name}'. Clearing previous driver data."
            )
            app_data.track_name = new_track_name
            app_data.drivers.clear()
            
            # Broadcast the track update to all connected clients
            if websocket_manager:
                await websocket_manager.broadcast({
                    "type": "track_update",
                    "action": "set",
                    "data": {
                        "name": new_track_name
                    }
                })
            
        else:
            logger.info(f"Track name '{new_track_name}' is already set.")
        return app_data.track_name
