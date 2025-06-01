import logging
from contextlib import asynccontextmanager
from typing import Dict, List

import uvicorn
from fastapi import FastAPI, HTTPException, Request, Path
from fastapi import WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.exceptions import RequestValidationError

# Import models and CRUD operations
from app.models.models import (
    LapTimeInput,
    LapTimeDeleteInput,
    TrackNameInput,
    TrackNameResponse,
    ExportResponse,
    DriverResponse,
    User,
    UserResponse,
    UserListResponse,
    driver_to_response,
)
from app.services.crud import (
    get_all_drivers,
    add_or_update_lap_time,
    delete_driver_lap_time,
    get_track,
    set_track,
    get_all_users,
    add_user,
    delete_user,
    app_data,
    state_lock,
    set_websocket_manager,
)
from app.utils.helpers import generate_csv_content, update_overall_fastest_lap
from app.services.websocket import ConnectionManager
from app.dependencies.auth import check_admin_auth_middleware, get_current_user

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Create the WebSocket connection manager
manager = ConnectionManager()


# --- Lifespan Management ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Application startup...")
    # --- Add startup logic here ---
    # Assign the manager to crud.py
    set_websocket_manager(manager)
    yield
    # --- Add shutdown logic here ---
    logger.info("Application shutdown...")


app = FastAPI(title="F1 Telemetry API", version="1.0.0", lifespan=lifespan)

# --- Middleware ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow all origins for development
    # In production, restrict this to your frontend's origin:
    # allow_origins=["http://localhost:8080", "http://127.0.0.1:8080", "http://your_domain.com"],
    allow_credentials=True,
    allow_methods=["*"],  # Allow all standard methods
    allow_headers=["*"],  # Allow all headers
)


# Add authentication middleware for admin routes
@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    return await check_admin_auth_middleware(request, call_next)


# -- WebSocket Connection Management ---
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)
        logger.info(f"Client disconnected")


# --- Custom Exception Handlers ---
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    # Log the validation errors for debugging
    logger.error(f"Validation error for request {request.url}: {exc.errors()}")
    return JSONResponse(
        status_code=422,
        content={"detail": exc.errors()},
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    # Log HTTP exceptions that we raise intentionally
    logger.warning(
        f"HTTP Exception for request {request.url}: Status={exc.status_code}, Detail={exc.detail}"
    )
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail},
    )


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    # Catch-all for unexpected server errors
    logger.exception(
        f"Unhandled exception for request {request.url}: {exc}"
    )  # Log the full traceback
    return JSONResponse(
        status_code=500,
        content={"detail": "An internal server error occurred."},
    )


# --- Import API Routers ---
from app.api.users import router as users_router
from app.api.drivers import router as drivers_router
from app.api.auth import router as auth_router

# --- Include Routers ---
app.include_router(auth_router)
app.include_router(users_router)
app.include_router(drivers_router)

# You can still add additional routes here if necessary


# --- Login Route ---
@app.get("/login")
async def login_page():
    """Serve the login page."""
    with open("static/login.html", "r", encoding="utf-8") as f:
        content = f.read()
    return Response(content=content, media_type="text/html")


# --- Static Files Serving ---
# Serve specific admin/display routes first
# Ensure the paths match your folder structure
app.mount("/admin", StaticFiles(directory="static/admin", html=True), name="admin")
app.mount(
    "/display", StaticFiles(directory="static/display", html=True), name="display"
)
app.mount(
    "/admin/users",
    StaticFiles(directory="static/admin/users", html=True),
    name="users",
)
# Serve shared assets (like images) or a root index.html from the main static folder
# This also acts as a fallback for other paths under /
app.mount("/", StaticFiles(directory="static", html=True), name="static")

# --- Run the application ---
if __name__ == "__main__":
    logger.info("Starting Uvicorn server...")
    uvicorn.run("app.main:app", host="0.0.0.0", port=8080, reload=True)
