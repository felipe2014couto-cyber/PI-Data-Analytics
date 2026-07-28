"""PI Web API endpoints (health only)."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.deps import get_pi_service
from app.schemas.pi import PiHealth
from app.services.pi_service import PiService

router = APIRouter(prefix="/pi", tags=["pi"])


@router.get("/health", response_model=PiHealth, summary="Verificar conexao com o PI Web API")
async def pi_health(service: PiService = Depends(get_pi_service)) -> PiHealth:
    return await service.check_health()
