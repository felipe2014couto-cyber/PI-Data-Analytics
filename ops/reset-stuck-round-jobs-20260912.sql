-- Run manually only after migration 20260919 and the new worker code are deployed.
-- The transaction aborts unless all ten reviewed R1/R3 jobs are still eligible.
BEGIN;

CREATE TEMP TABLE expected_backfill_jobs (id integer PRIMARY KEY, round_name varchar(8));
INSERT INTO expected_backfill_jobs (id, round_name) VALUES
    (3124, 'R1'), (3242, 'R1'), (3269, 'R1'), (3270, 'R1'),
    (5495, 'R3'), (5496, 'R3'), (5497, 'R3'), (5498, 'R3'),
    (6581, 'R3'), (6582, 'R3');

DO $$
BEGIN
    IF (
        SELECT count(*)
        FROM pi_backfill_jobs job
        JOIN expected_backfill_jobs expected
          ON expected.id = job.id AND expected.round_name = job.round_name
        WHERE job.status = 'RUNNING'
          AND job.lease_expires_at IS NULL
    ) <> 10 THEN
        RAISE EXCEPTION 'Precondition failed: expected all 10 reviewed legacy RUNNING jobs';
    END IF;
END $$;

CREATE TEMP TABLE reset_backfill_jobs AS
WITH reset AS (
    UPDATE pi_backfill_jobs job
       SET status = 'PENDING',
           stage = 'PENDING',
           next_start = COALESCE(job.checkpoint_start, job.next_start, job.target_start),
           error_message = NULL,
           last_error_at = NULL,
           lease_owner = NULL,
           lease_expires_at = NULL,
           heartbeat_at = NULL,
           next_attempt_at = NULL,
           updated_at = now()
      FROM expected_backfill_jobs expected
     WHERE job.id = expected.id
       AND job.round_name = expected.round_name
       AND job.status = 'RUNNING'
       AND job.lease_expires_at IS NULL
    RETURNING job.id, job.round_name, job.status, job.next_start, job.checkpoint_start
)
SELECT * FROM reset;

DO $$
BEGIN
    IF (SELECT count(*) FROM reset_backfill_jobs) <> 10 THEN
        RAISE EXCEPTION 'Reset failed: updated % jobs instead of 10',
            (SELECT count(*) FROM reset_backfill_jobs);
    END IF;
END $$;

TABLE reset_backfill_jobs;
COMMIT;
