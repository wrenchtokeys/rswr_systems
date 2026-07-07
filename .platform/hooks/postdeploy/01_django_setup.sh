#!/bin/bash
set -e

# Django post-deployment setup
source /var/app/venv/*/bin/activate
cd /var/app/current

# Create media directories
echo "Creating media directories..."
mkdir -p /var/app/current/media/repair_photos/before
mkdir -p /var/app/current/media/repair_photos/after
chmod -R 755 /var/app/current/media
chown -R webapp:webapp /var/app/current/media

# Database migrations
echo "Running Django migrations..."
python manage.py migrate --noinput

# Create cache table (used by django-ratelimit when Redis is not available)
echo "Creating cache table..."
python manage.py createcachetable --database default 2>/dev/null || echo "Cache table already exists"

# Static files are collected in the predeploy hook
# (.platform/hooks/predeploy/01_collectstatic.sh) so the manifest exists
# before gunicorn starts. Do NOT collect them here: rewriting the manifest
# after workers have started re-introduces the empty-manifest 500 race.

# Notification templates (idempotent)
echo "Setting up notification templates..."
python manage.py setup_notification_templates || echo "Warning: setup_notification_templates failed"

# Set Stripe price IDs (idempotent)
echo "Setting Stripe price IDs..."
python manage.py set_stripe_prices || echo "Warning: set_stripe_prices failed"

echo "Django setup completed"
