"""Explicit bounded rebuild / independent incremental derived-data worker.

Examples (run from backend):
 python -m app.commands.production_units rebuild --equipment 2 --tags 20 23 --start 2026-10-01T21:32:12Z --end 2026-10-02T21:32:12Z
 python -m app.commands.production_units refresh --materialization 1
 python -m app.commands.production_units refresh --materialization 1 --watch

Watch only follows explicitly registered periods; it never discovers or
backfills years. Each transaction is separate from RECORDED ingestion.
"""
import argparse
import json
import time
from datetime import datetime
import app.models  # noqa: F401
from sqlalchemy import text
from app.database.session import SessionLocal
from app.services.production_unit_store import ProductionUnitStore


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    rebuild = commands.add_parser("rebuild")
    rebuild.add_argument("--equipment", type=int, required=True)
    rebuild.add_argument("--section", type=int)
    rebuild.add_argument("--tags", type=int, nargs="+", required=True)
    rebuild.add_argument("--start", type=datetime.fromisoformat, required=True)
    rebuild.add_argument("--end", type=datetime.fromisoformat, required=True)
    refresh = commands.add_parser("refresh")
    refresh.add_argument("--materialization", type=int, required=True)
    refresh.add_argument("--watch", action="store_true")
    refresh.add_argument("--interval", type=float, default=10)
    args = parser.parse_args()
    if args.command == "refresh" and args.interval < 1:
        parser.error("--interval deve ser pelo menos 1 segundo")
    while True:
        with SessionLocal() as db:
            if db.get_bind().dialect.name == "postgresql":
                db.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ"))
            store = ProductionUnitStore(db)
            started = time.perf_counter()
            if args.command == "rebuild":
                result = store.rebuild(args.equipment, args.section, args.tags, args.start, args.end)
                output = {"segments": len(result.segments)}
            else:
                output = store.refresh(args.materialization)
            db.commit()
            print(json.dumps(output | {"duration_ms": round((time.perf_counter() - started) * 1000, 2)}), flush=True)
        if args.command != "refresh" or not args.watch:
            break
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
