import csv
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple
from io import StringIO

import aiofiles

from app.models.models import Driver, LapTime  # Import necessary models

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Time parsing is now part of the LapTime model via computed_field


def update_overall_fastest_lap(drivers: Dict[str, Driver]):
    """
    Finds the single fastest lap across all drivers and updates the
    is_fastest flag on the corresponding LapTime object.
    """
    overall_fastest_time = float("inf")
    fastest_driver_name: str | None = None
    fastest_lap_ref: LapTime | None = None

    # First pass: find the minimum time value
    for name, driver in drivers.items():
        if (
            driver.fastest_lap
            and driver.fastest_lap.time_seconds < overall_fastest_time
        ):
            overall_fastest_time = driver.fastest_lap.time_seconds
            fastest_driver_name = name  # Keep track of which driver had it

    # Second pass: reset all flags and set the fastest one
    for name, driver in drivers.items():
        if driver.fastest_lap:
            is_the_overall_fastest = name == fastest_driver_name
            # We need to modify the flag on the existing LapTime object
            driver.fastest_lap.is_fastest = is_the_overall_fastest
            if is_the_overall_fastest:
                fastest_lap_ref = driver.fastest_lap  # Keep a reference if needed

    # Optional: return the fastest lap details if needed elsewhere immediately
    # return fastest_driver_name, fastest_lap_ref


async def generate_csv_content(
    drivers: Dict[str, Driver], track_name: str
) -> Tuple[str, str]:
    """Generates CSV content for driver lap times and returns filename and content."""
    safe_track_name = track_name.replace(" ", "_").replace(
        "/", "_"
    )  # Sanitize filename
    filename = f"{safe_track_name}.csv"

    # Prepare data: List of tuples (Driver Name, Team, LapTime object)
    lap_data: List[Tuple[str, str, LapTime]] = []
    for name, driver in drivers.items():
        if driver.fastest_lap:
            lap_data.append((name, driver.team, driver.fastest_lap))

    # Sort by lap time (fastest first) using the computed property
    lap_data.sort(key=lambda item: item[2].time_seconds)

    # F1 Points System (Top 10) + Fastest Lap Bonus
    points_map = {
        1: 25,
        2: 18,
        3: 15,
        4: 12,
        5: 10,
        6: 9,
        7: 8,
        8: 7,
        9: 6,
        10: 5,
        11: 4,
        12: 3,
        13: 2,
        14: 1,
    }

    # Create CSV content using StringIO
    csv_content = StringIO()
    writer = csv.writer(csv_content)

    # Write header
    writer.writerow(["Position", "Driver", "Time", "Points"])

    # Write data
    for i, (name, team, lap) in enumerate(lap_data):
        position = i + 1
        points = points_map.get(position, 0)  # Get points based on position, default 0

        writer.writerow(
            [
                position,
                name,
                lap.time,
                points,
            ]
        )

    csv_string = csv_content.getvalue()
    csv_content.close()

    logger.info(f"Successfully generated CSV content for {filename}")
    return filename, csv_string
