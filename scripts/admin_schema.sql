-- =============================================================================
-- Nasama Shop — Full DB schema + admin-dashboard migration
-- Safe to run multiple times (idempotent). Run with `psql` or any SQL client.
--
--   psql "$DATABASE_URL" -f backend/scripts/admin_schema.sql
--
-- This file is equivalent to alembic upgrade head for revisions 001 + 002.
-- =============================================================================

BEGIN;

-- -----------------------------------------------------------------------------
-- orders
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS orders (
    id              UUID PRIMARY KEY,
    order_number    VARCHAR(32)  NOT NULL,
    customer_name   VARCHAR(255) NOT NULL,
    phone_e164      VARCHAR(20)  NOT NULL,
    phone_national  VARCHAR(15)  NOT NULL,
    status          VARCHAR(50)  NOT NULL DEFAULT 'pending',
    subtotal        NUMERIC(10,2) NOT NULL,
    upsell_total    NUMERIC(10,2) NOT NULL DEFAULT 0,
    total           NUMERIC(10,2) NOT NULL,
    currency        VARCHAR(3)   NOT NULL DEFAULT 'SAR',
    payment_method  VARCHAR(50)  NOT NULL DEFAULT 'COD',
    items           JSONB        NOT NULL,
    upsell_item     JSONB,
    landing_page    VARCHAR(500),
    utm             JSONB,
    click_ids       JSONB,
    cookies         JSONB,
    event_id        VARCHAR(255),
    client_ip       VARCHAR(45),
    user_agent      VARCHAR(1000),
    sheet_sent_at   TIMESTAMPTZ,
    sheet_response  JSONB,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

-- Admin-dashboard columns (migration 002)
ALTER TABLE orders ADD COLUMN IF NOT EXISTS admin_notes   VARCHAR(2000);
ALTER TABLE orders ADD COLUMN IF NOT EXISTS cancel_reason VARCHAR(500);
ALTER TABLE orders ADD COLUMN IF NOT EXISTS confirmed_at  TIMESTAMPTZ;
ALTER TABLE orders ADD COLUMN IF NOT EXISTS shipped_at    TIMESTAMPTZ;
ALTER TABLE orders ADD COLUMN IF NOT EXISTS delivered_at  TIMESTAMPTZ;

-- Constraints + indexes
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'uq_orders_order_number'
    ) THEN
        ALTER TABLE orders ADD CONSTRAINT uq_orders_order_number UNIQUE (order_number);
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS ix_orders_order_number ON orders (order_number);
CREATE INDEX IF NOT EXISTS ix_orders_event_id     ON orders (event_id);
CREATE INDEX IF NOT EXISTS ix_orders_status       ON orders (status);
CREATE INDEX IF NOT EXISTS ix_orders_created_at   ON orders (created_at);

-- -----------------------------------------------------------------------------
-- tracking_events  (first-party analytics, only valid KSA traffic)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS tracking_events (
    id               UUID PRIMARY KEY,
    event_name       VARCHAR(100) NOT NULL,
    event_id         VARCHAR(255),
    order_id         UUID REFERENCES orders(id) ON DELETE SET NULL,
    payload          JSONB NOT NULL,
    provider_results JSONB,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_tracking_events_event_id   ON tracking_events (event_id);
CREATE INDEX IF NOT EXISTS ix_tracking_events_order_id   ON tracking_events (order_id);
CREATE INDEX IF NOT EXISTS ix_tracking_events_event_name ON tracking_events (event_name);
CREATE INDEX IF NOT EXISTS ix_tracking_events_created_at ON tracking_events (created_at);

-- -----------------------------------------------------------------------------
-- alembic_version  (mark migrations applied so future `alembic upgrade head`
-- does not try to re-create tables)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS alembic_version (
    version_num VARCHAR(32) NOT NULL PRIMARY KEY
);

INSERT INTO alembic_version (version_num)
SELECT '002'
WHERE NOT EXISTS (SELECT 1 FROM alembic_version);

UPDATE alembic_version SET version_num = '002';

COMMIT;
