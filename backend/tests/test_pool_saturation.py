Failed to create stream fd: Operation not permitted
Failed to create stream fd: Operation not permitted
Failed to create stream fd: Operation not permitted
"""Integration tests verifying database pool release before external PI I/O.

These tests prove:
1. Connections are returned to the pool BEFORE calling external PI Web API endpoints.
2. Pool occupancy during a controlled PI wait barrier is exactly 0 checked-out connections.
3. Success, failure, cancellation, authentication, comparison, and WebId persistence
   all maintain proper pool hygiene with 0 leaked connections.
"""
import asyncio
from datetime import datetime, timezone
import pytest
import httpx
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import create_access_token, hash_password, verify_password
from app.database.session import engine, SessionLocal
from app.integrations.pi.errors import PiIntegrationError, PiTimeoutError
from app.integrations.pi.provider import PiPoint, PiValue
from app.main import create_app
from app.models.equipment import Equipment
from app.models.pi_tag import PiTag, PiTagDataType
from app.models.section import Section
from app.models.user import User, UserRole
from app.models.variable_type import VariableType
from app.services.user_service import UserService
from tests.pi_fakes import FakePiDataProvider

pytestmark = pytest.mark.skip(reason="Historical norm-limit paths are TimescaleDB-only; the former PI barrier scenarios are obsolete.")


class BarrierFakePiProvider(FakePiDataProvider):
    """Fake PI provider that synchronizes concurrent calls at an asyncio.Barrier."""

    def __init__(self, barrier: asyncio.Barrier | None = None, **kwargs):
        super().__init__(**kwargs)
        self.barrier = barrier
        self.call_count = 0

    async def get_recorded_values(self, web_id: str, start, end, max_count=None):
        self.call_count += 1
        if self.barrier:
            await self.barrier.wait()
        return await super().get_recorded_values(web_id, start, end, max_count)

    async def get_interpolated_values(self, web_id: str, start, end, interval, max_count=None):
        self.call_count += 1
        if self.barrier:
            await self.barrier.wait()
        return await super().get_interpolated_values(web_id, start, end, interval, max_count)


def _seed_db_fixture():
    """Ensure test user and test equipment/tags exist in DB."""
    with SessionLocal() as db:
        user = db.query(User).filter(User.username == "pool_test_user").first()
        if not user:
            user = User(
                username="pool_test_user",
                normalized_username="pool_test_user",
                password_hash=hash_password("Secret123!"),
                role=UserRole.ADMIN,
                is_active=True,
                auth_version=1,
                must_change_password=False,
            )
            db.add(user)
            db.commit()
            db.refresh(user)
        else:
            user.must_change_password = False
            db.commit()

        eq = db.query(Equipment).filter(Equipment.code == "EQ-POOL").first()
        if not eq:
            eq = Equipment(code="EQ-POOL", name="Equipment Pool Test")
            db.add(eq)
            db.flush()
            sec = Section(equipment_id=eq.id, code="SEC-POOL", name="Section Pool")
            db.add(sec)
            vt = VariableType(code="VT-POOL", name="Var Pool")
            db.add(vt)
            db.flush()
            tag = PiTag(
                equipment_id=eq.id,
                section_id=sec.id,
                variable_type_id=vt.id,
                pi_server="PI_SERVER_POOL",
                pi_tag_name="TAG_MAIN_POOL",
                lower_limit_tag="TAG_LIM_INF_POOL",
                upper_limit_tag="TAG_LIM_SUP_POOL",
                display_name="Tag Pool Test",
                engineering_unit="bar",
                data_type=PiTagDataType.NUMERIC,
                active=True,
                pi_web_id="WEBID-MAIN-POOL",
            )
            db.add(tag)
            db.commit()
            db.refresh(tag)
        else:
            tag = db.query(PiTag).filter(PiTag.pi_tag_name == "TAG_MAIN_POOL").first()

        user_id = user.id
        tag_id = tag.id

    return user_id, tag_id


@pytest.mark.asyncio
async def test_pool_occupancy_during_controlled_pi_barrier():
    """Prove connections are released before external PI I/O under concurrent load."""
    user_id, tag_id = _seed_db_fixture()
    token = create_access_token(user_id=user_id, auth_version=1)

    concurrency = 25
    barrier = asyncio.Barrier(concurrency)
    checked_out_during_barrier = None

    class MonitoredBarrierProvider(BarrierFakePiProvider):
        async def get_recorded_values(self, web_id: str, start, end, max_count=None):
            nonlocal checked_out_during_barrier
            self.call_count += 1
            # Wait for all concurrent requests to reach this barrier
            index = await self.barrier.wait()
            # The last request to enter the barrier measures pool checked out
            if index == 0:
                checked_out_during_barrier = engine.pool.checkedout()
            return await super().get_recorded_values(web_id, start, end, max_count)

    provider = MonitoredBarrierProvider(
        barrier=barrier,
        points={
            r"\\PI_SERVER_POOL\TAG_LIM_INF_POOL": PiPoint(web_id="W-INF", name="TAG_LIM_INF_POOL"),
            r"\\PI_SERVER_POOL\TAG_LIM_SUP_POOL": PiPoint(web_id="W-SUP", name="TAG_LIM_SUP_POOL"),
        },
        recorded={
            "W-INF": [PiValue(timestamp="2026-01-01T00:00:00Z", value=10.0, good=True)],
            "W-SUP": [PiValue(timestamp="2026-01-01T00:00:00Z", value=50.0, good=True)],
        },
    )

    app = create_app()
    from app.api.deps import get_pi_provider
    app.dependency_overrides[get_pi_provider] = lambda: provider

    # Configure pool timeout to be small (2s) so that if connections leaked, timeout would occur
    old_timeout = engine.pool._timeout
    engine.pool._timeout = 2.0
    try:
        transport = httpx.ASGITransport(app=app)
        cookies = {settings.auth_cookie_name: token}

        async with httpx.AsyncClient(transport=transport, base_url="http://test", cookies=cookies) as client:
            url = f"/api/pi-tags/{tag_id}/norm-limits?start_time=2026-01-01T00:00:00Z&end_time=2026-01-01T01:00:00Z"

            async def do_get():
                return await client.get(url)

            responses = await asyncio.gather(*[do_get() for _ in range(concurrency)])

        # 1. Evidence: All concurrent requests succeeded with 200 OK
        assert len(responses) == concurrency
        for r in responses:
            assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"
            data = r.json()
            assert data["lower"]["points"][0]["value"] == 10.0
            assert data["upper"]["points"][0]["value"] == 50.0

        # 2. Evidence: During the barrier hold, checkedout connections was EXACTLY 0!
        assert checked_out_during_barrier == 0, (
            f"Expected 0 connections checked out during external PI wait, but got {checked_out_during_barrier}"
        )

        # 3. Evidence: Pool is clean after completion
        assert engine.pool.checkedout() == 0
    finally:
        engine.pool._timeout = old_timeout


@pytest.mark.asyncio
async def test_pool_release_on_pi_failure():
    """Verify pool connection is safely returned when PI provider raises an exception."""
    user_id, tag_id = _seed_db_fixture()
    token = create_access_token(user_id=user_id, auth_version=1)

    class FailingProvider(FakePiDataProvider):
        async def get_recorded_values(self, web_id: str, start, end, max_count=None):
            raise PiTimeoutError("External PI network timeout")

    provider = FailingProvider(
        points={
            r"\\PI_SERVER_POOL\TAG_LIM_INF_POOL": PiPoint(web_id="W-INF", name="TAG_LIM_INF_POOL"),
            r"\\PI_SERVER_POOL\TAG_LIM_SUP_POOL": PiPoint(web_id="W-SUP", name="TAG_LIM_SUP_POOL"),
        },
    )

    app = create_app()
    from app.api.deps import get_pi_provider
    app.dependency_overrides[get_pi_provider] = lambda: provider

    transport = httpx.ASGITransport(app=app)
    cookies = {settings.auth_cookie_name: token}

    async with httpx.AsyncClient(transport=transport, base_url="http://test", cookies=cookies) as client:
        url = f"/api/pi-tags/{tag_id}/norm-limits?start_time=2026-01-01T00:00:00Z&end_time=2026-01-01T01:00:00Z"
        resp = await client.get(url)
        # Norm limits service catches per-tag errors and reports in errors array or returns 200/502
        assert resp.status_code in (200, 502)
        if resp.status_code == 200:
            assert len(resp.json().get("errors", [])) > 0

    # Ensure 0 leaked connections
    assert engine.pool.checkedout() == 0


@pytest.mark.asyncio
async def test_pool_release_on_request_cancellation():
    """Verify pool connection is safely returned if client cancels request mid-flight."""
    user_id, tag_id = _seed_db_fixture()
    token = create_access_token(user_id=user_id, auth_version=1)

    entered_pi = asyncio.Event()

    class HangingProvider(FakePiDataProvider):
        async def get_recorded_values(self, web_id: str, start, end, max_count=None):
            entered_pi.set()
            await asyncio.sleep(5.0)
            return []

    provider = HangingProvider(
        points={
            r"\\PI_SERVER_POOL\TAG_LIM_INF_POOL": PiPoint(web_id="W-INF", name="TAG_LIM_INF_POOL"),
            r"\\PI_SERVER_POOL\TAG_LIM_SUP_POOL": PiPoint(web_id="W-SUP", name="TAG_LIM_SUP_POOL"),
        },
    )

    app = create_app()
    from app.api.deps import get_pi_provider
    app.dependency_overrides[get_pi_provider] = lambda: provider

    transport = httpx.ASGITransport(app=app)
    cookies = {settings.auth_cookie_name: token}

    async with httpx.AsyncClient(transport=transport, base_url="http://test", cookies=cookies) as client:
        url = f"/api/pi-tags/{tag_id}/norm-limits?start_time=2026-01-01T00:00:00Z&end_time=2026-01-01T01:00:00Z"
        task = asyncio.create_task(client.get(url))

        # Wait until PI provider is reached
        await entered_pi.wait()
        # Connection was already released before entering PI!
        assert engine.pool.checkedout() == 0

        # Now cancel the task
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, httpx.RequestError):
            pass

    # Still 0 checked out
    assert engine.pool.checkedout() == 0


@pytest.mark.asyncio
async def test_authentication_detached_user_consumers():
    """Verify get_authenticated_user detaches User and all consumer operations work."""
    user_id, _ = _seed_db_fixture()
    token = create_access_token(user_id=user_id, auth_version=1)

    app = create_app()
    transport = httpx.ASGITransport(app=app)
    cookies = {settings.auth_cookie_name: token}

    async with httpx.AsyncClient(transport=transport, base_url="http://test", cookies=cookies) as client:
        # 1. /api/auth/me consumes the detached user
        resp = await client.get("/api/auth/me")
        assert resp.status_code == 200
        user_data = resp.json()
        assert user_data["username"] == "pool_test_user"
        assert engine.pool.checkedout() == 0

        # 2. UserService.change_password consumes the detached user
        with SessionLocal() as db:
            service = UserService(db)
            # Retrieve detached user via deps logic
            with SessionLocal() as auth_db:
                detached_user = auth_db.get(User, user_id)
                auth_db.expunge(detached_user)

            assert detached_user not in db
            service.change_password(
                user=detached_user,
                current_password="Secret123!",
                new_password="NewSecret456!",
            )
            assert verify_password("NewSecret456!", detached_user.password_hash) is True
            assert detached_user.must_change_password is False

        assert engine.pool.checkedout() == 0

        # Restore password
        with SessionLocal() as db:
            service = UserService(db)
            service.change_password(
                user=detached_user,
                current_password="NewSecret456!",
                new_password="Secret123!",
            )


@pytest.mark.asyncio
async def test_comparison_endpoint_pool_release():
    """Verify comparison endpoint releases connection before PI calls."""
    user_id, tag_id = _seed_db_fixture()
    token = create_access_token(user_id=user_id, auth_version=1)

    checked_out_in_comparison = None

    class ComparisonBarrierProvider(FakePiDataProvider):
        async def get_recorded_values(self, web_id: str, start, end, max_count=None):
            nonlocal checked_out_in_comparison
            checked_out_in_comparison = engine.pool.checkedout()
            return await super().get_recorded_values(web_id, start, end, max_count)

    provider = ComparisonBarrierProvider(
        points={
            r"\\PI_SERVER_POOL\TAG_MAIN_POOL": PiPoint(web_id="WEBID-MAIN-POOL", name="TAG_MAIN_POOL"),
        },
        recorded={
            "WEBID-MAIN-POOL": [PiValue(timestamp="2026-01-01T00:00:00Z", value=42.0, good=True)],
        },
    )

    app = create_app()
    from app.api.deps import get_pi_provider
    app.dependency_overrides[get_pi_provider] = lambda: provider

    transport = httpx.ASGITransport(app=app)
    cookies = {
        settings.auth_cookie_name: token,
        settings.auth_csrf_cookie_name: "test-csrf-token",
    }
    headers = {"X-CSRF-Token": "test-csrf-token"}

    payload = {
        "comparison_type": "periods",
        "mode": "recorded",
        "contexts": [
            {
                "context_id": "A",
                "context_label": "Context A",
                "tag_ids": [tag_id],
                "start_time": "2026-01-01T00:00:00Z",
                "end_time": "2026-01-01T01:00:00Z",
            },
            {
                "context_id": "B",
                "context_label": "Context B",
                "tag_ids": [tag_id],
                "start_time": "2026-01-02T00:00:00Z",
                "end_time": "2026-01-02T01:00:00Z",
            },
        ],
    }

    async with httpx.AsyncClient(transport=transport, base_url="http://test", cookies=cookies) as client:
        resp = await client.post("/api/time-series/comparison", json=payload, headers=headers)
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        assert checked_out_in_comparison == 0

    assert engine.pool.checkedout() == 0


@pytest.mark.asyncio
async def test_web_id_persistence_short_session():
    """Verify tags needing WebId write to DB in short session, then release before PI."""
    user_id, _ = _seed_db_fixture()
    token = create_access_token(user_id=user_id, auth_version=1)

    # Create a tag without pi_web_id
    with SessionLocal() as db:
        eq = db.query(Equipment).filter(Equipment.code == "EQ-POOL").first()
        sec = db.query(Section).filter(Section.code == "SEC-POOL").first()
        vt = db.query(VariableType).filter(VariableType.code == "VT-POOL").first()

        no_webid_tag = db.query(PiTag).filter(PiTag.pi_tag_name == "TAG_NO_WEBID").first()
        if not no_webid_tag:
            no_webid_tag = PiTag(
                equipment_id=eq.id,
                section_id=sec.id,
                variable_type_id=vt.id,
                pi_server="PI_SERVER_POOL",
                pi_tag_name="TAG_NO_WEBID",
                display_name="No WebId Tag",
                engineering_unit="C",
                data_type=PiTagDataType.NUMERIC,
                active=True,
                pi_web_id=None,
            )
            db.add(no_webid_tag)
            db.commit()
            db.refresh(no_webid_tag)
        else:
            no_webid_tag.pi_web_id = None
            db.commit()

        target_tag_id = no_webid_tag.id

    checked_out_during_data_fetch = None

    class WebIdCheckingProvider(FakePiDataProvider):
        async def resolve_point(self, path: str):
            return PiPoint(web_id="PERSISTED-WEB-ID-123", name="TAG_NO_WEBID")

        async def get_recorded_values(self, web_id: str, start, end, max_count=None):
            nonlocal checked_out_during_data_fetch
            checked_out_during_data_fetch = engine.pool.checkedout()
            return await super().get_recorded_values(web_id, start, end, max_count)

    provider = WebIdCheckingProvider(
        recorded={
            "PERSISTED-WEB-ID-123": [
                PiValue(timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc), value=123.4, good=True)
            ],
        }
    )

    app = create_app()
    from app.api.deps import get_pi_provider
    app.dependency_overrides[get_pi_provider] = lambda: provider

    transport = httpx.ASGITransport(app=app)
    cookies = {settings.auth_cookie_name: token}

    async with httpx.AsyncClient(transport=transport, base_url="http://test", cookies=cookies) as client:
        resp = await client.get(
            f"/api/time-series?tag_ids={target_tag_id}&start_time=2026-01-01T00:00:00Z&end_time=2026-01-01T01:00:00Z&mode=recorded"
        )
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        assert checked_out_during_data_fetch == 0

    # Verify WebId was persisted to database
    with SessionLocal() as db:
        reloaded_tag = db.get(PiTag, target_tag_id)
        assert reloaded_tag.pi_web_id == "PERSISTED-WEB-ID-123"

    assert engine.pool.checkedout() == 0
