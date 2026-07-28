"""API package."""
from app.api.deps import get_db_session
from app.api.errors import register_error_handlers
from app.api.router import api_router

__all__ = ["get_db_session", "register_error_handlers", "api_router"]
