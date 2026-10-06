"""Routes tolerate deployed PI tables that predate unused sampling_mode fields."""

from datetime import datetime, timedelta, timezone

from sqlalchemy import inspect

from app.models.postgres import PiIngestionState, PiSample
from app.services.coverage_service import CoverageService
from tests.test_norm_limit_reload_service import _source


def test_catalog_endpoints_work_when_pi_tags_has_no_sampling_mode(client, db_session):
    source = _source(db_session, "LEGACY-PI-TAG-SCHEMA")
    end = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    start = end - timedelta(minutes=10)
    db_session.add(PiSample(
        tag_id=source.id,
        ts=start + timedelta(minutes=1),
        source_mode="RECORDED",
        value_type="double",
        value_double=42,
    ))
    db_session.add(PiIngestionState(
        tag_id=source.id,
        source_mode="RECORDED",
        last_source_ts=end,
        watermark_ts=end,
        last_success_at=end,
    ))
    CoverageService.record_coverage(db_session, source.id, start, end, "RECORDED")
    db_session.commit()

    # Simulate the deployed schemas in the isolated SQLite test DB. Add first
    # so this test catches ORM regressions that reintroduce unmigrated fields.
    bind = db_session.get_bind()
    with bind.begin() as connection:
        for table in ("pi_tags", "pi_ingestion_state"):
            columns = {column["name"] for column in inspect(connection).get_columns(table)}
            if "sampling_mode" not in columns:
                connection.exec_driver_sql(
                    f"ALTER TABLE {table} ADD COLUMN sampling_mode VARCHAR(32) "
                    "DEFAULT 'RECORDED'"
                )
            connection.exec_driver_sql(f"ALTER TABLE {table} DROP COLUMN sampling_mode")

    sections = client.get("/api/sections")
    tags = client.get("/api/pi-tags")
    assert sections.status_code == 200, sections.text
    assert tags.status_code == 200, tags.text
    assert any(section["code"] == "S-LEGACY-PI-TAG-SCHEMA" for section in sections.json()["items"])
    assert any(tag["pi_tag_name"] == "LEGACY-PI-TAG-SCHEMA" for tag in tags.json()["items"])

    chart = client.get("/api/time-series", params={
        "tag_ids": source.id,
        "start_time": start.isoformat(),
        "end_time": end.isoformat(),
        "mode": "recorded",
        "relative_period": "true",
    })
    assert chart.status_code == 200, chart.text
    assert chart.json()["query_execution"]["source"] == "timescaledb"
    assert [point["value"] for point in chart.json()["series"][0]["points"]] == [42]
