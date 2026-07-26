-- Nasama Shop — initial database schema (migration 001)
-- Run this in PostgreSQL (pgAdmin, Supabase SQL, Railway, etc.)
-- Then orders API will work.

CREATE TABLE IF NOT EXISTS orders (
    id UUID PRIMARY KEY,
    order_number VARCHAR(32) NOT NULL,
    customer_name VARCHAR(255) NOT NULL,
    phone_e164 VARCHAR(20) NOT NULL,
    phone_national VARCHAR(15) NOT NULL,
    status VARCHAR(50) NOT NULL DEFAULT 'pending',
    subtotal NUMERIC(10, 2) NOT NULL,
    upsell_total NUMERIC(10, 2) NOT NULL DEFAULT 0,
    total NUMERIC(10, 2) NOT NULL,
    currency VARCHAR(3) NOT NULL DEFAULT 'SAR',
    payment_method VARCHAR(50) NOT NULL DEFAULT 'COD',
    items JSONB NOT NULL,
    upsell_item JSONB,
    landing_page VARCHAR(500),
    utm JSONB,
    click_ids JSONB,
    cookies JSONB,
    event_id VARCHAR(255),
    client_ip VARCHAR(45),
    user_agent VARCHAR(1000),
    sheet_sent_at TIMESTAMPTZ,
    sheet_response JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_orders_order_number UNIQUE (order_number)
);

CREATE INDEX IF NOT EXISTS ix_orders_order_number ON orders (order_number);
CREATE INDEX IF NOT EXISTS ix_orders_event_id ON orders (event_id);

CREATE TABLE IF NOT EXISTS tracking_events (
    id UUID PRIMARY KEY,
    event_name VARCHAR(100) NOT NULL,
    event_id VARCHAR(255),
    order_id UUID REFERENCES orders (id) ON DELETE SET NULL,
    payload JSONB NOT NULL,
    provider_results JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_tracking_events_event_id ON tracking_events (event_id);
CREATE INDEX IF NOT EXISTS ix_tracking_events_order_id ON tracking_events (order_id);

-- Alembic version tracking (so "alembic upgrade head" knows DB is current)
CREATE TABLE IF NOT EXISTS alembic_version (
    version_num VARCHAR(32) NOT NULL PRIMARY KEY
);

INSERT INTO alembic_version (version_num)
VALUES ('001')
ON CONFLICT (version_num) DO NOTHING;
