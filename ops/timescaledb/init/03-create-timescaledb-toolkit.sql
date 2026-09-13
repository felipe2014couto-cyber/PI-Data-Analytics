-- Plot-style continuous aggregates use first()/last() hyperfunctions.
-- The init directory runs as the database administrator on a fresh volume;
-- this keeps the application role free of extension-creation privileges.
CREATE EXTENSION IF NOT EXISTS timescaledb_toolkit;

SELECT extname, extversion
FROM pg_extension
WHERE extname = 'timescaledb_toolkit';
