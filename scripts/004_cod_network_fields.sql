-- Manual migration when Alembic is unavailable (run once on production DB)
ALTER TABLE orders ADD COLUMN IF NOT EXISTS cod_network_sent_at TIMESTAMPTZ;
ALTER TABLE orders ADD COLUMN IF NOT EXISTS cod_network_response JSONB;
ALTER TABLE orders ADD COLUMN IF NOT EXISTS cod_network_reference_id VARCHAR(255);

-- After running SQL, set alembic version if needed:
-- DELETE FROM alembic_version;
-- INSERT INTO alembic_version (version_num) VALUES ('004');
