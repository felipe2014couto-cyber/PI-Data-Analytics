"""Historical responses negotiate lossless compression without changing points."""
import gzip
import json

import pytest
from fastapi import FastAPI, APIRouter
from fastapi.testclient import TestClient

from app.api.time_series import HistoricalQueryRoute


@pytest.mark.parametrize("encoding,compressed", [
    ("gzip, deflate, br", True), ("GZip", True), ("identity", False),
    ("gzip;q=0, *;q=1", False), ("gzip;q=0.5", True), ("*", True),
    ("gzip;q=invalid", False),
])
def test_historical_compression_preserves_every_timestamp_and_value(encoding, compressed):
    app = FastAPI()
    router = APIRouter(route_class=HistoricalQueryRoute)
    points = [{"timestamp": f"2026-09-10T15:{i // 60:02}:{i % 60:02}Z", "value": i / 7} for i in range(200)]

    @router.get("/time-series")
    async def get_time_series():
        return {"series": [{"tag_id": 20, "points": points}]}

    app.include_router(router)
    with TestClient(app) as client:
        with client.stream("GET", "/time-series", headers={"Accept-Encoding": encoding}) as response:
            wire = b"".join(response.iter_raw())
            assert response.status_code == 200
            assert (response.headers.get("content-encoding") == "gzip") is compressed
            assert int(response.headers["content-length"]) == len(wire)
            assert "Accept-Encoding" in response.headers["vary"]
            assert "api;dur=" in response.headers["server-timing"]
            decoded = gzip.decompress(wire) if compressed else wire
            assert json.loads(decoded)["series"][0]["points"] == points
            if compressed:
                assert len(wire) < len(decoded) / 2


def test_compression_does_not_apply_to_other_routes():
    app = FastAPI()
    router = APIRouter(route_class=HistoricalQueryRoute)

    @router.get("/export")
    async def export_time_series_csv():
        return "x" * 4000

    app.include_router(router)
    with TestClient(app) as client:
        response = client.get("/export", headers={"Accept-Encoding": "gzip"})
    assert "content-encoding" not in response.headers
    assert "server-timing" not in response.headers
