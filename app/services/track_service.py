import csv
import os
import logging
from pathlib import Path
from typing import Optional, List, Dict, Tuple
from app.models.models import TrackData, TrackPoint

# Configure logging
logger = logging.getLogger(__name__)

# Track files directory
TRACKS_DIR = Path("tracks")


class TrackService:
    """Service for loading and parsing track data files."""

    def __init__(self):
        self.track_cache: Dict[str, TrackData] = {}

    def get_available_tracks(self) -> List[str]:
        """Get list of available track names from the tracks directory."""
        if not TRACKS_DIR.exists():
            logger.warning(f"Tracks directory {TRACKS_DIR} does not exist")
            return []

        available_tracks = []
        for file_path in TRACKS_DIR.glob("*_racingline.txt"):
            # Extract track name from filename (e.g., "silverstone_2020_racingline.txt" -> "silverstone")
            track_name = file_path.stem.replace("_2020_racingline", "").replace(
                "_racingline", ""
            )
            available_tracks.append(track_name)

        return sorted(available_tracks)

    def find_track_file(self, track_name: str) -> Optional[Path]:
        """Find the racing line file for a given track name."""
        if not TRACKS_DIR.exists():
            logger.warning(f"Tracks directory {TRACKS_DIR} does not exist")
            return None

        # Normalize track name (lowercase, replace spaces with underscores)
        normalized_name = track_name.lower().replace(" ", "_")

        # Try different possible file patterns
        patterns = [
            f"{normalized_name}_2020_racingline.txt",
            f"{normalized_name}_racingline.txt",
            f"{track_name.lower()}_2020_racingline.txt",
            f"{track_name.lower()}_racingline.txt",
        ]

        for pattern in patterns:
            file_path = TRACKS_DIR / pattern
            if file_path.exists():
                logger.info(f"Found track file for '{track_name}': {file_path}")
                return file_path

        logger.warning(
            f"No track file found for '{track_name}'. Tried patterns: {patterns}"
        )
        return None

    def parse_track_file(self, file_path: Path) -> Optional[TrackData]:
        """Parse a track racing line file and return TrackData."""
        try:
            points = []
            track_info = ""

            with open(file_path, "r", encoding="utf-8") as file:
                lines = file.readlines()

                if len(lines) < 3:
                    logger.error(f"Track file {file_path} has insufficient lines")
                    return None

                # First line contains track metadata
                track_info = lines[0].strip().strip('"')

                # Second line contains headers (skip it)
                headers = lines[1].strip().strip('"').split('","')
                logger.debug(f"Track file headers: {headers}")

                # Parse data lines
                for i, line in enumerate(lines[2:], start=3):
                    line = line.strip()
                    if not line:
                        continue

                    try:
                        # Split CSV data
                        values = line.split(",")
                        if len(values) >= 6:
                            point = TrackPoint(
                                dist=float(values[0]),
                                pos_z=float(values[1]),
                                pos_x=float(values[2]),
                                pos_y=float(values[3]),
                                drs=int(values[4]),
                                sector=int(values[5]),
                            )
                            points.append(point)
                    except (ValueError, IndexError) as e:
                        logger.warning(f"Error parsing line {i} in {file_path}: {e}")
                        continue

            if not points:
                logger.error(f"No valid track points found in {file_path}")
                return None

            track_name = file_path.stem.replace("_2020_racingline", "").replace(
                "_racingline", ""
            )

            track_data = TrackData(
                name=track_name, track_info=track_info, points=points
            )

            logger.info(
                f"Successfully parsed track '{track_name}' with {len(points)} points"
            )
            return track_data

        except Exception as e:
            logger.error(f"Error parsing track file {file_path}: {e}")
            return None

    async def load_track_data(self, track_name: str) -> Optional[TrackData]:
        """Load track data for a given track name, with caching."""
        if not track_name:
            return None

        # Check cache first
        if track_name in self.track_cache:
            logger.debug(f"Returning cached track data for '{track_name}'")
            return self.track_cache[track_name]

        # Find and parse track file
        track_file = self.find_track_file(track_name)
        if not track_file:
            return None

        track_data = self.parse_track_file(track_file)
        if track_data:
            # Cache the result
            self.track_cache[track_name] = track_data
            logger.info(f"Cached track data for '{track_name}'")

        return track_data

    def clear_cache(self):
        """Clear the track data cache."""
        self.track_cache.clear()
        logger.info("Track data cache cleared")


# Global track service instance
track_service = TrackService()
