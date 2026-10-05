from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, model_validator
from sqlalchemy.orm import Session

from app.api.deps import get_db_session
from app.schemas.pi import AnalysisFilterRequest
from app.schemas.production_unit import ProductionUnitAnalysisResponse, ProductionUnitFilterConfiguration
from app.services.production_unit_service import ProductionUnitService

router = APIRouter(prefix="/production-analysis", tags=["production-analysis"])


class ProductionUnitAnalysisRequest(BaseModel):
    analysis_rule: Literal["MEDIA", "MIN", "MAXIMO", "OOC"] | None = None
    section_id: int | None = Field(default=None, gt=0)
    equipment_id: int | None = Field(default=None, gt=0)
    tag_ids: list[int] = Field(min_length=1, max_length=50)
    start_time: datetime
    end_time: datetime
    filter_configuration: ProductionUnitFilterConfiguration = Field(default_factory=ProductionUnitFilterConfiguration, alias="filterConfiguration")
    analysis_filters: list[AnalysisFilterRequest] = Field(default_factory=list, alias="analysisFilters", max_length=100)

    model_config = {"populate_by_name": True}

    @model_validator(mode="after")
    def validate_scope(self):
        if self.section_id is None and self.equipment_id is None:
            raise ValueError("Informe equipment_id quando section_id não for informado.")
        return self


@router.post("/units", response_model=ProductionUnitAnalysisResponse, summary="Agregar tags por intervalos RECORDED de UM")
def analyze_production_units(
    request: ProductionUnitAnalysisRequest,
    db: Session = Depends(get_db_session),
) -> ProductionUnitAnalysisResponse:
    if request.analysis_rule == "OOC":
        from app.services.production_unit_ooc import ProductionUnitOocService
        return ProductionUnitOocService(db).analyze(request)
    return ProductionUnitService(db).analyze(
        request.section_id, request.tag_ids, request.start_time, request.end_time,
        request.filter_configuration, request.analysis_filters, equipment_id=request.equipment_id,
    )
