"""Administrative CEP dependency reconciliation endpoints."""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_db_session, get_pi_service, require_admin, validate_csrf
from app.services.cep_dependency_service import CepDependencyService
from app.services.pi_service import PiService

router = APIRouter(
    prefix="/admin/cep-dependencies",
    tags=["cep-dependencies"],
    dependencies=[Depends(require_admin), Depends(validate_csrf)],
)


@router.post("/reconcile")
async def reconcile_dependencies(
    db: Session = Depends(get_db_session),
    pi_service: PiService = Depends(get_pi_service),
):
    provider = pi_service._resolve_provider()
    return await CepDependencyService(db).reconcile(provider)
