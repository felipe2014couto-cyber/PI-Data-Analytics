"""Read-only, same-session comparison of runtime and persisted UM queries."""
import argparse
from datetime import datetime
import json
import math
import statistics
import time
import app.models  # noqa: F401
from sqlalchemy import event, text
from app.database.session import SessionLocal
from app.schemas.production_unit import ProductionUnitFilterConfiguration, ProductionUnitFilterRule
from app.services.production_unit_service import ProductionUnitService


def equal(a, b):
    if isinstance(a, dict):
        return a.keys() == b.keys() and all(equal(a[k], b[k]) for k in a)
    if isinstance(a, list):
        return len(a) == len(b) and all(equal(x,y) for x,y in zip(a,b))
    if isinstance(a, float) and isinstance(b, float):
        return math.isclose(a,b,rel_tol=1e-12,abs_tol=1e-12)
    return a == b


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--equipment', type=int, required=True)
    parser.add_argument('--section', type=int)
    parser.add_argument('--tags', type=int, nargs='+', required=True)
    parser.add_argument('--start', type=datetime.fromisoformat, required=True)
    parser.add_argument('--end', type=datetime.fromisoformat, required=True)
    parser.add_argument('--runs', type=int, default=5)
    parser.add_argument('--filter-tag', type=int)
    parser.add_argument('--min', type=float)
    parser.add_argument('--max', type=float)
    parser.add_argument('--quality', action='store_true')
    parser.add_argument('--prepare', action='store_true', help='Explicitly rebuild only this bounded period before comparison')
    args = parser.parse_args()
    if args.runs < 1:
        parser.error('--runs deve ser positivo')
    rules = [ProductionUnitFilterRule(id='benchmark-range', kind='numeric', tag_id=args.filter_tag, operator='between', value=args.min, second_value=args.max)] if args.filter_tag else []
    config = ProductionUnitFilterConfiguration(filters_enabled=bool(rules) or args.quality, rules=rules)
    report = {'equipment_id':args.equipment, 'section_id':args.section, 'tag_ids':args.tags, 'start':args.start.isoformat(), 'end':args.end.isoformat(), 'filters':config.model_dump(mode='json')}
    if args.prepare:
        from app.services.production_unit_store import ProductionUnitStore
        with SessionLocal() as prepare_db:
            prepare_db.execute(text('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ'))
            ProductionUnitStore(prepare_db).rebuild(args.equipment, args.section, args.tags, args.start, args.end)
            prepare_db.commit()
    with SessionLocal() as db:
        db.execute(text('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY'))
        counter=[]
        def query_count(*unused): counter.append(1)
        event.listen(db.connection(), 'after_cursor_execute', query_count)
        responses={}
        for label, stored in (('before',False),('after',True)):
            samples=[]; counts=[]
            for unused in range(args.runs):
                counter.clear(); started=time.perf_counter()
                response=ProductionUnitService(db).analyze(args.section,args.tags,args.start,args.end,config,equipment_id=args.equipment,use_store=stored)
                samples.append(round((time.perf_counter()-started)*1000,3));counts.append(len(counter))
            responses[label]=response
            report[label]={'runs_ms':samples,'median_ms':statistics.median(samples),'queries':counts,'segments':len(response.segments),'raw_samples':sum(v.raw_sample_count for s in response.segments for v in s.variables),'runtime_raw_sample_count':response.runtime_raw_sample_count,'strategy':response.strategy,'precomputed_segments':response.precomputed_segments,'runtime_segments':response.runtime_segments}
        report['equal_results']=equal([s.model_dump(mode='json') for s in responses['before'].segments],[s.model_dump(mode='json') for s in responses['after'].segments])
        report['average_tolerance']='floating statistics: relative and absolute 1e-12; counts/bounds/text exact'
        report['results']=[s.model_dump(mode='json') for s in responses['after'].segments]
    print(json.dumps(report,ensure_ascii=False,indent=2))
    if not report['equal_results']:
        raise SystemExit('Resultados diferentes')


if __name__=='__main__':
    main()
