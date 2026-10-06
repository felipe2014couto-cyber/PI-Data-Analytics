"""Atendido (%) per UM: exact numeric RECORDED samples and historical bounds.

No materialization, filter-result cache, PI requests, or CEP calculations.
"""
from bisect import bisect_right
from datetime import datetime, timezone
import json
import math
from sqlalchemy import text
from app.core.exceptions import ValidationError
from app.models import PiTag, PiTagDataType, Section
from app.models.postgres import PiSample, PiIngestionCoverage
from app.schemas.production_unit import ProductionUnitAnalysisResponse, ProductionUnitSegment, ProductionUnitVariable
from app.services.production_unit_service import ProductionUnitService, _build_segments, MAX_PERIOD_DAYS, MAX_UM_SEGMENTS, MAX_FILTER_STATE_EVENTS
from app.services.production_unit_filters import build_filter_state_intervals, merge_coverage


def reliable_intervals(events, coverage, start, end):
    """Do not allow a seed to cross an uncovered historical gap."""
    usable = []
    for event in events:
        state_start = max(start, event['ts'])
        if any(left <= event['ts'] <= state_start < right for left, right in coverage.get(event['tag_id'], [])):
            usable.append(event)
        else:
            # Retain invalid transitions as barriers; dropping a bad transition
            # would extend the previous valid state across it.
            usable.append(dict(event, good=False))
    return build_filter_state_intervals(usable, coverage, start, end)


class StateLookup:
    def __init__(self, intervals):
        self.rows = sorted(intervals, key=lambda row: row['start_ts'])
        self.starts = [datetime.fromisoformat(row['start_ts']) for row in self.rows]

    def at(self, timestamp):
        index = bisect_right(self.starts, timestamp) - 1
        if index < 0:
            return None
        row = self.rows[index]
        return row if timestamp < datetime.fromisoformat(row['end_ts']) else None


def build_limit_state_intervals(events, coverage, start, end):
    """Hold each recorded Good numeric limit until a transition or coverage gap.

    Events before the query are seeds, not query-time measurements. Invalid
    events remain transition boundaries, so a prior Good value cannot resume
    after Bad/Timeout or after an uncovered interval without a new Good event.
    """
    by_tag = {}
    for event in events:
        by_tag.setdefault(event['tag_id'], []).append(event)
    intervals = []
    for tag_id, tag_events in by_tag.items():
        ordered = sorted(tag_events, key=lambda event: event['ts'])
        for index, event in enumerate(ordered):
            value = event['value_double']
            if (not event['good'] or event['questionable'] or event['substituted']
                    or isinstance(value, bool) or not isinstance(value, (int, float))
                    or not math.isfinite(value)):
                continue
            left = max(start, event['ts'])
            coverage_end = next((right for covered_start, right in coverage.get(tag_id, [])
                                 if covered_start <= event['ts'] <= left < right), None)
            if coverage_end is None:
                continue
            next_event = ordered[index + 1]['ts'] if index + 1 < len(ordered) else end
            right = min(end, next_event, coverage_end)
            if left < right:
                intervals.append(dict(tag_id=tag_id, start_ts=left.isoformat(),
                                      end_ts=right.isoformat(), value_double=value,
                                      value_text=None, value_boolean=None))
    return intervals


class HistoricalLimitLookup(StateLookup):
    def __init__(self, intervals):
        # ISO strings with different UTC offsets do not sort chronologically.
        self.rows = sorted(intervals, key=lambda row: datetime.fromisoformat(row['start_ts']))
        self.starts = [datetime.fromisoformat(row['start_ts']) for row in self.rows]


def classify_sample(value, lower, upper):
    """None means ineligible; both endpoints are inclusive."""
    if any(isinstance(item, bool) or not isinstance(item, (int, float)) or not math.isfinite(item) for item in (value, lower, upper)) or lower > upper:
        return None
    return lower <= value <= upper


def eligible_recorded_sample(row):
    """Defensive validation in addition to the RECORDED SQL predicates."""
    return (row['source_mode'] == 'RECORDED' and row['good']
            and not row['questionable'] and not row['substituted']
            and row['value_type'] in {'double', 'float', 'int'}
            and isinstance(row['value_double'], (int, float))
            and not isinstance(row['value_double'], bool) and math.isfinite(row['value_double']))


class ProductionUnitOocService:
    def __init__(self, db):
        self.db = db
        self.units = ProductionUnitService(db)

    def _states(self, ids, start, end, limit_ids=()):
        events = []
        fields = ('tag_id','ts','value_text','value_double','value_boolean','good','questionable','substituted')
        for tag_id in sorted(ids):
            seed = self.db.query(PiSample).filter(PiSample.tag_id == tag_id, PiSample.source_mode == 'RECORDED', PiSample.ts < start).order_by(PiSample.ts.desc()).first()
            if seed is not None:
                events.append({key:getattr(seed,key) for key in fields})
        rows = self.db.query(PiSample).filter(PiSample.tag_id.in_(ids), PiSample.source_mode == 'RECORDED', PiSample.ts >= start, PiSample.ts <= end).order_by(PiSample.ts).limit(MAX_FILTER_STATE_EVENTS + 1).all()
        if len(rows) > MAX_FILTER_STATE_EVENTS:
            raise ValidationError('Reduza a janela: excesso de eventos históricos de contexto para a métrica OOC da Base Unidade.')
        events.extend({key:getattr(row,key) for key in fields} for row in rows)
        coverage_rows = self.db.query(PiIngestionCoverage).filter(PiIngestionCoverage.tag_id.in_(ids), PiIngestionCoverage.mode == 'RECORDED', PiIngestionCoverage.interval_seconds.is_(None), PiIngestionCoverage.status.in_(['COMPLETE','EMPTY_CONFIRMED']), PiIngestionCoverage.range_start < end).all()
        utc = lambda value: value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value
        for event in events:
            event["ts"] = utc(event["ts"])
        coverage = merge_coverage([{ "tag_id": row.tag_id, "range_start": utc(row.range_start), "range_end": utc(row.range_end) } for row in coverage_rows], ids)
        intervals = reliable_intervals(
            [event for event in events if event['tag_id'] not in limit_ids], coverage, start, end,
        )
        intervals.extend(build_limit_state_intervals(
            [event for event in events if event['tag_id'] in limit_ids], coverage, start, end,
        ))
        return events, intervals

    def _limit(self, source, name):
        # Same historical tag-name contract used by PiNormLimitsService; no
        # current PI value or static visual limit is involved.
        if not name or not name.strip():
            return None
        # Configured limit dependencies are deliberately inactive so ordinary
        # ingestion does not schedule them. The explicit materializer stores
        # them in pi_tags/pi_samples; OOC may still read those dependencies.
        matches = self.db.query(PiTag).filter(PiTag.pi_tag_name == name.strip(), PiTag.pi_server == source.pi_server, PiTag.data_type == PiTagDataType.NUMERIC).all()
        if len(matches) > 1:
            raise ValidationError(f'Configuração ambígua do limite histórico {name}.')
        return matches[0].id if matches else None

    def analyze(self, request):
        start, end = request.start_time, request.end_time
        if start.tzinfo is None or end.tzinfo is None or not start < end or (end-start).total_seconds() > MAX_PERIOD_DAYS * 86400:
            raise ValidationError('Informe um período válido de até 31 dias com timezone explícito.')
        section = self.db.get(Section, request.section_id) if request.section_id is not None else None
        equipment_id = section.equipment_id if section is not None else request.equipment_id
        if equipment_id is None or (section is not None and request.equipment_id is not None and equipment_id != request.equipment_id):
            raise ValidationError('Informe um equipamento e uma seção compatíveis.')
        um = self.units.resolve_um_tag(equipment_id, request.section_id)
        selected = self.db.query(PiTag).filter(PiTag.id.in_(request.tag_ids), PiTag.equipment_id == equipment_id, PiTag.active.is_(True)).all()
        if {tag.id for tag in selected} != set(request.tag_ids):
            raise ValidationError('Tags selecionadas ausentes, inativas ou de outro equipamento.')
        tags = [tag for tag in selected if tag.id != um.id and tag.data_type == PiTagDataType.NUMERIC]
        if not tags:
            raise ValidationError('a métrica OOC da Base Unidade exige ao menos uma variável numérica.')
        rules, dynamic, filter_ids = self.units._resolve_filter_plan(section, tags, request.filter_configuration, request.analysis_filters, equipment_id=equipment_id)
        if len(tags) == 1:
            filter_ids.discard(tags[0].id)
        limits = {tag.id:(self._limit(tag,tag.lower_limit_tag), self._limit(tag,tag.upper_limit_tag)) for tag in tags}
        limit_ids = {limit for pair in limits.values() for limit in pair if limit is not None}
        state_ids = {um.id} | filter_ids | limit_ids
        events, intervals = self._states(state_ids, start, end, limit_ids)
        segments = _build_segments([row for row in events if row['tag_id'] == um.id], start, end)
        from app.services.production_unit_service import _um_value_matches
        um_rules = [rule for rule, target in rules if target == um.id and rule.kind in {'numeric','text'}]
        segments = [segment for segment in segments if all(_um_value_matches(rule,segment.value) for rule in um_rules)]
        if len(segments) > MAX_UM_SEGMENTS:
            raise ValidationError('Reduza a janela: excesso de segmentos de UM.')
        lookups = {
            tag_id: (HistoricalLimitLookup if tag_id in limit_ids else StateLookup)(
                [row for row in intervals if row['tag_id'] == tag_id])
            for tag_id in state_ids
        }
        counts = {(index,tag.id):[0,0] for index in range(len(segments)) for tag in tags}
        starts = [segment.start for segment in segments]
        aliases = {tag_id:f'fs{index}' for index,tag_id in enumerate(sorted(filter_ids))}
        filter_sql, params = self.units._compile_filters(section,tags,aliases,rules,dynamic,request.filter_configuration)
        joins = ' '.join(f'LEFT JOIN states {alias} ON {alias}.tag_id=:filter_{index} AND p.ts >= {alias}.start_ts AND p.ts < {alias}.end_ts' for index,(tag_id,alias) in enumerate(sorted(aliases.items())))
        params.update({f'filter_{index}':tag_id for index,tag_id in enumerate(sorted(aliases))})
        tag_json = json.dumps([{'tag_id':tag.id} for tag in tags])
        # Stream exact raw events; all existing sample predicates remain SQL
        # predicates. The frontend receives only counters and percentages.
        rows = self.db.execute(text(f'''
            WITH tags AS (SELECT * FROM jsonb_to_recordset(CAST(:tags AS jsonb)) AS x(tag_id integer)),
            states AS (SELECT * FROM jsonb_to_recordset(CAST(:states AS jsonb)) AS x(tag_id integer,start_ts timestamptz,end_ts timestamptz,value_double double precision,value_text text,value_boolean boolean))
            SELECT p.tag_id,p.ts,p.value_double,p.source_mode,p.value_type,p.good,p.questionable,p.substituted FROM tags t JOIN pi_samples_timescale p ON p.tag_id=t.tag_id
            {joins}
            WHERE p.source_mode='RECORDED' AND p.ts >= :start AND p.ts < :end
              AND p.good AND NOT p.questionable AND NOT p.substituted
              AND p.value_type IN ('double','float','int') AND p.value_double IS NOT NULL AND ({filter_sql})
            ORDER BY p.ts,p.tag_id
        '''), dict(params,tags=tag_json,states=json.dumps(intervals),start=start,end=end), execution_options={'stream_results':True}).mappings()
        for row in rows:
            if not eligible_recorded_sample(row):
                continue
            index = bisect_right(starts,row['ts']) - 1
            if index < 0 or row['ts'] >= segments[index].end or segments[index].status != 'ASSIGNED' or lookups[um.id].at(row['ts']) is None:
                continue
            lower_id, upper_id = limits[row['tag_id']]
            lower = lookups[lower_id].at(row['ts']) if lower_id is not None else None
            upper = lookups[upper_id].at(row['ts']) if upper_id is not None else None
            inside = classify_sample(row['value_double'], lower['value_double'] if lower else None, upper['value_double'] if upper else None)
            if inside is None:
                continue
            count = counts[index,row['tag_id']]
            count[0] += 1
            count[1] += int(inside)
        return ProductionUnitAnalysisResponse(strategy="production_unit_ooc_recorded_runtime",equipment_id=equipment_id,section_id=request.section_id,um_tag_id=um.id,um_tag_name=um.pi_tag_name,start_time=start,end_time=end,segments=[
            ProductionUnitSegment(segment_id=f"{um.id}:{segment.start.isoformat()}", status=segment.status, start_reason=segment.start_reason, end_reason=segment.end_reason, state_source_timestamp=segment.state_source_timestamp, duration_seconds=(segment.end-segment.start).total_seconds(), start_time=segment.start,end_time=segment.end,um_value=segment.value,variables=[
                ProductionUnitVariable(data_type="NUMERIC", unit=tag.engineering_unit, sample_count=counts[index,tag.id][0], excluded_quality_count=0, tag_id=tag.id,tag_name=tag.pi_tag_name,display_name=tag.display_name,eligible_sample_count=counts[index,tag.id][0],attended_sample_count=counts[index,tag.id][1],attended_percent=100*counts[index,tag.id][1]/counts[index,tag.id][0] if counts[index,tag.id][0] else None)
                for tag in tags]) for index,segment in enumerate(segments)])
