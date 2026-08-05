"""CEP Analysis Service — orchestrates the full CEP analysis workflow.

This service coordinates:
1. Loading materialized data (already done by endpoint)
2. Deduplicating PI tags
3. Resolving WebIds
4. Fetching Interpolated 5m (for compliance calculation)
5. Fetching Recorded (optional, for API response)
6. Calculating compliance via cep_calculator
7. Building the final result
8. Transitions to terminal state

The service does NOT load from database — it receives materialized data.
The service does NOT register tasks in QueryRegistry — the endpoint does that.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime

from app.core.config import settings
from app.integrations.pi.errors import PiIntegrationError
from app.integrations.pi.provider import PiDataProvider, PiValue
from app.schemas.cep_analysis import (
    CepAnalysisMetadata,
    CepAnalysisResult,
    CepAnalysisSummary,
    CepDiagnostic,
    CepRecordedPoint,
    CepRecordedSeries,
    CepVariableResult,
    MaterializedAnalysisData,
    MaterializedTag,
    MaterializedVariable,
)
from app.services.cep_calculator import (
    calculate_compliance,
)
from app.services.cep_pi_adapter import pi_value_to_cep_sample
from app.services.cep_query_store import CepQueryStore
from app.services.query_registry import QueryRegistry

logger = logging.getLogger("pi_analytics_data.service.cep_analysis")


class CepAnalysisService:
    """Orchestrates CEP analysis."""

    def __init__(self, provider: PiDataProvider) -> None:
        self._provider = provider

    async def run_analysis(
        self,
        query_id: str,
        materialized_data: MaterializedAnalysisData,
        store: CepQueryStore,
        registry: QueryRegistry,
    ) -> None:
        """Execute CEP analysis for an already-registered operation.

        The operation must be registered in the store before calling this method.
        The task must be registered in QueryRegistry by the caller (endpoint).
        The ready_event must be set after QueryRegistry registration.
        """
        try:
            # 1. Wait for the endpoint to finish QueryRegistry registration
            entry = await store.get(query_id)
            if entry is None:
                return
            await entry.ready_event.wait()

            # 2. Transition to running
            if not await store.set_running(query_id):
                return  # Already terminal
            analysis_started_at = datetime.now(UTC)

            # 3. Deduplicate tags — use the already-materialized unique tags
            unique_tags = materialized_data.unique_tags
            tag_variable_map = materialized_data.tag_variable_map

            # 4. Resolve WebIds
            web_ids, acquisition_diagnostics = await self._resolve_web_ids(unique_tags)

            # 5. Fetch Interpolated 5m
            interpolated_data, interpolated_diagnostics = await self._fetch_interpolated(
                web_ids, materialized_data.request.start_time,
                materialized_data.request.end_time,
            )
            acquisition_diagnostics.extend(interpolated_diagnostics)

            # 6. Calculate compliance for each variable
            variable_results = []
            for var in materialized_data.variables:
                result = self._calculate_variable_compliance(
                    var, interpolated_data, tag_variable_map
                )
                variable_results.append(result)

            # 7. Fetch Recorded if requested
            recorded_series: list[CepRecordedSeries] = []
            recorded_metadata: dict[str, object] = {}
            if materialized_data.request.include_recorded:
                recorded_series, recorded_metadata = await self._fetch_recorded(
                    unique_tags, materialized_data.request.start_time,
                    materialized_data.request.end_time, tag_variable_map,
                )

            # 8. Build result
            analysis_result = self._build_result(
                query_id, materialized_data, variable_results,
                recorded_series, recorded_metadata, acquisition_diagnostics,
                interpolated_data, len(web_ids), analysis_started_at,
            )

            # 9. Transition to terminal state
            status = self._determine_status(variable_results)
            await store.set_result(query_id, analysis_result, status)

        except asyncio.CancelledError:
            # Technical cancellation from QueryRegistry
            # Do NOT convert failed to cancelled
            entry = await store.get(query_id)
            if entry is not None and entry.query_status not in (
                "completed", "failed", "cancelled"
            ):
                await store.set_cancelled(query_id)
            raise
        except Exception as exc:
            # Unhandled exceptions → failed
            logger.exception("CEP analysis failed for %s", query_id)
            error_result = self._build_error_result(query_id, exc)
            await store.set_result(query_id, error_result, "failed")
        finally:
            # Always unregister from QueryRegistry (idempotent)
            await registry.unregister(query_id)

    # -- Deduplication --

    def _deduplicate_tags(
        self, variables: list[MaterializedVariable]
    ) -> list[int]:
        """Collect unique tag IDs from all variables."""
        seen: set[int] = set()
        for var in variables:
            for tag_id in [var.reading_tag_id, var.lower_limit_tag_id,
                           var.upper_limit_tag_id, var.target_tag_id]:
                if tag_id is not None:
                    seen.add(tag_id)
        return sorted(seen)

    # -- WebId resolution --

    async def _resolve_web_ids(
        self, unique_tags: list[MaterializedTag]
    ) -> tuple[dict[int, str], list[CepDiagnostic]]:
        """Resolve cached and missing WebIds for the materialized PI tags."""
        result: dict[int, str] = {}
        diagnostics: list[CepDiagnostic] = []
        for tag in unique_tags:
            if tag.pi_web_id:
                result[tag.id] = tag.pi_web_id
                continue

            try:
                point = await self._provider.resolve_point(
                    f"\\\\{tag.pi_server}\\{tag.pi_tag_name}"
                )
            except PiIntegrationError as exc:
                logger.warning("WebId resolution failed for tag %s: %s", tag.pi_tag_name, exc)
                diagnostics.append(CepDiagnostic(
                    tag_id=tag.id,
                    tag_name=tag.pi_tag_name,
                    variable_ids=[],
                    error_code="WEBID_RESOLUTION_FAILED",
                    message="Não foi possível resolver a tag no PI Web API.",
                ))
                continue

            if point is None:
                diagnostics.append(CepDiagnostic(
                    tag_id=tag.id,
                    tag_name=tag.pi_tag_name,
                    variable_ids=[],
                    error_code="TAG_NOT_FOUND",
                    message="Tag não encontrada no PI Web API.",
                ))
                continue

            result[tag.id] = point.web_id
        return result, diagnostics

    # -- Interpolated fetch --

    async def _fetch_interpolated(
        self,
        web_ids: dict[int, str],
        start_time: datetime,
        end_time: datetime,
    ) -> tuple[dict[str, list[PiValue]], list[CepDiagnostic]]:
        """Fetch Interpolated 5m data, retaining a diagnostic per failed tag."""
        if not web_ids:
            return {}, []

        try:
            responses = await self._provider.get_interpolated_values_batch(
                web_ids=list(web_ids.values()),
                start_time=start_time,
                end_time=end_time,
                interval="5m",
            )
        except PiIntegrationError as exc:
            logger.warning("Interpolated batch fetch failed: %s", exc)
            return {}, [
                CepDiagnostic(
                    tag_id=tag_id,
                    tag_name="",
                    variable_ids=[],
                    error_code="PI_INTERPOLATED_FAILED",
                    message="Falha ao adquirir amostras Interpolated no PI Web API.",
                )
                for tag_id in web_ids
            ]

        tag_id_by_web_id = {web_id: tag_id for tag_id, web_id in web_ids.items()}
        mapped: dict[str, list[PiValue]] = {str(tag_id): [] for tag_id in web_ids}
        for response in responses:
            tag_id = tag_id_by_web_id.get(response.web_id)
            if tag_id is not None:
                mapped[str(tag_id)] = response.values

        diagnostics: list[CepDiagnostic] = []
        for tag_id_text, values in mapped.items():
            if not values:
                diagnostics.append(CepDiagnostic(
                    tag_id=int(tag_id_text),
                    tag_name="",
                    variable_ids=[],
                    error_code="NO_HISTORY_IN_PERIOD",
                    message="A tag não possui histórico no período informado.",
                ))
        return mapped, diagnostics

    # -- Recorded fetch --

    async def _fetch_recorded(
        self,
        unique_tags: list[MaterializedTag],
        start_time: datetime,
        end_time: datetime,
        tag_variable_map: dict[int, list[int]],
    ) -> tuple[list[CepRecordedSeries], dict[str, object]]:
        """Fetch Recorded data respecting individual and aggregate limits."""
        individual_limit = settings.pi_cep_recorded_max_points_per_tag
        aggregate_limit = settings.pi_cep_recorded_max_total_points

        sorted_tags = sorted(unique_tags, key=lambda t: t.pi_tag_name)
        remaining_aggregate = aggregate_limit

        recorded_series: list[CepRecordedSeries] = []
        not_acquired: list[str] = []
        total_returned = 0
        any_aggregate_truncation = False

        for tag in sorted_tags:
            if remaining_aggregate <= 0:
                not_acquired.append(tag.pi_tag_name)
                continue

            if not tag.pi_web_id:
                not_acquired.append(tag.pi_tag_name)
                continue

            budget = min(individual_limit, remaining_aggregate)

            # Reverse query: start_time=fim, end_time=início
            try:
                raw_values = await self._provider.get_recorded_values(
                    web_id=tag.pi_web_id,
                    start_time=end_time,
                    end_time=start_time,
                    max_count=budget + 1,
                )
                points_desc = raw_values.values
            except PiIntegrationError as exc:
                logger.warning("Recorded fetch failed for tag %s: %s", tag.pi_tag_name, exc)
                not_acquired.append(tag.pi_tag_name)
                continue

            # Determine truncation
            individual_bound = individual_limit <= remaining_aggregate
            aggregate_bound = remaining_aggregate <= individual_limit

            if len(points_desc) > budget:
                truncated = True
                source_point_count = None
                selected_desc = points_desc[:budget]
                selected = sorted(selected_desc, key=lambda p: p.timestamp)

                if individual_bound and aggregate_bound:
                    # Both limits hit — both confirmed
                    any_aggregate_truncation = True
                elif aggregate_bound:
                    any_aggregate_truncation = True
                # individual_bound alone doesn't trigger aggregate flag

                remaining_aggregate -= budget
            elif len(points_desc) > 0:
                truncated = False
                source_point_count = len(points_desc)
                selected = sorted(points_desc, key=lambda p: p.timestamp)
                remaining_aggregate -= len(points_desc)
            else:
                truncated = False
                source_point_count = 0
                selected = []

            total_returned += len(selected)

            series = CepRecordedSeries(
                tag_id=tag.id,
                tag_name=tag.pi_tag_name,
                variable_ids=tag_variable_map.get(tag.id, []),
                points=[self._to_recorded_point(p) for p in selected],
                truncated=truncated,
                source_point_count=source_point_count,
            )
            recorded_series.append(series)

        metadata = {
            "recorded_total_point_limit": aggregate_limit,
            "recorded_returned_point_count": total_returned,
            "recorded_total_limit_reached": any_aggregate_truncation,
            "recorded_tags_not_acquired": not_acquired,
        }

        return recorded_series, metadata

    def _to_recorded_point(self, pv: PiValue) -> CepRecordedPoint:
        """Convert a PiValue to a CepRecordedPoint."""
        return CepRecordedPoint(
            timestamp=pv.timestamp,
            value=pv.value if isinstance(pv.value, (int, float)) else None,
            good=pv.good,
            questionable=pv.questionable,
            substituted=pv.substituted,
        )

    # -- Compliance calculation --

    def _calculate_variable_compliance(
        self,
        var: MaterializedVariable,
        interpolated_data: dict[str, list[PiValue]],
        tag_variable_map: dict[int, list[int]],
    ) -> CepVariableResult:
        """Calculate compliance for a single variable."""
        reading_values = interpolated_data.get(str(var.reading_tag_id), [])
        lower_values = interpolated_data.get(str(var.lower_limit_tag_id), [])
        upper_values = interpolated_data.get(str(var.upper_limit_tag_id), [])
        target_values = interpolated_data.get(str(var.target_tag_id), []) if var.target_tag_id else []

        # Convert to CepSample
        reading_samples = [pi_value_to_cep_sample(v) for v in reading_values]
        lower_samples = [pi_value_to_cep_sample(v) for v in lower_values]
        upper_samples = [pi_value_to_cep_sample(v) for v in upper_values]
        target_samples = [pi_value_to_cep_sample(v) for v in target_values] if target_values else None

        try:
            _points, summary = calculate_compliance(
                reading_samples, lower_samples, upper_samples, target_samples
            )
        except Exception as exc:
            logger.warning("Compliance calculation failed for variable %s: %s", var.id, exc)
            return CepVariableResult(
                variable_id=var.id,
                code=var.code,
                name=var.name,
                equipment_id=var.equipment_id,
                section_id=var.section_id,
                variable_type_id=var.variable_type_id,
                status="error",
            )

        # Determine status
        total_classifiable = summary.total_classifiable
        no_data_count = summary.no_data

        if total_classifiable == 0 and no_data_count == 0:
            # No points at all — no_data
            status = "no_data"
            conformity_pct = None
        elif total_classifiable == 0:
            # Only SEM_DADOS points
            status = "no_data"
            conformity_pct = None
        else:
            status = "processed"
            conformity_pct = summary.conformity_pct

        non_conformant = summary.non_conformant_below + summary.non_conformant_above

        return CepVariableResult(
            variable_id=var.id,
            code=var.code,
            name=var.name,
            equipment_id=var.equipment_id,
            section_id=var.section_id,
            variable_type_id=var.variable_type_id,
            conformity_pct=conformity_pct,
            total_points=summary.total_classifiable + summary.no_data,
            conformant=summary.conformant,
            non_conformant=non_conformant,
            no_data=summary.no_data,
            status=status,  # type: ignore[arg-type]
        )

    # -- Result building --

    def _build_result(
        self,
        query_id: str,
        materialized_data: MaterializedAnalysisData,
        variable_results: list[CepVariableResult],
        recorded_series: list[CepRecordedSeries],
        recorded_metadata: dict[str, object],
        acquisition_diagnostics: list[CepDiagnostic],
        interpolated_data: dict[str, list[PiValue]],
        resolved_webid_count: int,
        analysis_started_at: datetime,
    ) -> CepAnalysisResult:
        """Build the final analysis result."""
        # Summary
        total = len(variable_results)
        conformant = sum(1 for v in variable_results if v.status == "processed" and v.non_conformant == 0)
        non_conformant = sum(1 for v in variable_results if v.status == "processed" and v.non_conformant > 0)
        no_data = sum(1 for v in variable_results if v.status == "no_data")
        failed = sum(1 for v in variable_results if v.status == "error")

        # overall_pct
        eligible_conformant = sum(v.conformant for v in variable_results if v.status == "processed")
        eligible_total = sum(v.conformant + v.non_conformant for v in variable_results if v.status == "processed")
        overall_pct = (eligible_conformant / eligible_total * 100) if eligible_total > 0 else None

        # analysis_status
        has_useful = any(v.status == "processed" for v in variable_results)
        has_error = any(v.status == "error" for v in variable_results)
        if not has_error:
            analysis_status = "completed"
        elif has_useful:
            analysis_status = "partial"
        else:
            analysis_status = "failed"

        summary = CepAnalysisSummary(
            analysis_status=analysis_status,  # type: ignore[arg-type]
            overall_pct=overall_pct,
            total_variables=total,
            conformant_variables=conformant,
            non_conformant_variables=non_conformant,
            no_data_variables=no_data,
            failed_variables=failed,
            period_start=materialized_data.request.start_time,
            period_end=materialized_data.request.end_time,
        )

        # Diagnostics
        diagnostics = self._build_diagnostics(variable_results, recorded_metadata)
        tag_names = {tag.id: tag.pi_tag_name for tag in materialized_data.unique_tags}
        tag_variable_map = materialized_data.tag_variable_map
        for diagnostic in acquisition_diagnostics:
            diagnostics.append(diagnostic.model_copy(update={
                "tag_name": diagnostic.tag_name or tag_names.get(diagnostic.tag_id, ""),
                "variable_ids": diagnostic.variable_ids or tag_variable_map.get(diagnostic.tag_id, []),
            }))

        # Metadata
        rec_limit = recorded_metadata.get("recorded_total_point_limit", 0)
        rec_returned = recorded_metadata.get("recorded_returned_point_count", 0)
        rec_reached = recorded_metadata.get("recorded_total_limit_reached", False)
        rec_not_acquired = recorded_metadata.get("recorded_tags_not_acquired", [])

        metadata = CepAnalysisMetadata(
            pi_request_count=resolved_webid_count,
            pi_points_received=sum(len(points) for points in interpolated_data.values()),
            points_returned=sum(v.total_points for v in variable_results),
            tags_processed=resolved_webid_count,
            tags_failed=sum(
                1
                for d in diagnostics
                if d.error_code in {"TAG_NOT_FOUND", "WEBID_RESOLUTION_FAILED", "PI_INTERPOLATED_FAILED"}
            ),
            webid_resolved=resolved_webid_count,
            duration_ms=int((datetime.now(UTC) - analysis_started_at).total_seconds() * 1000),
            recorded_total_point_limit=rec_limit if isinstance(rec_limit, int) else 0,
            recorded_returned_point_count=rec_returned if isinstance(rec_returned, int) else 0,
            recorded_total_limit_reached=rec_reached if isinstance(rec_reached, bool) else False,
            recorded_tags_not_acquired=rec_not_acquired if isinstance(rec_not_acquired, list) else [],
        )

        # Build result
        result = CepAnalysisResult(
            query_id=query_id,
            query_status="completed" if analysis_status != "failed" else "failed",
            summary=summary,
            variables=variable_results,
            diagnostics=diagnostics,
            recorded_series=recorded_series if materialized_data.request.include_recorded else None,
            metadata=metadata,
        )

        return result

    def _build_diagnostics(
        self,
        variable_results: list[CepVariableResult],
        recorded_metadata: dict[str, object],
    ) -> list[CepDiagnostic]:
        """Build diagnostics for failed variables and recorded limits."""
        diagnostics: list[CepDiagnostic] = []

        # Diagnostics for error variables
        for var in variable_results:
            if var.status == "error":
                diagnostics.append(CepDiagnostic(
                    tag_id=0,
                    tag_name="",
                    variable_ids=[var.variable_id],
                    error_code="VARIABLE_CALCULATION_ERROR",
                    message=f"Falha no cálculo da variável {var.code}.",
                ))

        # Diagnostics for recorded total limit
        if recorded_metadata.get("recorded_total_limit_reached"):
            not_acquired = recorded_metadata.get("recorded_tags_not_acquired", [])
            if isinstance(not_acquired, list):
                for tag_name in not_acquired:
                    diagnostics.append(CepDiagnostic(
                        tag_id=0,
                        tag_name=str(tag_name),
                        variable_ids=[],
                        error_code="CEP_RECORDED_TOTAL_LIMIT_REACHED",
                        message=f"Tag {tag_name} não adquirida devido ao limite agregado de pontos Recorded.",
                    ))

        return diagnostics

    def _determine_status(
        self, variable_results: list[CepVariableResult]
    ) -> str:
        """Determine the terminal query status."""
        has_useful = any(v.status == "processed" for v in variable_results)
        has_error = any(v.status == "error" for v in variable_results)

        if has_useful or not has_error:
            return "completed"
        return "failed"

    def _build_error_result(
        self, query_id: str, exc: Exception
    ) -> CepAnalysisResult:
        """Build a result for an unhandled error."""
        now = datetime.now(UTC)
        summary = CepAnalysisSummary(
            analysis_status="failed",
            total_variables=0,
            period_start=now,
            period_end=now,
        )
        return CepAnalysisResult(
            query_id=query_id,
            query_status="failed",
            summary=summary,
            variables=[],
            diagnostics=[
                CepDiagnostic(
                    tag_id=0,
                    tag_name="",
                    variable_ids=[],
                    error_code="INTERNAL_ERROR",
                    message=str(exc),
                )
            ],
            metadata=CepAnalysisMetadata(),
        )
