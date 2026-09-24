"""CEP data provider backed exclusively by the TimescaleDB hypertable."""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from numbers import Real

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

    @staticmethod
    def _interpolate(timestamp: datetime, previous, following) -> PiValue | None:
        if previous is None and following is None:
            return None
        if previous is None:
            return None  # No value is known at the requested instant.
        previous_ts = previous["ts"]
        if previous_ts.tzinfo is None:
            previous_ts = previous_ts.replace(tzinfo=UTC)
        previous_value = TimescaleCepProvider._row_value(previous)
        if following is None or previous_ts == timestamp:
            return PiValue(timestamp=timestamp, value=previous_value,
                           good=bool(previous["good"]), questionable=bool(previous["questionable"]),
                           substituted=bool(previous["substituted"]))
        following_ts = following["ts"]
        if following_ts.tzinfo is None:
            following_ts = following_ts.replace(tzinfo=UTC)
        following_value = TimescaleCepProvider._row_value(following)
        if (isinstance(previous_value, Real) and not isinstance(previous_value, bool)
                and isinstance(following_value, Real) and not isinstance(following_value, bool)
                and following_ts > previous_ts):
            fraction = (timestamp - previous_ts).total_seconds() / (following_ts - previous_ts).total_seconds()
            value = float(previous_value) + (float(following_value) - float(previous_value)) * fraction
        else:
            value = previous_value
        return PiValue(timestamp=timestamp, value=value,
                       good=bool(previous["good"] and following["good"]),
                       questionable=bool(previous["questionable"] or following["questionable"]),
                       substituted=bool(previous["substituted"] or following["substituted"]))

    @staticmethod
    def _row_value(row) -> object:
        return (row["value_double"] if row["value_type"] in {"double", "float", "int"}
                else row["value_boolean"] if row["value_type"] == "boolean" else row["value_text"])

    def _interpolated_from_recorded(self, tag_id: int, start: datetime, end: datetime,
                                    seconds: int, max_count: int | None) -> list[PiValue]:
        session_context = self.session_factory() if self.session_factory is not None else None
        session = session_context or self.db
        try:
            if session.bind.dialect.name == "postgresql":
                # Indexed nearest-neighbour lookups avoid loading millions of raw
                # events into Python for a multi-day CEP analysis.
                query = text("""
                    SELECT tick.ts AS requested_ts,
                           p.ts AS p_ts, p.value_type AS p_type, p.value_double AS p_double,
                           p.value_boolean AS p_boolean, p.value_text AS p_text,
                           p.good AS p_good, p.questionable AS p_questionable, p.substituted AS p_substituted,
                           n.ts AS n_ts, n.value_type AS n_type, n.value_double AS n_double,
                           n.value_boolean AS n_boolean, n.value_text AS n_text,
                           n.good AS n_good, n.questionable AS n_questionable, n.substituted AS n_substituted
                    FROM generate_series(:start, :end - (:seconds * interval '1 second'),
                                         :seconds * interval '1 second') AS tick(ts)
                    LEFT JOIN LATERAL (
                        SELECT ts, value_type, value_double, value_boolean, value_text,
                               good, questionable, substituted
                        FROM pi_samples_timescale
                        WHERE tag_id = :tag_id AND source_mode = 'RECORDED' AND ts <= tick.ts
                        ORDER BY ts DESC LIMIT 1
                    ) p ON true
                    LEFT JOIN LATERAL (
                        SELECT ts, value_type, value_double, value_boolean, value_text,
                               good, questionable, substituted
                        FROM pi_samples_timescale
                        WHERE tag_id = :tag_id AND source_mode = 'RECORDED' AND ts >= tick.ts
                        ORDER BY ts ASC LIMIT 1
                    ) n ON true
                    ORDER BY tick.ts
                    LIMIT :limit
                """)
                rows = session.execute(query, {
                    "tag_id": tag_id, "start": start, "end": end,
                    "seconds": seconds, "limit": max_count or 1000000,
                }).mappings().all()
                values = []
                for row in rows:
                    previous = ({"ts": row["p_ts"], "value_type": row["p_type"],
                                 "value_double": row["p_double"], "value_boolean": row["p_boolean"],
                                 "value_text": row["p_text"], "good": row["p_good"],
                                 "questionable": row["p_questionable"], "substituted": row["p_substituted"]}
                                if row["p_ts"] is not None else None)
                    following = ({"ts": row["n_ts"], "value_type": row["n_type"],
                                  "value_double": row["n_double"], "value_boolean": row["n_boolean"],
                                  "value_text": row["n_text"], "good": row["n_good"],
                                  "questionable": row["n_questionable"], "substituted": row["n_substituted"]}
                                 if row["n_ts"] is not None else None)
                    value = self._interpolate(row["requested_ts"], previous, following)
                    if value is not None:
                        values.append(value)
                return values

            # SQLite is used by tests; keep the same interpolation semantics.
            rows = session.execute(text("""
                SELECT ts, value_type, value_double, value_boolean, value_text,
                       good, questionable, substituted
                FROM pi_samples_timescale
                WHERE tag_id = :tag_id AND source_mode = 'RECORDED'
                ORDER BY ts
            """), {"tag_id": tag_id}).mappings().all()
            normalized_rows = [
                {**row, "ts": datetime.fromisoformat(row["ts"]) if isinstance(row["ts"], str) else row["ts"]}
                for row in rows
            ]
            for row in normalized_rows:
                if row["ts"].tzinfo is None:
                    row["ts"] = row["ts"].replace(tzinfo=UTC)
            values = []
            tick = start
            step = timedelta(seconds=seconds)
            while tick < end and (max_count is None or len(values) < max_count):
                previous = next((row for row in reversed(normalized_rows) if row["ts"] <= tick), None)
                following = next((row for row in normalized_rows if row["ts"] >= tick), None)
                value = self._interpolate(tick, previous, following)
                if value is not None:
                    values.append(value)
                tick += step
            return values
        finally:
            if session_context is not None:
                session_context.close()

    async def get_interpolated_values(self, web_id: str, start_time: datetime, end_time: datetime, interval: str, max_count: int | None = None) -> PiInterpolatedValues:
        seconds = int(interval[:-1]) * {"s": 1, "m": 60, "h": 3600}[interval[-1]]
        tag_id = self._by_web_id.get(web_id)
        if tag_id is None:
            return PiInterpolatedValues(web_id=web_id, values=[])
        if self.session_factory is not None:
            values = await asyncio.to_thread(
                self._interpolated_from_recorded, tag_id,
                start_time.astimezone(UTC), end_time.astimezone(UTC), seconds, max_count,
            )
        else:
            values = self._interpolated_from_recorded(
                tag_id, start_time.astimezone(UTC), end_time.astimezone(UTC), seconds, max_count,
            )
        return PiInterpolatedValues(web_id=web_id, values=values)
