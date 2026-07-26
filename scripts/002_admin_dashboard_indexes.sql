-- Optional performance indexes for the admin dashboard.
-- Run this in Postgres after the initial schema exists.

CREATE INDEX IF NOT EXISTS ix_orders_created_at
  ON orders (created_at DESC);

CREATE INDEX IF NOT EXISTS ix_orders_status_created_at
  ON orders (status, created_at DESC);

CREATE INDEX IF NOT EXISTS ix_tracking_events_event_name_created_at
  ON tracking_events (event_name, created_at DESC);

CREATE INDEX IF NOT EXISTS ix_tracking_events_created_at
  ON tracking_events (created_at DESC);
