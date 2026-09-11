"""CEP data provider backed exclusively by the TimescaleDB hypertable."""
from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.integrations.pi.provider import (
    PiDataProvider,
    PiInterpolatedValues,
    PiPoint,
    PiRecordedValues,
    PiValue,
)
from app.schemas.cep_analysis import MaterializedTag


class TimescaleCepProvider(PiDataProvider):
    """Adapt persisted PI samples to the CEP provider contract.

    ``resolve_point`` only resolves the local catalog; it never contacts PI.
    """

    def __init__(self, db: Session, tags: list[MaterializedTag], session_factory=None) -> None:
        self.db = db
        self.session_factory = session_factory
        self._by_path: dict[str, int] = {}
        self._by_web_id: dict[str, int] = {}
        for item in tags:
            row = db.execute(
                text("SELECT id, pi_web_id FROM pi_tags WHERE pi_server = :server AND pi_tag_name = :name"),
                {"server": item.pi_server, "name": item.pi_tag_name},
            ).mappings().first()
            if row is None:
                continue
            self._by_path[f"\\\\{item.pi_server}\\{item.pi_tag_name}"] = int(row["id"])
            if row["pi_web_id"]:
                self._by_web_id[str(row["pi_web_id"])] = int(row["id"])
            self._by_web_id[f"db:{int(row['id'])}"] = int(row["id"])

    async def ping(self) -> None:
        return None

    async def resolve_point(self, path: str) -> PiPoint | None:
        tag_id = self._by_path.get(path)
        if tag_id is None:
            return None
        return PiPoint(web_id=f"db:{tag_id}", name=path.rsplit("\\", 1)[-1])

    def _values(self, web_id: str, start: datetime, end: datetime, mode: str, max_count: int | None) -> list[PiValue]:
        if start > end:
            start, end = end, start
        tag_id = self._by_web_id.get(web_id)
        if tag_id is None:
            return []
        query = """
            SELECT ts, value_double, value_boolean, value_text, value_type,
                   good, questionable, substituted
            FROM pi_samples_timescale
            WHERE tag_id = :tag_id AND source_mode = :mode
              AND ts >= :start AND ts < :end
            ORDER BY ts ASC
        """
        params = {"tag_id": tag_id, "mode": mode, "start": start.astimezone(UTC), "end": end.astimezone(UTC)}
        if max_count is not None:
            query += " LIMIT :max_count"
            params["max_count"] = max_count
        if self.session_factory is not None:
            with self.session_factory() as session:
                rows = session.execute(text(query), params).mappings().all()
        else:
            rows = self.db.execute(text(query), params).mappings().all()
        values: list[PiValue] = []
        for row in rows:
            value = row["value_double"] if row["value_type"] in {"double", "float", "int"} else row["value_boolean"] if row["value_type"] == "boolean" else row["value_text"]
            ts = row["ts"]
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=UTC)
            values.append(PiValue(timestamp=ts, value=value, good=bool(row["good"]), questionable=bool(row["questionable"]), substituted=bool(row["substituted"])))
        return values

    async def get_recorded_values(self, web_id: str, start_time: datetime, end_time: datetime, max_count: int | None = None) -> PiRecordedValues:
        return PiRecordedValues(web_id=web_id, values=self._values(web_id, start_time, end_time, "RECORDED", max_count))

    async def get_interpolated_values(self, web_id: str, start_time: datetime, end_time: datetime, interval: str, max_count: int | None = None) -> PiInterpolatedValues:
        seconds = int(interval[:-1]) * {"s": 1, "m": 60, "h": 3600}[interval[-1]]
        return PiInterpolatedValues(web_id=web_id, values=self._values(web_id, start_time, end_time, f"INTERPOLATED_{seconds}S", max_count))
