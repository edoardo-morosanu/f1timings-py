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

    def find_matching_track_name(self, input_track_name: str) -> Optional[str]:
        """
        Find the best matching track name from available tracks using case-insensitive matching
        with comprehensive alias support.

        Args:
            input_track_name: The track name to match (can be any case)

        Returns:
            The actual track name from available tracks, or None if no match found
        """
        if not input_track_name:
            return None

        available_tracks = self.get_available_tracks()
        input_normalized = input_track_name.lower().replace(" ", "_").replace("-", "_")

        # Track aliases mapping - common names to actual track file names
        track_aliases = {
            # Country/Location based aliases
            "australia": "melbourne",
            "australian": "melbourne",
            "austria": "austria",
            "austrian": "austria",
            "azerbaijan": "baku",
            "bahrain": "bahrain",
            "bahraini": "bahrain",
            "belgium": "spa",
            "belgian": "spa",
            "brazil": "brazil",
            "brazilian": "brazil",
            "canada": "canada",
            "canadian": "canada",
            "china": "shanghai",
            "chinese": "shanghai",
            "france": "paul_ricard",
            "french": "paul_ricard",
            "germany": "hungaroring",  # Note: No German GP in current files
            "hungary": "hungaroring",
            "hungarian": "hungaroring",
            "italy": "monza",
            "italian": "monza",
            "japan": "suzuka",
            "japanese": "suzuka",
            "mexico": "mexico",
            "mexican": "mexico",
            "netherlands": "zandvoort",
            "dutch": "zandvoort",
            "qatar": "losail",
            "russia": "sochi",
            "russian": "sochi",
            "saudi_arabia": "jeddah",
            "saudi": "jeddah",
            "singapore": "singapore",
            "spain": "catalunya",
            "spanish": "catalunya",
            "uk": "silverstone",
            "britain": "silverstone",
            "british": "silverstone",
            "england": "silverstone",
            "usa": "texas",
            "united_states": "texas",
            "america": "texas",
            "american": "texas",
            "uae": "abu_dhabi",
            "emirates": "abu_dhabi",
            "vietnam": "hanoi",
            "vietnamese": "hanoi",
            # Circuit/Track name aliases
            "albert_park": "melbourne",
            "red_bull_ring": "austria",
            "spielberg": "austria",
            "baku_city_circuit": "baku",
            "bahrain_international_circuit": "bahrain",
            "spa_francorchamps": "spa",
            "francorchamps": "spa",
            "interlagos": "brazil",
            "sao_paulo": "brazil",
            "gilles_villeneuve": "canada",
            "montreal": "canada",
            "shanghai_international_circuit": "shanghai",
            "circuit_paul_ricard": "paul_ricard",
            "le_castellet": "paul_ricard",
            "hungaroring": "hungaroring",
            "budapest": "hungaroring",
            "autodromo_nazionale_monza": "monza",
            "suzuka_circuit": "suzuka",
            "autodromo_hermanos_rodriguez": "mexico",
            "mexico_city": "mexico",
            "circuit_zandvoort": "zandvoort",
            "losail_international_circuit": "losail",
            "doha": "losail",
            "sochi_autodrom": "sochi",
            "jeddah_corniche_circuit": "jeddah",
            "marina_bay": "singapore",
            "singapore_street_circuit": "singapore",
            "circuit_de_catalunya": "catalunya",
            "barcelona": "catalunya",
            "silverstone_circuit": "silverstone",
            "yas_marina": "abu_dhabi",
            "yas_marina_circuit": "abu_dhabi",
            "hanoi_street_circuit": "hanoi",
            "circuit_of_the_americas": "texas",
            "cota": "texas",
            "austin": "texas",
            "imola_circuit": "imola",
            "autodromo_enzo_e_dino_ferrari": "imola",
            "san_marino": "imola",
            "las_vegas_strip": "las_vegas",
            "vegas": "las_vegas",
            "strip": "las_vegas",
            "miami_international_autodrome": "miami",
            "hard_rock_stadium": "miami",
            "monaco_street_circuit": "monaco",
            "monte_carlo": "monaco",
            "circuit_de_monaco": "monaco",
            "sakhir_circuit": "sakhir",
        }

        # First try alias matching
        for alias, actual_track in track_aliases.items():
            if input_normalized == alias or input_normalized.replace(
                "_", ""
            ) == alias.replace("_", ""):
                # Check if the actual track exists in available tracks
                for track in available_tracks:
                    if track.lower() == actual_track.lower():
                        logger.info(
                            f"Alias match found for '{input_track_name}' -> '{alias}' -> '{track}'"
                        )
                        return track

        # Second, try exact match (case-insensitive)
        for track in available_tracks:
            if track.lower() == input_normalized:
                logger.info(f"Exact match found for '{input_track_name}': '{track}'")
                return track

        # Third, try partial matching - check if input is contained in any track name
        for track in available_tracks:
            track_normalized = track.lower().replace(" ", "_").replace("-", "_")
            if (
                input_normalized in track_normalized
                or track_normalized in input_normalized
            ):
                logger.info(f"Partial match found for '{input_track_name}': '{track}'")
                return track

        # Fourth, try matching without common prefixes/suffixes
        cleaned_input = (
            input_normalized.replace("circuit", "")
            .replace("track", "")
            .replace("street", "")
            .replace("international", "")
            .strip("_")
        )
        for track in available_tracks:
            cleaned_track = (
                track.lower()
                .replace("circuit", "")
                .replace("track", "")
                .replace("street", "")
                .replace("international", "")
                .strip("_")
            )
            if cleaned_input == cleaned_track:
                logger.info(f"Cleaned match found for '{input_track_name}': '{track}'")
                return track

        logger.warning(
            f"No matching track found for '{input_track_name}' in available tracks: {available_tracks}"
        )
        return None

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
