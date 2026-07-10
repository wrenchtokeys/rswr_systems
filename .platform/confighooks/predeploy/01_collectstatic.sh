#!/bin/bash
# CONFIG-deploy twin of .platform/hooks/predeploy/01_collectstatic.sh — keep in sync.
#
# Configuration deployments (eb setenv, option changes) re-extract the app
# bundle into /var/app/staging and flip it to /var/app/current, but they run
# .platform/confighooks/, NOT .platform/hooks/. Without this file a config
# deploy replaces STATIC_ROOT with whatever is in the bundle — no manifest,
# no hashed files — and every hashed static URL 404s (July 2026 broken-admin
# incident: eb setenv for SES credentials wiped the collected static files).
set -e

source /var/app/venv/*/bin/activate
cd /var/app/staging

echo "Collecting static files (config-deploy predeploy)..."
python manage.py collectstatic --noinput
