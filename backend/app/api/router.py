"""Main API router."""
from fastapi import APIRouter, Depends

from app.api.admin_users import router as admin_users_router
from app.api.auth import router as auth_router
from app.api.cep import router as cep_router
from app.api.deps import get_current_user, validate_csrf
from app.api.equipments import router as equipments_router
from app.api.health import router as health_router
from app.api.pi import router as pi_router
from app.api.pi_tags import router as pi_tags_router
from app.api.sections import router as sections_router
from app.api.time_series import router as time_series_router
from app.api.variable_types import router as variable_types_router
from app.api.visual_configurations import router as visual_configurations_router

api_router = APIRouter()
api_router.include_router(health_router)
api_router.include_router(auth_router)
api_router.include_router(admin_users_router)
protected = [Depends(get_current_user), Depends(validate_csrf)]
api_router.include_router(pi_router, dependencies=protected)
api_router.include_router(equipments_router, dependencies=protected)
api_router.include_router(sections_router, dependencies=protected)
api_router.include_router(variable_types_router, dependencies=protected)
api_router.include_router(pi_tags_router, dependencies=protected)
api_router.include_router(time_series_router, dependencies=protected)
api_router.include_router(visual_configurations_router, dependencies=protected)
api_router.include_router(cep_router, dependencies=protected)
