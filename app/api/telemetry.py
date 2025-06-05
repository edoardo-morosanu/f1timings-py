import asyncio
import os
import socket
import threading
import time
import logging
from typing import Optional, Dict, Any, List

# Configure basic logging
logging.basicConfig(
    level=logging.DEBUG, format="%(asctime)s - %(levelname)s - %(message)s"
)  # Changed to DEBUG
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)  # Ensure DEBUG logs from this module are shown

# Attempt to silence the f1-24-telemetry library's own logger (can be re-enabled if too noisy)
# logging.getLogger('f1_24_telemetry').setLevel(logging.ERROR)

# Attempt to silence Uvicorn's default loggers (can be re-enabled if too noisy)
# logging.getLogger('uvicorn.error').setLevel(logging.CRITICAL)
# logging.getLogger('uvicorn.access').setLevel(logging.INFO) # Access logs can be useful
# logging.getLogger('uvicorn').setLevel(logging.INFO)

import os
import traceback
from dotenv import load_dotenv
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from app.models.models import DriverResponse, LapTime  # Moved import here


# --- Pydantic Models for Live Telemetry Endpoint ---
class LiveDriverData(BaseModel):
    name: str
    team: str
    worldPositionX: Optional[float] = None
    worldPositionY: Optional[float] = None
    worldPositionZ: Optional[float] = None


class SessionInfo(BaseModel):
    trackId: Optional[int] = None
    gamePaused: Optional[bool] = None


class LiveTelemetryResponse(BaseModel):
    drivers: List[LiveDriverData]
    sessionInfo: Optional[SessionInfo] = None
    activeDriversCount: int


# Load environment variables from .env file
load_dotenv()

telemetry_router = APIRouter()  # Moved here

# --- Team ID to Name Mapping ---
# Based on common F1 2024 team IDs. This might need adjustment.
TEAM_ID_MAP = {
    0: "Mercedes-AMG Petronas F1 Team",
    1: "Scuderia Ferrari",
    2: "Oracle Red Bull Racing",
    3: "Williams Racing",
    4: "Aston Martin Aramco F1 Team",
    5: "BWT Alpine F1 Team",
    6: "Visa Cash App RB F1 Team",  # Formerly Scuderia AlphaTauri
    7: "MoneyGram Haas F1 Team",
    8: "McLaren F1 Team",
    9: "Stake F1 Team Kick Sauber",  # Formerly Alfa Romeo Racing
    # Placeholder for unknown or player teams if not in this list
    # Values like 41 for 'Haas F1 Team ES' (presumably esports) or 85 for 'Mercedes AMG Esports' also exist in some contexts.
    # For simplicity, focusing on the main constructor teams.
    255: "Unknown Team",  # Often used for no team or invalid
}


# --- Utility Functions ---
def ms_to_laptime_str(ms: Optional[int]) -> str:
    if (
        ms is None or ms <= 0
    ):  # Handle cases where lap time might be 0, None, or invalid
        # Depending on requirements, could return None, an empty string, or a placeholder
        return (
            "0:00.000"  # Or perhaps better to indicate no valid time, e.g., "--:--.---"
        )

    total_seconds = ms / 1000.0
    minutes = int(total_seconds // 60)
    seconds = int(total_seconds % 60)
    milliseconds = int(round((total_seconds - (minutes * 60) - seconds) * 1000))
    # Ensure milliseconds don't round up to 1000, which would break formatting
    if milliseconds >= 1000:
        milliseconds = 999
    return f"{minutes}:{seconds:02d}.{milliseconds:03d}"


# --- New Helper Function for /api/drivers ---
async def get_live_driver_data_for_api() -> Dict[str, DriverResponse]:
    """
    Assembles live driver data from telemetry stores for the API.
    Returns a dictionary of DriverResponse objects, keyed by driver name.
    """
    # Access global stores; ensure they are declared global if modified, but here we only read.
    # It's assumed participant_data_store, lap_data_store, active_drivers_count are accessible in this scope.

    drivers_api_response: Dict[str, DriverResponse] = {}

    # Ensure participant_data_store is a list and active_drivers_count is an int
    logger.debug(
        f"[get_live_driver_data_for_api] Called. active_drivers_count: {active_drivers_count}, participant_data_store items: {len(participant_data_store) if isinstance(participant_data_store, list) else 'Not a list'}"
    )
    if (
        not isinstance(participant_data_store, list)
        or not isinstance(active_drivers_count, int)
        or active_drivers_count == 0
    ):
        logger.debug(
            "[get_live_driver_data_for_api] Participant data store not ready, not a list, or no active drivers. Returning empty."
        )
        return drivers_api_response

    # Iterate up to the number of active drivers, ensuring bounds are respected for stores
    for i in range(min(active_drivers_count, len(participant_data_store))):
        participant = participant_data_store[i]

        # Check if lap_data_store is populated and index is valid
        lap_data = None
        if isinstance(lap_data_store, list) and i < len(lap_data_store):
            lap_data = lap_data_store[i]

        logger.debug(
            f"[get_live_driver_data_for_api] Loop index {i}: Raw Participant Data from store: {participant}, Raw Lap Data from store: {lap_data}"
        )
        if (
            not participant
            or not isinstance(participant, dict)
            or not participant.get("name")
            or participant.get("name") == "N/A"
        ):  # Removed startswith("Driver_") check
            logger.debug(
                f"[get_live_driver_data_for_api] Skipping index {i}: Participant data invalid, name is fallback/placeholder ('{participant.get('name') if participant else 'No PData'}'), or missing."
            )
            continue

        driver_name = participant.get("name", f"Driver {i+1}")
        team_id = participant.get("teamId", 255)
        team_name = TEAM_ID_MAP.get(team_id, "Unknown Team")

        lap_times_list: List[LapTime] = []
        last_lap_ms = lap_data.get("lastLapTimeInMS")
        logger.debug(
            f"[get_live_driver_data_for_api] Driver '{driver_name}' (idx {i}), Extracted lastLapTimeInMS: {last_lap_ms} (type: {type(last_lap_ms)}) "
        )
        if last_lap_ms is not None and isinstance(last_lap_ms, int) and last_lap_ms > 0:
            lap_time_str = ms_to_laptime_str(last_lap_ms)
            # For now, we'll consider this the "fastest" reported in this context,
            # as we only handle one lap time per driver in the current API response structure.
            # A true 'is_fastest' would require session-wide tracking.
            lap_time_obj = LapTime(
                time=lap_time_str, is_fastest=True
            )  # Marking as 'fastest' for display purposes
            lap_times_list.append(lap_time_obj)
        else:
            logger.debug(
                f"[get_live_driver_data_for_api] Driver '{driver_name}' (idx {i}), No valid last lap time found (value: {last_lap_ms}), or it's 0. Lap times list will be empty."
            )

        # Fetch motion data for car position
        motion_data = None
        # Ensure latest_car_positions is a list and index i is valid
        if isinstance(latest_car_positions, list) and i < len(latest_car_positions):
            motion_data = latest_car_positions[i]

        world_x, world_y, world_z = None, None, None
        if motion_data and isinstance(motion_data, dict):
            world_x = motion_data.get("worldPositionX")
            world_y = motion_data.get("worldPositionY")
            world_z = motion_data.get("worldPositionZ")
            logger.debug(
                f"[get_live_driver_data_for_api] Driver '{driver_name}' (idx {i}), MotionData: X={world_x}, Y={world_y}, Z={world_z}"
            )
        else:
            logger.debug(
                f"[get_live_driver_data_for_api] Driver '{driver_name}' (idx {i}), No motion data found or motion_data is not a dict. latest_car_positions type: {type(latest_car_positions)}, len: {len(latest_car_positions) if isinstance(latest_car_positions, list) else 'N/A'}, motion_data for index {i}: {motion_data}"
            )

        drivers_api_response[driver_name] = DriverResponse(
            name=driver_name,
            team=team_name,
            lap_times=lap_times_list,
            world_x=world_x,
            world_y=world_y,
            world_z=world_z,
        )
        logger.debug(
            f"get_live_driver_data_for_api: Processed driver '{driver_name}', Team: '{team_name}', Laps: {len(lap_times_list)}"
        )

    if not drivers_api_response and active_drivers_count > 0:
        logger.warning(
            "[get_live_driver_data_for_api] After loop, drivers_api_response is unexpectedly empty despite active_drivers_count > 0."
        )
    elif active_drivers_count > 0:
        logger.info(
            f"[get_live_driver_data_for_api] After loop. Keys in drivers_api_response: {list(drivers_api_response.keys()) if drivers_api_response else 'Empty dict'}"
        )
        logger.info(
            f"[get_live_driver_data_for_api] Compiled data for {len(drivers_api_response)} drivers. Expected to process up to {min(active_drivers_count, len(participant_data_store))} entries."
        )

    # Detailed log of the actual content being returned
    if drivers_api_response:
        for name, driver_data in drivers_api_response.items():
            lap_times_summary = [
                (lt.time, lt.is_fastest) for lt in driver_data.lap_times
            ]
            logger.debug(
                f"[get_live_driver_data_for_api] Returning driver: '{name}', Team: '{driver_data.team}', LapTimes Summary: {lap_times_summary}"
            )
    else:
        logger.debug(
            "[get_live_driver_data_for_api] Returning empty drivers_api_response dict."
        )

    return drivers_api_response


async def get_full_live_telemetry_data() -> LiveTelemetryResponse:
    """Assembles full live telemetry data including driver positions and session info."""
    global participant_data_store, latest_car_positions, session_data_store, active_drivers_count, TEAM_ID_MAP

    live_drivers_list: List[LiveDriverData] = []

    # Ensure participant_data_store is a list and active_drivers_count is an int
    if (
        isinstance(participant_data_store, list)
        and isinstance(active_drivers_count, int)
        and active_drivers_count > 0
    ):
        # Iterate up to the number of active drivers, ensuring bounds are respected for stores
        for i in range(min(active_drivers_count, len(participant_data_store))):
            participant = participant_data_store[i]

            motion = None
            if isinstance(latest_car_positions, list) and i < len(latest_car_positions):
                motion = latest_car_positions[i]

            if (
                not participant
                or not isinstance(participant, dict)
                or not participant.get("name")
            ):
                logger.debug(
                    f"get_full_live_telemetry_data: Skipping driver index {i}, missing participant data or name."
                )
                continue

            driver_name = participant.get("name", f"Driver {i+1}")
            team_id = participant.get("teamId", 255)
            team_name = TEAM_ID_MAP.get(team_id, "Unknown Team")

            pos_x, pos_y, pos_z = None, None, None
            if motion and isinstance(motion, dict):
                pos_x = motion.get("worldPositionX")
                pos_y = motion.get("worldPositionY")
                pos_z = motion.get("worldPositionZ")

            live_drivers_list.append(
                LiveDriverData(
                    name=driver_name,
                    team=team_name,
                    worldPositionX=pos_x,
                    worldPositionY=pos_y,
                    worldPositionZ=pos_z,
                )
            )
    else:
        logger.debug(
            "get_full_live_telemetry_data: Participant data store not ready or no active drivers."
        )    
        current_session_info = None
    if isinstance(session_data_store, dict):
        current_session_info = SessionInfo(
            trackId=session_data_store.get("trackId"),
            gamePaused=bool(session_data_store.get("gamePaused", 0)),  # Ensure boolean
        )
    else:
        logger.debug(
            "get_full_live_telemetry_data: Session data store not ready or not a dict."
        )

    final_active_drivers_count = (
        active_drivers_count if isinstance(active_drivers_count, int) else 0
    )
    logger.info(
        f"get_full_live_telemetry_data: Compiled data for {len(live_drivers_list)} drivers. Session trackId: {current_session_info.trackId if current_session_info else 'N/A'}. Active drivers: {final_active_drivers_count}"
    )

    return LiveTelemetryResponse(
        drivers=live_drivers_list,
        sessionInfo=current_session_info,
        activeDriversCount=final_active_drivers_count,
    )


@telemetry_router.get(
    "/live_data_v2", response_model=LiveTelemetryResponse, tags=["Telemetry"]
)
async def live_data_endpoint():
    """Provides live telemetry data including driver positions, names, teams, and session info."""
    return await get_full_live_telemetry_data()


# Global flag and event to control the listener thready listener
try:
    from f1_24_telemetry.listener import TelemetryListener

    F1_TELEMETRY_AVAILABLE = True
except ImportError:
    TelemetryListener = None  # type: ignore
    F1_TELEMETRY_AVAILABLE = False
    print("WARNING: f1_24_telemetry library not found. UDP Telemetry will not work.")
    print(
        "Please install it, possibly using: pip install git+https://github.com/xavierdubuc/f1-24-telemetry.git"
    )

# Global state for the telemetry listener
listener_thread: Optional[threading.Thread] = None
listener_stop_event: Optional[threading.Event] = None
listener_port: Optional[int] = None
listener_host: Optional[str] = None
listener_error: Optional[str] = None
active_drivers_count = 0  # Updated by participant packets

# New global variables for detailed telemetry data
latest_car_positions: list = []  # Will store dicts of car positions
participant_data_store: list = []  # Will store dicts of participant info
session_data_store: dict = {}  # Will store session info
lap_data_store: list = []  # To store lap data for each car


class TelemetryStatus(BaseModel):
    running: bool
    host: Optional[str] = None
    port: Optional[int] = None
    active_drivers: int = 0
    error: Optional[str] = None


class LiveDataResponse(BaseModel):
    session: Optional[dict] = None
    participants: Optional[list] = None  # List of participant data dicts
    positions: Optional[list] = None  # List of car position dicts
    laps: Optional[list] = None  # List of car lap data dicts
    active_drivers: int
    is_running: bool
    error: Optional[str] = None


class StartResponse(BaseModel):
    message: str
    host: str
    port: int


def get_local_ip():
    """Helper function to get the local IP address."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.settimeout(0.1)  # Prevent long block if no network
    try:
        # Doesn't actually have to connect, uses OS routing table
        s.connect(("10.255.255.255", 1))
        IP = s.getsockname()[0]
    except Exception:
        try:
            IP = socket.gethostbyname(socket.gethostname())
        except socket.gaierror:
            IP = "127.0.0.1"  # Fallback
    finally:
        s.close()
    return IP


def telemetry_listener_worker(host: str, port: int, stop_event: threading.Event):
    global listener_error, active_drivers_count
    global latest_car_positions, participant_data_store, session_data_store, lap_data_store

    listener_instance = None
    try:
        print(f"Attempting to start UDP telemetry listener on {host}:{port}")
        listener_instance = TelemetryListener(port=port, host=host)
        print(f"UDP Telemetry listener started on {host}:{port}")

        # Ensure stores are initialized (though _clear_listener_state should handle this prior to thread start)
        if not latest_car_positions or len(latest_car_positions) != 22:
            latest_car_positions = [{} for _ in range(22)]
        if not participant_data_store or len(participant_data_store) != 22:
            participant_data_store = [{} for _ in range(22)]
        if not session_data_store:
            session_data_store = {}
        if not lap_data_store or len(lap_data_store) != 22:
            lap_data_store = [{} for _ in range(22)]

        while not stop_event.is_set():
            try:
                packet = listener_instance.get()
                if not packet:
                    logger.warning(
                        "listener_instance.get() returned a null/falsey packet. Skipping."
                    )
                    continue

                logger.debug(
                    f"Listener got a packet of type: {type(packet)}. Has 'header' attribute? {hasattr(packet, 'header')}"
                )

                if hasattr(packet, "header"):
                    packet_id = packet.header.packet_id
                    logger.debug(
                        f"Received packet_id: {packet_id} (type: {type(packet_id)})"
                    )

                    if packet_id == 0:  # MotionData
                        logger.info(
                            f"Processing MotionData (ID 0). Cars: {len(packet.car_motion_data) if hasattr(packet, 'car_motion_data') else 'N/A'}"
                        )
                        # active_drivers_count = sum(1 for car_motion in packet.car_motion_data if car_motion.world_position_x != 0 or car_motion.world_position_y != 0 or car_motion.world_position_z != 0) # This is not the authoritative source for active_drivers_count
                        for i, car_motion in enumerate(packet.car_motion_data):
                            if i < 22:  # Ensure we don't exceed our list size
                                latest_car_positions[i] = {
                                    "worldPositionX": car_motion.world_position_x,
                                    "worldPositionY": car_motion.world_position_y,
                                    "worldPositionZ": car_motion.world_position_z,
                                    "gForceLateral": car_motion.g_force_lateral,
                                    "gForceLongitudinal": car_motion.g_force_longitudinal,
                                    "gForceVertical": car_motion.g_force_vertical,
                                    "yaw": car_motion.yaw,
                                    "pitch": car_motion.pitch,
                                    "roll": car_motion.roll,
                                }
                        logger.debug(
                            f"Updated latest_car_positions for {len(packet.car_motion_data) if hasattr(packet, 'car_motion_data') else 'N/A'} cars. First car X: {latest_car_positions[0].get('worldPositionX') if latest_car_positions and latest_car_positions[0] else 'N/A'}"
                        )

                    elif packet_id == 1:  # SessionData
                        logger.info(
                            f"Processing SessionData (ID 1). Track ID: {packet.track_id if hasattr(packet, 'track_id') else 'N/A'}"
                        )
                        session_data_store.update(
                            {
                                "trackId": packet.track_id,
                                "networkGame": packet.network_game,
                                "gamePaused": packet.game_paused,
                                "sessionType": packet.session_type,
                                "sessionLinkIdentifier": packet.session_link_identifier,  # Added missing snake_case conversion
                                "sessionTimeLeft": packet.session_time_left,
                                "sessionDuration": packet.session_duration,
                                "pitSpeedLimit": packet.pit_speed_limit,
                            }
                        )
                        logger.debug(
                            f"Updated session_data_store. Track ID: {session_data_store.get('trackId')}, Session Type: {session_data_store.get('sessionType')}"
                        )

                    elif packet_id == 2:  # LapData
                        logger.info(
                            f"Processing LapData (ID 2). Cars: {len(packet.lap_data) if hasattr(packet, 'lap_data') else 'N/A'}"
                        )
                        if hasattr(packet, "lap_data"):
                            # Ensure lap_data_store is initialized correctly
                            if (
                                not isinstance(lap_data_store, list)
                                or len(lap_data_store) != 22
                            ):
                                logger.warning(
                                    "lap_data_store is not a list of 22 elements. Re-initializing."
                                )
                                lap_data_store[:] = [{} for _ in range(22)]

                            for i, car_lap_data in enumerate(packet.lap_data):
                                if i < 22:  # Process up to 22 cars
                                    # Combine sector time parts if necessary (assuming library provides them split)
                                    # For f1-24-telemetry, it's usually direct attributes like sector1_time_in_ms
                                    lap_data_store[i] = {
                                        "lastLapTimeInMS": getattr(
                                            car_lap_data, "last_lap_time_in_ms", 0
                                        ),
                                        "currentLapTimeInMS": getattr(
                                            car_lap_data, "current_lap_time_in_ms", 0
                                        ),
                                        "sector1TimeInMS": getattr(
                                            car_lap_data, "sector1_time_in_ms", 0
                                        ),  # Direct attribute
                                        "sector2TimeInMS": getattr(
                                            car_lap_data, "sector2_time_in_ms", 0
                                        ),  # Direct attribute
                                        "lapDistance": getattr(
                                            car_lap_data, "lap_distance", 0.0
                                        ),
                                        "totalDistance": getattr(
                                            car_lap_data, "total_distance", 0.0
                                        ),
                                        "safetyCarDelta": getattr(
                                            car_lap_data, "safety_car_delta", 0.0
                                        ),
                                        "carPosition": getattr(
                                            car_lap_data, "car_position", 0
                                        ),
                                        "currentLapNum": getattr(
                                            car_lap_data, "current_lap_num", 0
                                        ),
                                        "pitStatus": getattr(
                                            car_lap_data, "pit_status", 0
                                        ),
                                        "numPitStops": getattr(
                                            car_lap_data, "num_pit_stops", 0
                                        ),
                                        "sector": getattr(car_lap_data, "sector", 0),
                                        "currentLapInvalid": getattr(
                                            car_lap_data, "current_lap_invalid", 0
                                        ),
                                        "penalties": getattr(
                                            car_lap_data, "penalties", 0
                                        ),
                                        "totalWarnings": getattr(
                                            car_lap_data, "total_warnings", 0
                                        ),
                                        "cornerCuttingWarnings": getattr(
                                            car_lap_data, "corner_cutting_warnings", 0
                                        ),
                                        "gridPosition": getattr(
                                            car_lap_data, "grid_position", 0
                                        ),
                                        "driverStatus": getattr(
                                            car_lap_data, "driver_status", 0
                                        ),
                                        "resultStatus": getattr(
                                            car_lap_data, "result_status", 0
                                        ),
                                        # Best lap time is not in this packet per F1 24 spec.
                                        # If needed, it must be calculated and stored separately by the application.
                                    }
                            logger.debug(
                                f"Updated lap_data_store for {len(packet.lap_data)} cars. First car last lap: {lap_data_store[0].get('lastLapTimeInMS') if lap_data_store and lap_data_store[0] else 'N/A'}"
                            )

                    elif packet_id == 4:  # ParticipantsData
                        num_cars_to_log = (
                            str(packet.num_active_cars)
                            if hasattr(packet, "num_active_cars")
                            else (
                                str(packet.m_numActiveCars)
                                if hasattr(packet, "m_numActiveCars")
                                else "N/A"
                            )
                        )
                        logger.info(
                            f"Processing ParticipantsData (ID 4). Num Active Cars: {num_cars_to_log}"
                        )
                        if hasattr(
                            packet, "num_active_cars"
                        ):  # Check for 'num_active_cars' first
                            active_drivers_count = packet.num_active_cars
                            logger.debug(
                                f"[telemetry_listener_worker] active_drivers_count set to: {active_drivers_count} from packet.num_active_cars"
                            )
                        elif hasattr(
                            packet, "m_numActiveCars"
                        ):  # Fallback to 'm_numActiveCars'
                            active_drivers_count = packet.m_numActiveCars
                            logger.debug(
                                f"[telemetry_listener_worker] active_drivers_count set to: {active_drivers_count} from packet.m_numActiveCars (fallback)"
                            )
                        else:
                            logger.warning(
                                f"[telemetry_listener_worker] PacketParticipantsData (ID 4) received, but NEITHER 'num_active_cars' NOR 'm_numActiveCars' attribute is present. Cannot update active_drivers_count from packet header."
                            )

                        if hasattr(packet, "participants"):
                            # Ensure participant_data_store is initialized as a list of 22 empty dicts if not already
                            # This check is important if the listener starts after some packets have been missed
                            if (
                                not isinstance(participant_data_store, list)
                                or len(participant_data_store) != 22
                            ):
                                logger.warning(
                                    "participant_data_store is not a list of 22 elements. Re-initializing."
                                )
                                participant_data_store[:] = [
                                    {} for _ in range(22)
                                ]  # Modify in place

                            num_to_process = 0
                            if hasattr(packet, "m_numActiveCars"):  # F1 2020+
                                num_to_process = packet.m_numActiveCars
                            elif hasattr(packet, "header") and hasattr(
                                packet.header, "player_car_index"
                            ):  # Fallback for older games
                                num_to_process = len(packet.participants)
                            else:
                                num_to_process = len(
                                    packet.participants
                                )  # Default to length of participants array if count is missing

                            logger.debug(
                                f"ParticipantsData: num_to_process = {num_to_process}, actual len(packet.participants) = {len(packet.participants)}"
                            )

                            # Clear only the relevant portion of the store before repopulating
                            # for i in range(22):
                            #     participant_data_store[i] = {}

                            processed_indices = set()
                            for i in range(
                                min(num_to_process, len(packet.participants), 22)
                            ):
                                participant = packet.participants[i]
                                processed_indices.add(i)
                                try:
                                    name_bytes = getattr(participant, "name", b"")
                                    name_str = (
                                        name_bytes.decode("utf-8", errors="replace")
                                        .split("\x00")[0]
                                        .strip()
                                    )
                                    if (
                                        not name_str
                                        or name_str == "???????????????"
                                        or name_str.lower() == "player"
                                        or name_str.isspace()
                                    ):
                                        race_num = getattr(
                                            participant, "race_number", 0
                                        )
                                        name_str = f"Driver {race_num if race_num != 0 else i + 1}"
                                except Exception as e:
                                    logger.error(
                                        f"Error decoding participant name for index {i}: {e}"
                                    )
                                    race_num = getattr(participant, "race_number", 0)
                                    name_str = (
                                        f"Driver {race_num if race_num != 0 else i + 1}"
                                    )

                                participant_data_store[i] = {
                                    "aiControlled": getattr(
                                        participant, "ai_controlled", 1
                                    ),
                                    "driverId": getattr(participant, "driver_id", 255),
                                    "networkId": getattr(
                                        participant, "network_id", 255
                                    ),
                                    "teamId": getattr(participant, "team_id", 255),
                                    "myTeam": getattr(participant, "my_team", 0),
                                    "raceNumber": getattr(
                                        participant, "race_number", 0
                                    ),
                                    "nationality": getattr(
                                        participant, "nationality", 0
                                    ),
                                    "name": name_str,
                                    "yourTelemetry": getattr(
                                        participant, "your_telemetry", 0
                                    ),
                                    "is_online_player": (
                                        True
                                        if hasattr(participant, "network_id")
                                        and participant.network_id != 0
                                        and participant.network_id != 255
                                        and getattr(participant, "driver_id", 255)
                                        == 255
                                        else False
                                    ),
                                    "raw_name_bytes": (
                                        name_bytes.hex()
                                        if isinstance(name_bytes, bytes)
                                        else ""
                                    ),
                                }
                            # Clear data for cars that are no longer active in this packet
                            for i in range(22):
                                if i not in processed_indices and i >= num_to_process:
                                    participant_data_store[i] = {}

                        logger.info(
                            f"Participant data store updated. Active drivers: {active_drivers_count}. Processed up to {min(num_to_process, len(packet.participants), 22)} participants."
                        )
                        if (
                            participant_data_store
                            and len(participant_data_store) > 0
                            and participant_data_store[0]
                        ):
                            logger.debug(
                                f"First participant after update: Name='{participant_data_store[0].get('name')}', TeamID='{participant_data_store[0].get('teamId')}'"
                            )
                        else:
                            logger.debug(
                                "Participant_data_store is empty or first element is empty after update."
                            )

                    elif packet_id == 2:  # LapData
                        logger.info(
                            f"Processing LapData (ID 2). Cars: {len(packet.lap_data) if hasattr(packet, 'lap_data') else 'N/A'}"
                        )
                        for i, car_lap in enumerate(packet.lap_data):
                            if i < 22:
                                # Combine minute and millisecond parts for sector times
                                sector1_time_ms = (
                                    (car_lap.sector_1_time_minutes_part * 60 * 1000)
                                    + car_lap.sector_1_time_ms_part
                                    if hasattr(car_lap, "sector_1_time_minutes_part")
                                    and hasattr(car_lap, "sector_1_time_ms_part")
                                    else 0
                                )
                                sector2_time_ms = (
                                    (car_lap.sector_2_time_minutes_part * 60 * 1000)
                                    + car_lap.sector_2_time_ms_part
                                    if hasattr(car_lap, "sector_2_time_minutes_part")
                                    and hasattr(car_lap, "sector_2_time_ms_part")
                                    else 0
                                )

                                lap_data_store[i] = {
                                    "lastLapTimeInMS": (
                                        car_lap.last_lap_time_in_ms
                                        if hasattr(car_lap, "last_lap_time_in_ms")
                                        else 0
                                    ),
                                    "currentLapTimeInMS": (
                                        car_lap.current_lap_time_in_ms
                                        if hasattr(car_lap, "current_lap_time_in_ms")
                                        else 0
                                    ),
                                    "sector1TimeInMS": sector1_time_ms,
                                    "sector2TimeInMS": sector2_time_ms,
                                    # Note: spec.h does not explicitly list sector3Time. It's typically calculated.
                                    "lapDistance": (
                                        car_lap.lap_distance
                                        if hasattr(car_lap, "lap_distance")
                                        else 0.0
                                    ),
                                    "totalDistance": (
                                        car_lap.total_distance
                                        if hasattr(car_lap, "total_distance")
                                        else 0.0
                                    ),
                                    "safetyCarDelta": (
                                        car_lap.safety_car_delta
                                        if hasattr(car_lap, "safety_car_delta")
                                        else 0.0
                                    ),
                                    "carPosition": (
                                        car_lap.car_position
                                        if hasattr(car_lap, "car_position")
                                        else 0
                                    ),
                                    "currentLapNum": (
                                        car_lap.current_lap_num
                                        if hasattr(car_lap, "current_lap_num")
                                        else 0
                                    ),
                                    "pitStatus": (
                                        car_lap.pit_status
                                        if hasattr(car_lap, "pit_status")
                                        else 0
                                    ),
                                    "numPitStops": (
                                        car_lap.num_pit_stops
                                        if hasattr(car_lap, "num_pit_stops")
                                        else 0
                                    ),
                                    "sector": (
                                        car_lap.sector
                                        if hasattr(car_lap, "sector")
                                        else 0
                                    ),
                                    "currentLapInvalid": (
                                        car_lap.current_lap_invalid
                                        if hasattr(car_lap, "current_lap_invalid")
                                        else 0
                                    ),
                                    "penalties": (
                                        car_lap.penalties
                                        if hasattr(car_lap, "penalties")
                                        else 0
                                    ),
                                    "totalWarnings": (
                                        car_lap.total_warnings
                                        if hasattr(car_lap, "total_warnings")
                                        else 0
                                    ),  # Corrected from 'warnings'
                                    "cornerCuttingWarnings": (
                                        car_lap.corner_cutting_warnings
                                        if hasattr(car_lap, "corner_cutting_warnings")
                                        else 0
                                    ),
                                    "numUnservedDriveThroughPens": (
                                        car_lap.num_unserved_drive_through_pens
                                        if hasattr(
                                            car_lap, "num_unserved_drive_through_pens"
                                        )
                                        else 0
                                    ),
                                    "numUnservedStopGoPens": (
                                        car_lap.num_unserved_stop_go_pens
                                        if hasattr(car_lap, "num_unserved_stop_go_pens")
                                        else 0
                                    ),
                                    "gridPosition": (
                                        car_lap.grid_position
                                        if hasattr(car_lap, "grid_position")
                                        else 0
                                    ),
                                    "driverStatus": (
                                        car_lap.driver_status
                                        if hasattr(car_lap, "driver_status")
                                        else 0
                                    ),
                                    "resultStatus": (
                                        car_lap.result_status
                                        if hasattr(car_lap, "result_status")
                                        else 0
                                    ),
                                    "pitLaneTimerActive": (
                                        car_lap.pit_lane_timer_active
                                        if hasattr(car_lap, "pit_lane_timer_active")
                                        else 0
                                    ),
                                    "pitLaneTimeInLaneInMS": (
                                        car_lap.pit_lane_time_in_lane_in_ms
                                        if hasattr(
                                            car_lap, "pit_lane_time_in_lane_in_ms"
                                        )
                                        else 0
                                    ),
                                    "pitStopTimerInMS": (
                                        car_lap.pit_stop_timer_in_ms
                                        if hasattr(car_lap, "pit_stop_timer_in_ms")
                                        else 0
                                    ),
                                    "pitStopShouldServePen": (
                                        car_lap.pit_stop_should_serve_pen
                                        if hasattr(car_lap, "pit_stop_should_serve_pen")
                                        else 0
                                    ),
                                    "speedTrapFastestSpeed": (
                                        car_lap.speed_trap_fastest_speed
                                        if hasattr(car_lap, "speed_trap_fastest_speed")
                                        else 0.0
                                    ),
                                    "speedTrapFastestLap": (
                                        car_lap.speed_trap_fastest_lap
                                        if hasattr(car_lap, "speed_trap_fastest_lap")
                                        else 0
                                    ),
                                }
                        logger.debug(
                            f"Updated lap_data_store for {len(packet.lap_data) if hasattr(packet, 'lap_data') else 'N/A'} cars."
                        )
                    elif packet_id == 7:  # CarStatusData
                        # logger.info("CarStatus Packet Received")
                        # Process CarStatusData if needed. For now, we are not storing it globally.
                        logger.info(
                            f"Processing CarStatusData (ID 7). Cars: {len(packet.car_status_data) if hasattr(packet, 'car_status_data') else 'N/A'}"
                        )
                        # Example: if hasattr(packet, 'car_status_data'):
                        #     for i, status_data in enumerate(packet.car_status_data):
                        #         if i < 22:
                        #             # car_status_store[i] = { ... extract fields ... }
                        #             pass # Placeholder
                        pass
                else:
                    logger.warning(
                        f"Received packet (type: {type(packet)}) but it has no 'header' attribute. Cannot determine packet_id."
                    )

            except socket.timeout:
                continue
            except Exception as e:
                if stop_event.is_set():
                    print(
                        "Telemetry worker: socket error during stop signal, likely normal."
                    )
                    break
                listener_error = f"Error in telemetry worker: {type(e).__name__}: {e}"
                print(f"ERROR IN TELEMETRY WORKER: {listener_error}")
                traceback.print_exc()
                break

        print("UDP Telemetry listener worker signaled to stop or errored.")

    except Exception as e:
        listener_error = (
            f"Failed to start/run telemetry listener: {type(e).__name__}: {e}"
        )
        print(f"ERROR STARTING TELEMETRY LISTENER: {listener_error}")
        traceback.print_exc()
    finally:
        if (
            listener_instance
            and hasattr(listener_instance, "socket")
            and listener_instance.socket
        ):
            print("Closing telemetry listener socket.")
            listener_instance.socket.close()
        print("Telemetry listener worker finished.")


def _clear_listener_state():
    global listener_thread, listener_stop_event, listener_port, listener_host, listener_error, active_drivers_count
    global latest_car_positions, participant_data_store, session_data_store, lap_data_store

    listener_thread = None
    listener_stop_event = None
    listener_port = None
    listener_host = None
    listener_error = None
    active_drivers_count = 0

    # Reset new globals
    latest_car_positions = [{} for _ in range(22)]
    participant_data_store = [{} for _ in range(22)]
    session_data_store = {}
    lap_data_store = [{} for _ in range(22)]


@telemetry_router.post("/start", response_model=StartResponse)
async def start_telemetry(port: int = Query(20777, ge=1024, le=65535)):
    global listener_thread, listener_stop_event, listener_port, listener_host, listener_error, active_drivers_count

    # Get desired host from environment variable, default to 0.0.0.0
    desired_host = os.getenv("F1_TELEMETRY_LISTENER_HOST", "0.0.0.0")

    if not F1_TELEMETRY_AVAILABLE:
        raise HTTPException(
            status_code=500,
            detail="F1 Telemetry library (f1_24_telemetry) is not installed or available.",
        )

    if listener_thread and listener_thread.is_alive():
        raise HTTPException(
            status_code=400,
            detail=f"Telemetry listener is already running on host {listener_host}, port {listener_port}",
        )

    _clear_listener_state()  # Clear any previous error state before starting
    listener_port = port
    listener_host = desired_host
    listener_stop_event = threading.Event()

    listener_thread = threading.Thread(
        target=telemetry_listener_worker,
        args=(listener_host, listener_port, listener_stop_event),
        daemon=True,
    )
    listener_thread.start()

    await asyncio.sleep(0.5)  # Give thread a moment to initialize

    if listener_error:  # Check if worker thread set an error during startup
        initial_error = listener_error
        _clear_listener_state()
        raise HTTPException(
            status_code=500,
            detail=f"Failed to start telemetry listener: {initial_error}",
        )

    if not listener_thread.is_alive():
        _clear_listener_state()
        raise HTTPException(
            status_code=500,
            detail=f"Failed to start telemetry listener: Thread did not start.",
        )

    local_ip = get_local_ip()
    return StartResponse(
        message=f"UDP telemetry listener started on host {listener_host}, port {listener_port}",
        host=listener_host,
        port=listener_port,
    )


@telemetry_router.post("/stop")
async def stop_telemetry():
    global listener_thread, listener_stop_event

    if not listener_thread or not listener_thread.is_alive() or not listener_stop_event:
        raise HTTPException(
            status_code=400, detail="Telemetry listener is not running."
        )

    print("Attempting to stop telemetry listener...")
    listener_stop_event.set()
    listener_thread.join(timeout=3.0)  # Wait for the thread to finish

    if listener_thread.is_alive():
        print("Telemetry listener thread did not stop gracefully after timeout.")
        # Thread is daemon, so it will be killed if main app exits.
        # Forcing a socket close might be an option if we had direct access from here.
        # The worker itself tries to close its socket on stop_event.
        # Not raising an error here, but logging it.
        # Client will see success, but server might have lingering thread until socket timeout.

    final_error = (
        listener_error  # Capture error that might have occurred during shutdown
    )
    _clear_listener_state()
    print("Telemetry listener stop process completed.")

    response_message = "UDP telemetry listener stopped."
    if final_error and "Error in telemetry worker" not in final_error:
        # If error is not just a normal stop-related socket error
        response_message += (
            f" Note: An error occurred during operation or shutdown: {final_error}"
        )

    return {"message": response_message}


@telemetry_router.get("/status", response_model=TelemetryStatus)
async def get_telemetry_status():
    is_running = listener_thread is not None and listener_thread.is_alive()

    # Ensure error is cleared if not running and no specific stop error occurred
    current_error = listener_error
    if (
        not is_running
        and current_error == "Failed to start/run telemetry listener: timed out"
    ):
        current_error = None  # Clear timeout error if not running

    logger.debug(
        f"[get_telemetry_status] is_running: {is_running}, current active_drivers_count global: {active_drivers_count}"
    )
    return TelemetryStatus(
        running=is_running,
        host=listener_host if is_running else None,
        port=listener_port if is_running else None,
        active_drivers=active_drivers_count if is_running else 0,
        error=current_error,
    )


@telemetry_router.get("/live_data")
async def get_live_telemetry_data():
    global listener_thread, active_drivers_count, listener_error, listener_status_message, latest_car_positions, participant_data_store, session_data_store, lap_data_store
    logger.info(f"API /live_data called. Active drivers count: {active_drivers_count}")
    logger.debug(
        f"Current participant_data_store (first 2): {dict(list(participant_data_store.items())[:2])}"
    )
    logger.debug(
        f"Current latest_car_positions (first 2): {dict(list(latest_car_positions.items())[:2])}"
    )
    logger.debug(
        f"Current lap_data_store (first 2): {dict(list(lap_data_store.items())[:2])}"
    )
    logger.debug(f"Current session_data_store: {session_data_store}")
    drivers = []
    is_running_status = listener_thread is not None and listener_thread.is_alive()

    drivers_combined = []
    if is_running_status:
        for i in range(22):  # Iterate up to max 22 cars
            # Use .get(i, {}) on lists that might not be fully populated to avoid IndexError
            # Or ensure they are always initialized to 22 empty dicts
            participant_info = (
                participant_data_store[i]
                if i < len(participant_data_store) and participant_data_store[i]
                else {}
            )
            position_info = (
                latest_car_positions[i]
                if i < len(latest_car_positions) and latest_car_positions[i]
                else {}
            )
            lap_info = (
                lap_data_store[i]
                if i < len(lap_data_store) and lap_data_store[i]
                else {}
            )

            # Only add driver if essential participant data exists (e.g., name or teamId is present)
            if (
                participant_info.get("name")
                or participant_info.get("teamId") is not None
            ):
                drivers_combined.append(
                    {
                        **participant_info,
                        "position_data": position_info,  # Nest position data
                        "lap_data": lap_info,  # Nest lap data
                        "car_index": i,  # Add car_index for reference
                    }
                )
            elif (
                not any(participant_info.values())
                and not any(position_info.values())
                and not any(lap_info.values())
            ):
                # If all data for this index is empty, we can skip or add a placeholder
                # For now, we only add if participant_info.get('name') is present
                pass  # Or add placeholder: drivers_combined.append({'car_index': i, 'status': 'inactive'})

    response_data = {
        "session": session_data_store if is_running_status else {},
        "drivers": drivers_combined,
        "active_drivers": active_drivers_count if is_running_status else 0,
        "is_running": is_running_status,
        "error": listener_error if listener_error else None,
    }
    logger.info(
        f"API /live_data returning {len(drivers_combined)} drivers. Listener status: {is_running_status}"
    )
    logger.debug(f"API /live_data full response: {response_data}")
    from fastapi.responses import JSONResponse

    return JSONResponse(content=response_data)


# To integrate into your main FastAPI application (e.g., in main.py or app.py):
# from .api.telemetry import telemetry_router
# app.include_router(telemetry_router, prefix="/api/telemetry", tags=["Telemetry"])
