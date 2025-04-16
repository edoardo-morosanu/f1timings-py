import logging
from typing import Dict, List, Optional, Union
from pydantic import BaseModel, Field, field_validator, computed_field

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- Internal Data Structures ---

class LapTime(BaseModel):
    time: str  # Store as original string e.g., "1:23.456" or "83.456"
    is_fastest: bool = False

    # Use computed_field for calculations without storing extra state
    @computed_field
    @property
    def time_seconds(self) -> float:
        """Calculates lap time in seconds for comparison."""
        time_str = self.time
        if ":" in time_str:
            try:
                parts = time_str.split(":")
                minutes = float(parts[0])
                seconds = float(parts[1])
                return minutes * 60.0 + seconds
            except (ValueError, IndexError):
                logger.warning(f"Could not parse time with colon: {time_str}")
                return float("inf")
        elif "." in time_str:
            try:
                parts = time_str.split(".")
                if len(parts) == 3:  # mm.ss.sss format (common in games)
                    minutes = float(parts[0])
                    seconds = float(parts[1])
                    millis = float(f"0.{parts[2]}")
                    return minutes * 60.0 + seconds + millis
                elif len(parts) == 2:  # ss.sss format
                    # Handle potential whole second part correctly
                    sec_part = float(parts[0])
                    millis_part = float(f"0.{parts[1]}")
                    return sec_part + millis_part
                else:  # Unexpected format with dots
                    logger.warning(f"Unexpected dot format: {time_str}")
                    return float(time_str)  # Attempt direct parse
            except (ValueError, IndexError):
                logger.warning(f"Could not parse time with dot: {time_str}")
                return float("inf")
        else:  # Assume plain seconds
            try:
                return float(time_str)
            except ValueError:
                logger.warning(f"Could not parse plain time: {time_str}")
                return float("inf")


class Driver(BaseModel):
    name: str
    team: str  # "RedBull" or "McLaren"
    # Store only the single fastest lap per driver, as per Rust logic
    fastest_lap: Optional[LapTime] = None

    def update_lap(self, new_lap_time_str: str, new_team: str):
        """Adds or updates the driver's fastest lap if the new one is faster."""
        new_lap = LapTime(time=new_lap_time_str)
        self.team = new_team  # Update team regardless

        if (
            self.fastest_lap is None
            or new_lap.time_seconds < self.fastest_lap.time_seconds
        ):
            # New lap is faster or it's the first lap
            self.fastest_lap = new_lap
            return True  # Indicates lap was updated
        return False  # Lap was not faster


# --- Application State Structure ---


class AppData(BaseModel):
    drivers: Dict[str, Driver] = Field(default_factory=dict)
    track_name: Optional[str] = None


# --- API Input Models ---


class LapTimeInput(BaseModel):
    name: str  # Matches frontend 'name'
    team: str  # "RedBull" or "McLaren"
    time: str  # e.g., "1:23.456" or "83.456" or "1.23.456"

    @field_validator("time")
    def validate_time_format(cls, v):
        # Basic validation - more strict parsing happens in LapTime model
        if not any(c in v for c in ":."):
            try:
                float(v)  # Check if it's convertible to float if no separators
            except ValueError:
                raise ValueError(
                    "Time must be in a recognizable format (mm:ss.sss, mm.ss.sss, ss.sss, or seconds)"
                )
        # Allow formats with separators
        return v


class LapTimeDeleteInput(BaseModel):
    name: str  # Matches frontend 'name'
    time: str  # The specific lap time string to delete


class TrackNameInput(BaseModel):
    name: str  # Matches frontend 'name'


# --- API Response Models ---


class TrackNameResponse(BaseModel):
    name: str


class ExportResponse(BaseModel):
    success: bool
    filename: str = ""  # Filename of the *primary* export (e.g., CSV)
    message: str


class DriverResponse(BaseModel):
    """
    Defines the structure returned by /api/drivers.
    Matches the Rust version where lap_times was a Vec, even though
    we only store the fastest lap internally now. We reconstruct this
    structure for API consistency.
    """

    name: str
    team: str
    lap_times: List[LapTime] = Field(
        default_factory=list
    )  # List for frontend compatibility

class User(BaseModel):
    """Represents a user/driver with their assigned team."""
    name: str = Field(..., description="Driver's name", min_length=1)
    team: str = Field(..., description="Driver's team", min_length=1)

    @field_validator('name', 'team')
    def name_must_not_be_empty(cls, value):
        if not value.strip():
            raise ValueError("Name and team cannot be empty or just whitespace")
        return value.strip()

class UserResponse(BaseModel):
    """Response model for a single user."""
    name: str
    team: str

class UserListResponse(BaseModel):
    """Response model for a list of users."""
    users: Dict[str, UserResponse]


# Helper to convert internal Driver state to API response format
def driver_to_response(driver: Driver) -> DriverResponse:
    response = DriverResponse(name=driver.name, team=driver.team)
    if driver.fastest_lap:
        response.lap_times.append(driver.fastest_lap)
    return response
