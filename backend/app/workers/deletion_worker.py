"""Durable asynchronous deletion of samples from the canonical hypertable."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from sqlalchemy import select, text

from app.database.session import SessionLocal
from app.models.pi_tag import PiTag
from app.models.postgres import PiTagDeletionJob

logger = logging.getLogger("workers.deletion")


def _clear_assignments(db, tag_id: int) -> None:
    from app.models.section import Section
    db.query(Section).filter((Section.width_tag_id == tag_id) | (Section.um_tag_id == tag_id)).update({Section.width_tag_id: None, Section.um_tag_id: None}, synchronize_session=False)


async def run_deletion_loop(*, once: bool = False) -> None:
    while True:
        try:
            with SessionLocal() as db:
                jobs = db.execute(select(PiTagDeletionJob).where(PiTagDeletionJob.status.in_(["PENDING", "RUNNING"])).order_by(PiTagDeletionJob.id).limit(10)).scalars().all()
                for job in jobs:
                    job.status = "RUNNING"
                    job.attempts = (job.attempts or 0) + 1
                    db.commit()
                    try:
                        deleted = db.execute(text(
                            """
                            DELETE FROM pi_samples_timescale
                            WHERE tag_id = :tag_id
                              AND ts IN (
                                SELECT ts FROM pi_samples_timescale
                                WHERE tag_id = :tag_id ORDER BY ts LIMIT 5000
                              )
                            """
                        ), {"tag_id": job.tag_id}).rowcount
                        if deleted:
                            job.progress = min(0.99, (job.progress or 0.0) + 0.1)
                        else:
                            tag = db.get(PiTag, job.tag_id)
                            if tag is not None:
                                _clear_assignments(db, tag.id)
                                db.delete(tag)
                            job.status = "COMPLETED"
                            job.progress = 1.0
                        job.updated_at = datetime.now(timezone.utc)
                        job.last_error = None
                        db.commit()
                    except Exception as exc:
                        db.rollback()
                        job = db.get(PiTagDeletionJob, job.id)
                        if job:
                            job.status = "FAILED"
                            job.last_error = str(exc)[:2000]
                            job.updated_at = datetime.now(timezone.utc)
                            db.commit()
                        logger.exception("deletion_job_failed job_id=%s", job.id if job else None)
        except Exception:
            if once:
                raise
            logger.exception("deletion_cycle_failed")
        if once:
            return
        await asyncio.sleep(10)
