import os
import secrets
import bcrypt
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List
from itsdangerous import URLSafeTimedSerializer, SignatureExpired, BadSignature
from dotenv import load_dotenv
import logging

# Load environment variables
load_dotenv()

logger = logging.getLogger(__name__)

# Session management
SECRET_KEY = os.getenv("SECRET_KEY", "your-super-secret-key-change-this-in-production")
SESSION_SERIALIZER = URLSafeTimedSerializer(SECRET_KEY)
SESSION_MAX_AGE = int(os.getenv("SESSION_MAX_AGE", 86400))  # 24 hours in seconds

# Get admin credentials from environment
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin123")


def get_password_hash(password: str) -> str:
    """Hash a password using bcrypt."""
    # Convert password to bytes
    password_bytes = password.encode("utf-8")
    # Generate salt and hash
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(password_bytes, salt)
    # Return as string
    return hashed.decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against its hash."""
    try:
        # Convert both to bytes
        password_bytes = plain_password.encode("utf-8")
        hash_bytes = hashed_password.encode("utf-8")
        # Verify password
        return bcrypt.checkpw(password_bytes, hash_bytes)
    except Exception as e:
        logger.error(f"Password verification error: {e}")
        return False


# Simple in-memory admin user store (for school use)
# In production, you might want to use a database
ADMIN_USERS = {
    ADMIN_USERNAME: {
        "username": ADMIN_USERNAME,
        "password_hash": get_password_hash(ADMIN_PASSWORD),  # Default password
        "is_active": True,
    }
}

# Session store (in-memory)
active_sessions: Dict[str, Dict[str, Any]] = {}


def initialize_admin_users():
    """Initialize additional admin users from environment or add them manually."""
    # You can add more admin users here
    additional_admins = [
        # Example: {"username": "teacher1", "password": "secure_password_123"},
        # Example: {"username": "teacher2", "password": "another_secure_pass"},
    ]

    for admin in additional_admins:
        if admin["username"] not in ADMIN_USERS:
            ADMIN_USERS[admin["username"]] = {
                "username": admin["username"],
                "password_hash": get_password_hash(admin["password"]),
                "is_active": True,
            }
            logger.info(f"Added admin user: {admin['username']}")


# Initialize additional users on startup
initialize_admin_users()


def authenticate_user(username: str, password: str) -> Optional[Dict[str, Any]]:
    """Authenticate a user with username and password."""
    user = ADMIN_USERS.get(username)
    if not user:
        return None
    if not verify_password(password, user["password_hash"]):
        return None
    if not user.get("is_active", True):
        return None
    return {"username": user["username"]}


def create_session(username: str) -> str:
    """Create a new session for a user."""
    session_id = secrets.token_urlsafe(32)
    session_data = {
        "username": username,
        "created_at": datetime.utcnow(),
        "last_accessed": datetime.utcnow(),
    }
    active_sessions[session_id] = session_data
    logger.info(f"Created session for user: {username}")
    return session_id


def get_session(session_id: str) -> Optional[Dict[str, Any]]:
    """Get session data by session ID."""
    if not session_id:
        return None

    session_data = active_sessions.get(session_id)
    if not session_data:
        return None

    # Check if session has expired
    created_at = session_data["created_at"]
    if datetime.utcnow() - created_at > timedelta(seconds=SESSION_MAX_AGE):
        # Session expired, remove it
        del active_sessions[session_id]
        logger.info(f"Session expired and removed: {session_id}")
        return None

    # Update last accessed time
    session_data["last_accessed"] = datetime.utcnow()
    return session_data


def delete_session(session_id: str) -> bool:
    """Delete a session."""
    if session_id in active_sessions:
        username = active_sessions[session_id].get("username", "unknown")
        del active_sessions[session_id]
        logger.info(f"Session deleted for user: {username}")
        return True
    return False


def cleanup_expired_sessions():
    """Clean up expired sessions."""
    current_time = datetime.utcnow()
    expired_sessions = []

    for session_id, session_data in active_sessions.items():
        created_at = session_data["created_at"]
        if current_time - created_at > timedelta(seconds=SESSION_MAX_AGE):
            expired_sessions.append(session_id)

    for session_id in expired_sessions:
        del active_sessions[session_id]
        logger.info(f"Cleaned up expired session: {session_id}")

    if expired_sessions:
        logger.info(f"Cleaned up {len(expired_sessions)} expired sessions")


def add_admin_user(username: str, password: str) -> bool:
    """Add a new admin user (for initial setup)."""
    if username in ADMIN_USERS:
        return False

    ADMIN_USERS[username] = {
        "username": username,
        "password_hash": get_password_hash(password),
        "is_active": True,
    }
    logger.info(f"Added new admin user: {username}")
    return True


def change_password(username: str, new_password: str) -> bool:
    """Change password for an existing user."""
    if username not in ADMIN_USERS:
        return False

    ADMIN_USERS[username]["password_hash"] = get_password_hash(new_password)
    logger.info(f"Password changed for user: {username}")
    return True


def get_active_sessions_count() -> int:
    """Get the number of active sessions."""
    cleanup_expired_sessions()  # Clean up first
    return len(active_sessions)


def get_active_sessions_info() -> List[Dict[str, Any]]:
    """Get detailed information about all active sessions."""
    cleanup_expired_sessions()  # Clean up first
    sessions_info = []

    for session_id, session_data in active_sessions.items():
        sessions_info.append(
            {
                "session_id": session_id[:8] + "...",  # Truncated for security
                "username": session_data["username"],
                "created_at": session_data["created_at"].isoformat(),
                "last_accessed": session_data["last_accessed"].isoformat(),
                "duration": str(datetime.utcnow() - session_data["created_at"]),
            }
        )

    return sessions_info


def get_admin_users_list() -> List[Dict[str, Any]]:
    """Get list of all admin users (without password hashes)."""
    users = []
    for username, user_data in ADMIN_USERS.items():
        users.append(
            {"username": username, "is_active": user_data.get("is_active", True)}
        )
    return users
