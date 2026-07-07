#!/bin/bash
# Collect static files BEFORE the app flips to /var/app/current and gunicorn
# starts. Predeploy hooks run on normal deploys AND on autoscaling scale-up
# (self-startup), so every instance boots with a complete staticfiles
# manifest. Running this in postdeploy caused 500s: gunicorn workers started
# against an empty STATIC_ROOT and cached an empty manifest for the life of
# the process ("Missing staticfiles manifest entry" — July 2026 incident).
set -e

source /var/app/venv/*/bin/activate
cd /var/app/staging

echo "Collecting static files (predeploy)..."
python manage.py collectstatic --noinput
