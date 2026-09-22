"""Database health API router protected by admin authentication."""
from fastapi import APIRouter, Depends, Query

from app.api.deps import require_admin
from app.models.user import User
from app.schemas.database_health import DatabaseHealthResponse
from app.services.database_health_service import get_database_health

router = APIRouter(prefix="/database", tags=["database-health"])


@router.get(
    "/health",
    response_model=DatabaseHealthResponse,
    summary="Diagnóstico detalhado de saúde do PostgreSQL e TimescaleDB",
    description="Endpoint administrativo estritamente read-only para monitoramento de conexões, locks, armazenamento e frescor de dados.",
)
async def get_database_health_endpoint(
    refresh: bool = Query(default=False, description="Forçar nova coleta ignorando o cache em memória."),
    _: User = Depends(require_admin),
) -> DatabaseHealthResponse:
    """Return database health metrics for authorized administrators."""
    return await get_database_health(force_refresh=refresh)
