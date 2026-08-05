"""Tests for CEP API endpoints — HTTP contract, serialization, lifecycle."""
from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime

from fastapi.testclient import TestClient

from app.api.deps import get_db_session, get_pi_provider, get_query_registry_dep
from app.api.cep import _load_and_materialize
from app.core.config import settings
from app.models.cep_variable import CepVariable
from app.models.equipment import Equipment
from app.models.pi_tag import PiTag, PiTagDataType, PiTagValidationStatus
from app.models.section import Section
from app.models.variable_type import VariableType
from app.schemas.cep_analysis import CepAnalysisRequest
from app.services.cep_query_store import CepQueryStore, get_cep_query_store
from app.services.query_registry import get_query_registry


def _setup_db(db_session):
    """Create test data: equipment, section, variable_type, pi_tags, cep_variable."""
    eq = Equipment(code="RB1", name="RB1", active=True)
    db_session.add(eq)
    db_session.flush()

    sec = Section(equipment_id=eq.id, code="SEC1", name="Secao 1", active=True)
    db_session.add(sec)
    db_session.flush()

    vt = VariableType(code="CURRENT", name="CURRENT", active=True)
    db_session.add(vt)
    db_session.flush()

    tags = []
    for i, (name, desc) in enumerate([
        ("LFI_RB1_COR_ESC1", "Leitura"),
        ("LFI_RB1_COR_ESC1_LIM_INF", "Limite inferior"),
        ("LFI_RB1_COR_ESC1_LIM_SUP", "Limite superior"),
    ]):
        tag = PiTag(
            equipment_id=eq.id,
            section_id=sec.id,
            variable_type_id=vt.id,
            pi_server="PI_DATA",
            pi_tag_name=name,
            pi_web_id=f"W{i+1}",
            display_name=desc,
            description=desc,
            data_type=PiTagDataType.NUMERIC,
            active=True,
            validation_status=PiTagValidationStatus.VALID,
        )
        db_session.add(tag)
        tags.append(tag)
    db_session.flush()

    cv = CepVariable(
        equipment_id=eq.id,
        section_id=sec.id,
        variable_type_id=vt.id,
        reading_tag_id=tags[0].id,
        lower_limit_tag_id=tags[1].id,
        upper_limit_tag_id=tags[2].id,
        code="ESC_01",
        name="Escova 01",
        active=True,
    )
    db_session.add(cv)
    db_session.flush()

    return eq, sec, vt, tags, cv


def _make_client(db_session, fake_provider):
    """Create a test client with CEP dependencies."""
    from app.api.deps import get_current_user, validate_csrf
    from app.main import create_app
    from app.models.user import User, UserRole

    app = create_app()

    # Fresh store and registry for each test
    store = CepQueryStore()

    def _db_override():
        db = db_session
        try:
            yield db
        finally:
            pass

    def _provider_override():
        return fake_provider

    def _store_override():
        return store

    def _registry_override():
        return get_query_registry()

    def _authenticated_user():
        user = db_session.query(User).filter(User.normalized_username == "test-admin").first()
        if not user:
            user = User(
                username="test-admin",
                normalized_username="test-admin",
                password_hash="test-hash",
                role=UserRole.ADMIN,
                is_active=True,
                auth_version=1,
                must_change_password=False,
            )
            db_session.add(user)
            db_session.commit()
            db_session.refresh(user)
        db_session.expunge(user)
        return user

    from app.database.session import get_db
    app.dependency_overrides[get_db] = _db_override
    app.dependency_overrides[get_db_session] = _db_override
    app.dependency_overrides[get_pi_provider] = _provider_override
    app.dependency_overrides[get_cep_query_store] = _store_override
    app.dependency_overrides[get_query_registry_dep] = _registry_override
    app.dependency_overrides[get_current_user] = _authenticated_user
    app.dependency_overrides[validate_csrf] = lambda: None

    return TestClient(app), store


def test_materialization_uses_grouped_limit_tags_from_reading_registration(db_session) -> None:
    eq = Equipment(code="RB1", name="RB1", active=True)
    db_session.add(eq)
    db_session.flush()
    sec = Section(equipment_id=eq.id, code="SEC1", name="Secao 1", active=True)
    vt = VariableType(code="CURRENT", name="CURRENT", active=True)
    db_session.add_all([sec, vt])
    db_session.flush()

    reading = PiTag(
        equipment_id=eq.id, section_id=sec.id, variable_type_id=vt.id,
        pi_server="PIMS", pi_tag_name="PV_CORRETA", pi_web_id="WEBID_PV",
        lower_limit_tag="LIM_INF_CORRETO", upper_limit_tag="LIM_SUP_CORRETO",
        display_name="Escova 01", data_type=PiTagDataType.NUMERIC, active=True,
        validation_status=PiTagValidationStatus.VALID,
    )
    wrong_lower = PiTag(
        equipment_id=eq.id, section_id=sec.id, variable_type_id=vt.id,
        pi_server="PIMS", pi_tag_name="PV_DE_OUTRA_VARIAVEL", display_name="Outro",
        data_type=PiTagDataType.NUMERIC, active=True,
        validation_status=PiTagValidationStatus.VALID,
    )
    wrong_upper = PiTag(
        equipment_id=eq.id, section_id=sec.id, variable_type_id=vt.id,
        pi_server="PIMS", pi_tag_name="OUTRO_LIMITE", display_name="Outro limite",
        data_type=PiTagDataType.NUMERIC, active=True,
        validation_status=PiTagValidationStatus.VALID,
    )
    db_session.add_all([reading, wrong_lower, wrong_upper])
    db_session.flush()
    db_session.add(CepVariable(
        equipment_id=eq.id, section_id=sec.id, variable_type_id=vt.id,
        reading_tag_id=reading.id, lower_limit_tag_id=wrong_lower.id,
        upper_limit_tag_id=wrong_upper.id, code="ESC_01", name="Escova 01", active=True,
    ))
    db_session.commit()
    assert db_session.query(CepVariable).count() == 1

    materialized = _load_and_materialize(db_session, CepAnalysisRequest(
        start_time=datetime(2026, 8, 4, 15, 35, tzinfo=UTC),
        end_time=datetime(2026, 8, 4, 16, 5, tzinfo=UTC),
    ))

    variable = materialized.variables[0]
    tags_by_id = {tag.id: tag for tag in materialized.unique_tags}
    assert tags_by_id[variable.reading_tag_id].pi_tag_name == "PV_CORRETA"
    assert tags_by_id[variable.lower_limit_tag_id].pi_tag_name == "LIM_INF_CORRETO"
    assert tags_by_id[variable.upper_limit_tag_id].pi_tag_name == "LIM_SUP_CORRETO"
    assert "PV_DE_OUTRA_VARIAVEL" not in {tag.pi_tag_name for tag in materialized.unique_tags}


# ---------------------------------------------------------------------------
# POST /api/cep/analyze
# ---------------------------------------------------------------------------


class TestCreateAnalysis:
    """Tests for POST /api/cep/analyze."""

    def test_success_202(self, db_session, fake_provider):
        """POST returns 202 with query_id and query_status=pending."""
        _setup_db(db_session)
        client, store = _make_client(db_session, fake_provider)

        resp = client.post("/api/cep/analyze", json={
            "start_time": "2026-01-01T00:00:00Z",
            "end_time": "2026-01-02T00:00:00Z",
        })
        assert resp.status_code == 202
        data = resp.json()
        assert "query_id" in data
        assert data["query_status"] == "pending"

    def test_naive_timestamp_rejected_422(self, db_session, fake_provider):
        """Timestamp without timezone returns 422."""
        _setup_db(db_session)
        client, _ = _make_client(db_session, fake_provider)

        resp = client.post("/api/cep/analyze", json={
            "start_time": "2026-01-01T00:00:00",
            "end_time": "2026-01-02T00:00:00",
        })
        assert resp.status_code == 422

    def test_start_after_end_400(self, db_session, fake_provider):
        """start_time >= end_time returns 400."""
        _setup_db(db_session)
        client, _ = _make_client(db_session, fake_provider)

        resp = client.post("/api/cep/analyze", json={
            "start_time": "2026-01-02T00:00:00Z",
            "end_time": "2026-01-01T00:00:00Z",
        })
        assert resp.status_code == 400

    def test_period_too_long_400(self, db_session, fake_provider):
        """Period exceeding max_days returns 400."""
        _setup_db(db_session)
        client, _ = _make_client(db_session, fake_provider)

        max_days = settings.pi_query_max_period_days
        resp = client.post("/api/cep/analyze", json={
            "start_time": "2026-01-01T00:00:00Z",
            "end_time": "2026-01-01T00:00:00Z",
        })
        # This should fail because start >= end, not because of period
        # Let's use a valid but too-long period
        from datetime import timedelta
        start = datetime(2026, 1, 1, tzinfo=UTC)
        end = start + timedelta(days=max_days + 1)
        resp = client.post("/api/cep/analyze", json={
            "start_time": start.isoformat().replace("+00:00", "Z"),
            "end_time": end.isoformat().replace("+00:00", "Z"),
        })
        assert resp.status_code == 400

    def test_no_variables_422(self, db_session, fake_provider):
        """Filters with no active variables return 422."""
        _setup_db(db_session)
        client, _ = _make_client(db_session, fake_provider)

        resp = client.post("/api/cep/analyze", json={
            "start_time": "2026-01-01T00:00:00Z",
            "end_time": "2026-01-02T00:00:00Z",
            "equipment_id": 9999,
        })
        assert resp.status_code == 422

    def test_exceed_max_variables_422(self, db_session, fake_provider):
        """Selection exceeding pi_cep_max_variables returns 422."""
        _setup_db(db_session)
        client, _ = _make_client(db_session, fake_provider)

        # Create many variables
        eq = db_session.query(Equipment).first()
        sec = db_session.query(Section).first()
        vt = db_session.query(VariableType).first()
        tags = db_session.query(PiTag).all()

        for i in range(settings.pi_cep_max_variables + 1):
            tag = PiTag(
                equipment_id=eq.id, section_id=sec.id, variable_type_id=vt.id,
                pi_server="PI_DATA", pi_tag_name=f"EXTRA_{i}",
                pi_web_id=f"W_EXTRA_{i}", display_name=f"Extra {i}",
                data_type=PiTagDataType.NUMERIC, active=True,
                validation_status=PiTagValidationStatus.VALID,
            )
            db_session.add(tag)
            db_session.flush()

            cv = CepVariable(
                equipment_id=eq.id, section_id=sec.id, variable_type_id=vt.id,
                reading_tag_id=tag.id, lower_limit_tag_id=tags[1].id,
                upper_limit_tag_id=tags[2].id,
                code=f"EXTRA_{i:03d}", name=f"Extra {i}", active=True,
            )
            db_session.add(cv)
        db_session.commit()

        resp = client.post("/api/cep/analyze", json={
            "start_time": "2026-01-01T00:00:00Z",
            "end_time": "2026-01-02T00:00:00Z",
        })
        assert resp.status_code == 422

    def test_include_recorded_true(self, db_session, fake_provider):
        """include_recorded=true is accepted."""
        _setup_db(db_session)
        client, _ = _make_client(db_session, fake_provider)

        resp = client.post("/api/cep/analyze", json={
            "start_time": "2026-01-01T00:00:00Z",
            "end_time": "2026-01-02T00:00:00Z",
            "include_recorded": True,
        })
        assert resp.status_code == 202


# ---------------------------------------------------------------------------
# GET /api/cep/analyze/{query_id}
# ---------------------------------------------------------------------------


class TestGetAnalysis:
    """Tests for GET /api/cep/analyze/{query_id}."""

    def test_pending_returns_200(self, db_session, fake_provider):
        """GET for pending operation returns 200 with pending status."""
        _setup_db(db_session)
        client, store = _make_client(db_session, fake_provider)

        # Create a pending operation directly
        import uuid
        qid = str(uuid.uuid4())
        req = CepAnalysisRequest(
            start_time=datetime(2026, 1, 1, tzinfo=UTC),
            end_time=datetime(2026, 1, 2, tzinfo=UTC),
        )
        asyncio.get_event_loop().run_until_complete(store.register(qid, req))

        resp = client.get(f"/api/cep/analyze/{qid}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["query_status"] == "pending"

    def test_not_found_404(self, db_session, fake_provider):
        """GET for non-existent query_id returns 404."""
        _setup_db(db_session)
        client, _ = _make_client(db_session, fake_provider)

        resp = client.get("/api/cep/analyze/nonexistent")
        assert resp.status_code == 404

    def test_expired_returns_404(self, db_session, fake_provider):
        """GET for expired terminal operation returns 404."""
        _setup_db(db_session)
        client, store = _make_client(db_session, fake_provider)

        import uuid

        from app.schemas.cep_analysis import (
            CepAnalysisMetadata,
            CepAnalysisResult,
            CepAnalysisSummary,
        )

        qid = str(uuid.uuid4())
        req = CepAnalysisRequest(
            start_time=datetime(2026, 1, 1, tzinfo=UTC),
            end_time=datetime(2026, 1, 2, tzinfo=UTC),
        )
        entry = asyncio.get_event_loop().run_until_complete(store.register(qid, req))

        # Force expired terminal
        now = datetime.now(UTC)
        result = CepAnalysisResult(
            query_id=qid,
            query_status="completed",
            summary=CepAnalysisSummary(
                analysis_status="completed",
                total_variables=0,
                period_start=now,
                period_end=now,
            ),
            variables=[],
            metadata=CepAnalysisMetadata(),
        )
        asyncio.get_event_loop().run_until_complete(store.set_result(qid, result, "completed"))
        entry = asyncio.get_event_loop().run_until_complete(store.get(qid))
        entry.terminal_at = time.monotonic() - settings.pi_cep_result_ttl_seconds - 1

        resp = client.get(f"/api/cep/analyze/{qid}")
        assert resp.status_code == 404

    def test_completed_returns_200(self, db_session, fake_provider):
        """GET for completed operation returns 200 with result."""
        _setup_db(db_session)
        client, store = _make_client(db_session, fake_provider)

        import uuid

        from app.schemas.cep_analysis import (
            CepAnalysisMetadata,
            CepAnalysisResult,
            CepAnalysisSummary,
        )

        qid = str(uuid.uuid4())
        req = CepAnalysisRequest(
            start_time=datetime(2026, 1, 1, tzinfo=UTC),
            end_time=datetime(2026, 1, 2, tzinfo=UTC),
        )
        asyncio.get_event_loop().run_until_complete(store.register(qid, req))

        now = datetime.now(UTC)
        result = CepAnalysisResult(
            query_id=qid,
            query_status="completed",
            summary=CepAnalysisSummary(
                analysis_status="completed",
                total_variables=1,
                period_start=now,
                period_end=now,
            ),
            variables=[],
            metadata=CepAnalysisMetadata(),
        )
        asyncio.get_event_loop().run_until_complete(store.set_result(qid, result, "completed"))

        resp = client.get(f"/api/cep/analyze/{qid}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["query_status"] == "completed"

    def test_recorded_series_omitted_when_false(self, db_session, fake_provider):
        """recorded_series is omitted when include_recorded=false."""
        _setup_db(db_session)
        client, store = _make_client(db_session, fake_provider)

        import uuid

        from app.schemas.cep_analysis import (
            CepAnalysisMetadata,
            CepAnalysisResult,
            CepAnalysisSummary,
        )

        qid = str(uuid.uuid4())
        req = CepAnalysisRequest(
            start_time=datetime(2026, 1, 1, tzinfo=UTC),
            end_time=datetime(2026, 1, 2, tzinfo=UTC),
            include_recorded=False,
        )
        asyncio.get_event_loop().run_until_complete(store.register(qid, req))

        now = datetime.now(UTC)
        result = CepAnalysisResult(
            query_id=qid,
            query_status="completed",
            summary=CepAnalysisSummary(
                analysis_status="completed",
                total_variables=0,
                period_start=now,
                period_end=now,
            ),
            variables=[],
            metadata=CepAnalysisMetadata(),
        )
        asyncio.get_event_loop().run_until_complete(store.set_result(qid, result, "completed"))

        resp = client.get(f"/api/cep/analyze/{qid}")
        assert resp.status_code == 200
        data = resp.json()
        assert "recorded_series" not in data

    def test_recorded_series_present_when_true(self, db_session, fake_provider):
        """recorded_series is present when include_recorded=true."""
        _setup_db(db_session)
        client, store = _make_client(db_session, fake_provider)

        import uuid

        from app.schemas.cep_analysis import (
            CepAnalysisMetadata,
            CepAnalysisResult,
            CepAnalysisSummary,
        )

        qid = str(uuid.uuid4())
        req = CepAnalysisRequest(
            start_time=datetime(2026, 1, 1, tzinfo=UTC),
            end_time=datetime(2026, 1, 2, tzinfo=UTC),
            include_recorded=True,
        )
        asyncio.get_event_loop().run_until_complete(store.register(qid, req))

        now = datetime.now(UTC)
        result = CepAnalysisResult(
            query_id=qid,
            query_status="completed",
            summary=CepAnalysisSummary(
                analysis_status="completed",
                total_variables=0,
                period_start=now,
                period_end=now,
            ),
            variables=[],
            recorded_series=[],
            metadata=CepAnalysisMetadata(),
        )
        asyncio.get_event_loop().run_until_complete(store.set_result(qid, result, "completed"))

        resp = client.get(f"/api/cep/analyze/{qid}")
        assert resp.status_code == 200
        data = resp.json()
        assert "recorded_series" in data

    def test_cancelled_returns_200(self, db_session, fake_provider):
        """GET for cancelled operation returns 200."""
        _setup_db(db_session)
        client, store = _make_client(db_session, fake_provider)

        import uuid

        qid = str(uuid.uuid4())
        req = CepAnalysisRequest(
            start_time=datetime(2026, 1, 1, tzinfo=UTC),
            end_time=datetime(2026, 1, 2, tzinfo=UTC),
        )
        asyncio.get_event_loop().run_until_complete(store.register(qid, req))
        asyncio.get_event_loop().run_until_complete(store.set_cancelled(qid))

        resp = client.get(f"/api/cep/analyze/{qid}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["query_status"] == "cancelled"


# ---------------------------------------------------------------------------
# POST /api/cep/analyze/{query_id}/cancel
# ---------------------------------------------------------------------------


class TestCancelAnalysis:
    """Tests for POST /api/cep/analyze/{query_id}/cancel."""

    def test_cancel_pending_200(self, db_session, fake_provider):
        """Cancel pending operation returns 200."""
        _setup_db(db_session)
        client, store = _make_client(db_session, fake_provider)

        import uuid

        qid = str(uuid.uuid4())
        req = CepAnalysisRequest(
            start_time=datetime(2026, 1, 1, tzinfo=UTC),
            end_time=datetime(2026, 1, 2, tzinfo=UTC),
        )
        asyncio.get_event_loop().run_until_complete(store.register(qid, req))

        resp = client.post(f"/api/cep/analyze/{qid}/cancel")
        assert resp.status_code == 200
        data = resp.json()
        assert data["query_status"] == "cancelled"

    def test_cancel_already_cancelled_idempotent(self, db_session, fake_provider):
        """Cancel already cancelled returns 200 (idempotent)."""
        _setup_db(db_session)
        client, store = _make_client(db_session, fake_provider)

        import uuid

        qid = str(uuid.uuid4())
        req = CepAnalysisRequest(
            start_time=datetime(2026, 1, 1, tzinfo=UTC),
            end_time=datetime(2026, 1, 2, tzinfo=UTC),
        )
        asyncio.get_event_loop().run_until_complete(store.register(qid, req))
        asyncio.get_event_loop().run_until_complete(store.set_cancelled(qid))

        resp = client.post(f"/api/cep/analyze/{qid}/cancel")
        assert resp.status_code == 200
        data = resp.json()
        assert data["query_status"] == "cancelled"

    def test_cancel_completed_409(self, db_session, fake_provider):
        """Cancel completed operation returns 409."""
        _setup_db(db_session)
        client, store = _make_client(db_session, fake_provider)

        import uuid

        from app.schemas.cep_analysis import (
            CepAnalysisMetadata,
            CepAnalysisResult,
            CepAnalysisSummary,
        )

        qid = str(uuid.uuid4())
        req = CepAnalysisRequest(
            start_time=datetime(2026, 1, 1, tzinfo=UTC),
            end_time=datetime(2026, 1, 2, tzinfo=UTC),
        )
        asyncio.get_event_loop().run_until_complete(store.register(qid, req))

        now = datetime.now(UTC)
        result = CepAnalysisResult(
            query_id=qid,
            query_status="completed",
            summary=CepAnalysisSummary(
                analysis_status="completed",
                total_variables=0,
                period_start=now,
                period_end=now,
            ),
            variables=[],
            metadata=CepAnalysisMetadata(),
        )
        asyncio.get_event_loop().run_until_complete(store.set_result(qid, result, "completed"))

        resp = client.post(f"/api/cep/analyze/{qid}/cancel")
        assert resp.status_code == 409

    def test_cancel_failed_409(self, db_session, fake_provider):
        """Cancel failed operation returns 409."""
        _setup_db(db_session)
        client, store = _make_client(db_session, fake_provider)

        import uuid

        from app.schemas.cep_analysis import (
            CepAnalysisMetadata,
            CepAnalysisResult,
            CepAnalysisSummary,
        )

        qid = str(uuid.uuid4())
        req = CepAnalysisRequest(
            start_time=datetime(2026, 1, 1, tzinfo=UTC),
            end_time=datetime(2026, 1, 2, tzinfo=UTC),
        )
        asyncio.get_event_loop().run_until_complete(store.register(qid, req))

        now = datetime.now(UTC)
        result = CepAnalysisResult(
            query_id=qid,
            query_status="failed",
            summary=CepAnalysisSummary(
                analysis_status="failed",
                total_variables=0,
                period_start=now,
                period_end=now,
            ),
            variables=[],
            metadata=CepAnalysisMetadata(),
        )
        asyncio.get_event_loop().run_until_complete(store.set_result(qid, result, "failed"))

        resp = client.post(f"/api/cep/analyze/{qid}/cancel")
        assert resp.status_code == 409

    def test_cancel_not_found_404(self, db_session, fake_provider):
        """Cancel non-existent operation returns 404."""
        _setup_db(db_session)
        client, _ = _make_client(db_session, fake_provider)

        resp = client.post("/api/cep/analyze/nonexistent/cancel")
        assert resp.status_code == 404

    def test_cancel_expired_returns_404(self, db_session, fake_provider):
        """Cancel expired terminal operation returns 404."""
        _setup_db(db_session)
        client, store = _make_client(db_session, fake_provider)

        import uuid

        from app.schemas.cep_analysis import (
            CepAnalysisMetadata,
            CepAnalysisResult,
            CepAnalysisSummary,
        )

        qid = str(uuid.uuid4())
        req = CepAnalysisRequest(
            start_time=datetime(2026, 1, 1, tzinfo=UTC),
            end_time=datetime(2026, 1, 2, tzinfo=UTC),
        )
        asyncio.get_event_loop().run_until_complete(store.register(qid, req))

        now = datetime.now(UTC)
        result = CepAnalysisResult(
            query_id=qid,
            query_status="completed",
            summary=CepAnalysisSummary(
                analysis_status="completed",
                total_variables=0,
                period_start=now,
                period_end=now,
            ),
            variables=[],
            metadata=CepAnalysisMetadata(),
        )
        asyncio.get_event_loop().run_until_complete(store.set_result(qid, result, "completed"))
        entry = asyncio.get_event_loop().run_until_complete(store.get(qid))
        entry.terminal_at = time.monotonic() - settings.pi_cep_result_ttl_seconds - 1

        resp = client.post(f"/api/cep/analyze/{qid}/cancel")
        assert resp.status_code == 404
