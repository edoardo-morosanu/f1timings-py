# F1Timings-Py

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

**Actively Developed Python implementation for F1 Timing and Telemetry (using FastAPI).**

This project provides a web API to track F1 lap times, manage driver data, and export standings. It serves static frontends for administration and display. Future development aims to integrate real-time telemetry data received via UDP from F1 simulation games (e.g., F1 24) and push live updates via WebSockets.

This is the successor to the original [f1timings-rs](https://github.com/edoardo-morosanu/f1timings-rs) Rust project.

---

## Features

**Implemented:**

- **Web API (FastAPI):**
  - Manage drivers and their single fastest lap time
  - Set and retrieve the current track name.
  - Sophisticated lap time parsing supporting multiple formats (`mm:ss.sss`, `mm.ss.sss`, `ss.sss`, plain seconds) via Pydantic models.
- **Data Storage:** In-memory storage for drivers and track info, using `asyncio.Lock` for safe concurrent access.
- **Data Export (`GET /api/export`):**
  - Exports current standings (sorted by fastest lap) to timestamped CSV files in an `exports/` directory, including calculated points.
- **Static File Serving:** Serves static HTML/JS/CSS frontends from `static/admin`, `static/display`, and the root `static` directory.
- **WebSocket Integration:**
  - Real-time updates via `/ws` endpoint for connected clients
  - Broadcasts notifications for lap time updates, user changes, and track changes
  - Supports instant UI updates without manual refreshing
- **Robust Error Handling:** Custom exception handlers for validation, HTTP, and general server errors.

**Upcoming / Planned Features:**

- **UDP Telemetry Listener:** (Placeholder in `main.py` lifespan) Listen for UDP packets from F1 2x games.
- **Real-time Data Processing:** Parse telemetry packets.
- **Enhanced Telemetry Data:** Push processed telemetry data to connected clients in real-time via existing WebSocket infrastructure.
- **Enhanced Display Frontend:** A web interface (`/display`) that visualizes live data received via WebSockets.
- **Persistence:** Option to save/load state to/from disk instead of purely in-memory.

## Technology Stack

- **Backend:** Python 3.12.10
- **Web Framework:** FastAPI
- **Data Validation:** Pydantic
- **Async Server:** Uvicorn
- **Concurrency:** asyncio (`async`/`await`, `asyncio.Lock`)
- **Real-time Communication:** WebSockets
- **Async File I/O:** aiofiles (for export)
- **Data Storage:** In-memory Python dictionaries managed within Pydantic models.
- **Frontend (Assumed):** HTML, CSS, JavaScript

## Prerequisites

- **Python:** Version 3.12.10 recommended.
- **pip:** Python package installer.
- **(Optional) Git:** For cloning the repository.

## Installation & Setup

1.  **Clone the repository:**

    ```bash
    $ git clone https://github.com/edoardo-morosanu/f1timings-py.git
    $ cd f1timings-py
    ```

2.  **Create and activate a virtual environment (Recommended):**

    ```bash
    # Linux/macOS
    $ python3 -m venv venv
    $ source venv/bin/activate

    # Windows
    $ python -m venv venv
    $ .\venv\Scripts\activate
    ```

3.  **Install dependencies:**
    ```bash
    $ pip install -r requirements.txt
    ```

## Running the Application

- **Development (with auto-reload):**

  ```bash
  # Make sure your virtual environment is activated
  $ uvicorn main:app
  ```

  _Alternatively:_

  ```bash
  $ python main.py
  ```

The server listens on `0.0.0.0:8080` by default.

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
