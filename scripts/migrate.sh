#!/bin/sh
# Run migrations before starting the API (used in Docker / production deploy)
set -e
echo "Running database migrations..."
alembic upgrade head
echo "Migrations complete."
