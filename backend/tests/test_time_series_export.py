"""Tests for CSV export endpoint."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.integrations.pi.provider import PiPoint
from app.models.pi_tag import PiTag
from app.schemas.pi import TimeSeries
from app.services.pi_long_range_service import _format_csv_row, _remove_boundary_duplicates
from tests.pi_fakes import make_value
from tests.test_pi_time_series import _configure_pi, _make_tag


def test_csv_format_row():
    from app.models.pi_tag import PiTag

    tag = PiTag(
        id=1,
        pi_tag_name="TAG",
        display_name="Display",
        engineering_unit="C",
        pi_server="PIMS",
        active=True,
    )
    v = make_value("2026-07-01T00:00:00Z", 25.5, good=True)
    row = _format_csv_row(tag, v)
    assert "1;TAG;Display" in row
    assert "25.5" in row
    assert ";number;" in row
    assert "true;false;false" in row
    assert "C" in row


def test_csv_format_string_value():
    from app.models.pi_tag import PiTag

    tag = PiTag(
        id=2,
        pi_tag_name="TAG2",
        display_name="Display2",
        engineering_unit=None,
        pi_server="PIMS",
        active=True,
    )
    v = make_value("2026-07-01T00:00:00Z", "RUN", good=True)
    row = _format_csv_row(tag, v)
    assert '"RUN"' in row
    assert ";string;" in row


def test_csv_format_boolean_value():
    from app.models.pi_tag import PiTag

    tag = PiTag(
        id=3,
        pi_tag_name="TAG3",
        display_name="Display3",
        engineering_unit=None,
        pi_server="PIMS",
        active=True,
    )
    v = make_value("2026-07-01T00:00:00Z", True, good=True)
    row = _format_csv_row(tag, v)
    assert "true" in row
    assert ";boolean;" in row


def test_csv_format_null_value():
    from app.models.pi_tag import PiTag

    tag = PiTag(
        id=4,
        pi_tag_name="TAG4",
        display_name="Display4",
        engineering_unit=None,
        pi_server="PIMS",
        active=True,
    )
    v = make_value("2026-07-01T00:00:00Z", None, good=False)
    row = _format_csv_row(tag, v)
    parts = row.split(";")
    assert parts[4] == ""
    assert parts[5] == "null"
