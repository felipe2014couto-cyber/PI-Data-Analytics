"""Phase 5.9 — Backend performance and load tests.

All tests use mocks/fixtures and do NOT hit a real PI Web API.
Measures: response time, concurrency, tag count impact, memory behavior.
"""
import asyncio
import statistics
import time
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_time_series_response(tag_count: int, points_per_tag: int = 100) -> dict:
    """Build a fake time-series response payload."""
    series = []
    for i in range(tag_count):
        points = []
        base_ts = 1690000000  # fixed timestamp
        for j in range(points_per_tag):
            points.append({
                "timestamp": f"2026-07-01T{j // 3600:02d}:{(j % 3600) // 60:02d}:{j % 60:02d}Z",
                "value": float(j),
                "good": True,
                "questionable": False,
                "substituted": False,
            })
        series.append({
            "tag_id": i + 1,
            "tag_name": f"Tag_{i+1}",
            "display_name": f"Tag {i+1}",
            "unit": "°C",
            "points": points,
            "error": None,
        })
    return {
        "series": series,
        "total_points": tag_count * points_per_tag,
        "errors": [],
        "query_duration_ms": 150,
    }


# ---------------------------------------------------------------------------
# 1. Visual Configuration endpoint performance
# ---------------------------------------------------------------------------

class TestVisualConfigPerformance:
    def test_create_read_update_cycle_under_500ms(self, client: TestClient):
        """Full CRUD cycle should complete well under 500ms."""
        start = time.perf_counter()
        # Create
        r = client.post("/api/visual-configurations", json={
            "name": "perf-test",
            "document": {"schema_version": 1, "visual_rules": {"enabled": False, "selectedSeriesInstanceId": "", "bySeries": {}}},
        })
        assert r.status_code == 201
        cfg_id = r.json()["id"]

        # Read
        client.get(f"/api/visual-configurations/{cfg_id}")
        # Update
        client.put(f"/api/visual-configurations/{cfg_id}", json={
            "expected_version": 1,
            "document": {"schema_version": 1, "visual_rules": {"enabled": True, "selectedSeriesInstanceId": "x", "bySeries": {}}},
        })
        # History
        client.get(f"/api/visual-configurations/{cfg_id}/history")
        # List
        client.get("/api/visual-configurations")
        elapsed = time.perf_counter() - start
        assert elapsed < 0.5, f"CRUD cycle took {elapsed:.3f}s, expected < 0.5s"

    def test_concurrent_creates_from_different_threads(self, client: TestClient):
        """Multiple concurrent create requests should all succeed."""
        def create_one(i):
            return client.post("/api/visual-configurations", json={
                "name": f"concurrent-{i}",
                "document": {"schema_version": 1, "visual_rules": {"enabled": False, "selectedSeriesInstanceId": "", "bySeries": {}}},
            })

        start = time.perf_counter()
        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(create_one, i) for i in range(10)]
            results = [f.result() for f in futures]
        elapsed = time.perf_counter() - start

        statuses = [r.status_code for r in results]
        assert all(s == 201 for s in statuses), f"Some creates failed: {statuses}"
        assert elapsed < 2.0, f"10 concurrent creates took {elapsed:.3f}s"

    def test_list_performance_with_many_configs(self, client: TestClient):
        """Listing should remain fast even with many configs."""
        # Create 50 configs
        for i in range(50):
            client.post("/api/visual-configurations", json={
                "name": f"bulk-{i}",
                "document": {"schema_version": 1, "visual_rules": {"enabled": False, "selectedSeriesInstanceId": "", "bySeries": {}}},
            })

        start = time.perf_counter()
        r = client.get("/api/visual-configurations")
        elapsed = time.perf_counter() - start

        assert r.status_code == 200
        assert len(r.json()) == 50
        assert elapsed < 1.0, f"Listing 50 configs took {elapsed:.3f}s"


# ---------------------------------------------------------------------------
# 2. Response time benchmarks (mocked PI)
# ---------------------------------------------------------------------------

class TestResponseTimeBenchmarks:
    def test_health_endpoint_under_100ms(self, client: TestClient):
        start = time.perf_counter()
        r = client.get("/api/health")
        elapsed = time.perf_counter() - start
        assert r.status_code == 200
        assert elapsed < 0.1, f"Health took {elapsed*1000:.0f}ms"

    def test_pi_health_endpoint_under_200ms(self, client: TestClient):
        start = time.perf_counter()
        r = client.get("/api/pi/health")
        elapsed = time.perf_counter() - start
        assert r.status_code == 200
        assert elapsed < 0.2, f"PI health took {elapsed*1000:.0f}ms"

    def test_auth_login_under_500ms(self, client: TestClient):
        start = time.perf_counter()
        r = client.post("/api/auth/login", json={"username": "test-admin", "password": "admin"})
        elapsed = time.perf_counter() - start
        assert r.status_code == 200
        assert elapsed < 0.5, f"Login took {elapsed*1000:.0f}ms"


# ---------------------------------------------------------------------------
# 3. Tag count impact on visual configuration operations
# ---------------------------------------------------------------------------

class TestTagCountImpact:
    def test_document_with_10_tags_stores_correctly(self, client: TestClient):
        doc = {
            "schema_version": 1,
            "selectedTagIds": list(range(1, 11)),
            "seriesAssignments": [
                {"tagId": i, "order": i - 1, "lineAxis": "primary"}
                for i in range(1, 11)
            ],
            "visual_rules": {"enabled": False, "selectedSeriesInstanceId": "", "bySeries": {}},
        }
        r = client.post("/api/visual-configurations", json={"name": "10-tags", "document": doc})
        assert r.status_code == 201
        cfg_id = r.json()["id"]
        r2 = client.get(f"/api/visual-configurations/{cfg_id}")
        assert r2.status_code == 200
        assert len(r2.json()["document"]["selectedTagIds"]) == 10

    def test_document_with_100_series_rules(self, client: TestClient):
        by_series = {f"series-{i}": {"limits": {"LIE": 0, "LSE": 100}} for i in range(100)}
        doc = {
            "schema_version": 1,
            "visual_rules": {"enabled": True, "selectedSeriesInstanceId": "series-0", "bySeries": by_series},
        }
        r = client.post("/api/visual-configurations", json={"name": "100-rules", "document": doc})
        assert r.status_code == 201

    def test_large_sidebar_state_persists(self, client: TestClient):
        doc = {
            "schema_version": 1,
            "selectedTagIds": list(range(1, 11)),
            "sidebar_state": {
                "filters": {"preset": "P7D", "mode": "recorded", "interval": "10s"},
                "selectedEquipmentIds": list(range(1, 21)),
            },
            "visual_rules": {"enabled": False, "selectedSeriesInstanceId": "", "bySeries": {}},
        }
        r = client.post("/api/visual-configurations", json={"name": "large-sidebar", "document": doc})
        assert r.status_code == 201
        cfg_id = r.json()["id"]
        r2 = client.get(f"/api/visual-configurations/{cfg_id}")
        assert len(r2.json()["document"]["sidebar_state"]["selectedEquipmentIds"]) == 20


# ---------------------------------------------------------------------------
# 4. Optimistic concurrency stress test
# ---------------------------------------------------------------------------

class TestOptimisticConcurrencyStress:
    def test_rapid_updates_with_same_version_only_one_succeeds(self, client: TestClient):
        """When two requests try to update with the same expected_version,
        only the first should succeed; the second gets 409."""
        r = client.post("/api/visual-configurations", json={
            "name": "stress-test",
            "document": {"schema_version": 1, "visual_rules": {"enabled": False, "selectedSeriesInstanceId": "", "bySeries": {}}},
        })
        cfg_id = r.json()["id"]

        def update_with_version(expected):
            return client.put(f"/api/visual-configurations/{cfg_id}", json={
                "expected_version": expected,
                "document": {"schema_version": 1, "visual_rules": {"enabled": True, "selectedSeriesInstanceId": f"x-{expected}", "bySeries": {}}},
            })

        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(update_with_version, 1) for _ in range(5)]
            results = [f.result() for f in futures]

        success_count = sum(1 for r in results if r.status_code == 200)
        conflict_count = sum(1 for r in results if r.status_code == 409)
        assert success_count == 1, f"Expected 1 success, got {success_count}"
        assert conflict_count == 4, f"Expected 4 conflicts, got {conflict_count}"


# ---------------------------------------------------------------------------
# 5. Error response time
# ---------------------------------------------------------------------------

class TestErrorPerformance:
    def test_404_is_fast(self, client: TestClient):
        start = time.perf_counter()
        r = client.get("/api/visual-configurations/nonexistent-id")
        elapsed = time.perf_counter() - start
        assert r.status_code == 404
        assert elapsed < 0.1

    def test_422_is_fast(self, client: TestClient):
        start = time.perf_counter()
        r = client.post("/api/visual-configurations", json={"name": ""})
        elapsed = time.perf_counter() - start
        assert r.status_code == 422
        assert elapsed < 0.1
