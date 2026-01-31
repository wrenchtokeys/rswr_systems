# Deployment Configuration Files

This directory contains systemd service files for production deployment of Celery workers.

## Files

- `celery-worker.service` - Celery worker process service
- `celery-beat.service` - Celery beat scheduler service

## Installation on Production Server

### Prerequisites

1. **Create django user and group:**
   ```bash
   sudo useradd -r -s /bin/bash -m -d /home/django django
   ```

2. **Deploy application to /var/www/rs_systems:**
   ```bash
   sudo mkdir -p /var/www/rs_systems
   sudo chown django:django /var/www/rs_systems
   ```

3. **Create virtual environment:**
   ```bash
   sudo -u django python3 -m venv /var/www/rs_systems/venv
   sudo -u django /var/www/rs_systems/venv/bin/pip install -r requirements.txt
   ```

4. **Ensure Redis is running:**
   ```bash
   sudo systemctl status redis
   # or if using ElastiCache, verify connection
   redis-cli -h your-elasticache-endpoint ping
   ```

### Install Systemd Services

```bash
# Copy service files to systemd directory
sudo cp deployment/celery-worker.service /etc/systemd/system/
sudo cp deployment/celery-beat.service /etc/systemd/system/

# Reload systemd daemon
sudo systemctl daemon-reload

# Enable services to start on boot
sudo systemctl enable celery-worker
sudo systemctl enable celery-beat

# Start services
sudo systemctl start celery-worker
sudo systemctl start celery-beat

# Check status
sudo systemctl status celery-worker
sudo systemctl status celery-beat
```

### Verify Services are Running

```bash
# Check worker status
sudo systemctl status celery-worker

# Check beat status
sudo systemctl status celery-beat

# View worker logs
sudo journalctl -u celery-worker -f

# View beat logs
sudo journalctl -u celery-beat -f

# Or check log files directly
sudo tail -f /var/log/celery/worker.log
sudo tail -f /var/log/celery/beat.log
```

## Configuration Notes

### Customizing Service Files

Before installing, you may need to customize these paths:

- **WorkingDirectory**: `/var/www/rs_systems` (application root)
- **User/Group**: `django` (application user)
- **Concurrency**: `--concurrency=8` (adjust based on CPU cores)
- **Queues**: `--queues=celery,notifications,maintenance`

### Environment Variables

Service files use `DJANGO_SETTINGS_MODULE=rs_systems.settings.production`. To load additional environment variables:

**Option 1: EnvironmentFile (Recommended)**

Uncomment this line in service files:
```ini
EnvironmentFile=/var/www/rs_systems/.env
```

Then create `/var/www/rs_systems/.env` with production values:
```bash
sudo nano /var/www/rs_systems/.env

# Add:
CELERY_BROKER_URL=redis://your-elasticache-endpoint:6379/0
AWS_SES_SMTP_USER=AKIA...
AWS_SES_SMTP_PASSWORD=...
# etc.

# Set permissions
sudo chown django:django /var/www/rs_systems/.env
sudo chmod 600 /var/www/rs_systems/.env
```

**Option 2: Environment directive**

Add individual environment variables directly in service file:
```ini
Environment="AWS_SES_SMTP_USER=AKIA..."
Environment="AWS_SES_SMTP_PASSWORD=..."
```

## Managing Services

### Start/Stop/Restart

```bash
# Worker
sudo systemctl start celery-worker
sudo systemctl stop celery-worker
sudo systemctl restart celery-worker

# Beat
sudo systemctl start celery-beat
sudo systemctl stop celery-beat
sudo systemctl restart celery-beat

# Both
sudo systemctl restart celery-worker celery-beat
```

### Enable/Disable Auto-start

```bash
# Enable (start on boot)
sudo systemctl enable celery-worker celery-beat

# Disable (don't start on boot)
sudo systemctl disable celery-worker celery-beat
```

### View Logs

```bash
# Real-time logs (systemd journal)
sudo journalctl -u celery-worker -f
sudo journalctl -u celery-beat -f

# Log files
sudo tail -f /var/log/celery/worker.log
sudo tail -f /var/log/celery/beat.log

# View errors only
sudo journalctl -u celery-worker -p err
```

## Troubleshooting

### Service Won't Start

```bash
# Check service status for errors
sudo systemctl status celery-worker

# View full logs
sudo journalctl -u celery-worker -xe

# Common issues:
# 1. Permission denied on /var/run/celery
sudo chown -R django:django /var/run/celery

# 2. Permission denied on /var/log/celery
sudo chown -R django:django /var/log/celery

# 3. Virtual environment not found
sudo ls -la /var/www/rs_systems/venv/bin/celery

# 4. Redis not accessible
sudo -u django redis-cli ping
```

### Worker Not Processing Tasks

```bash
# Check if worker is connected to Redis
sudo journalctl -u celery-worker | grep "Connected to redis"

# Check active tasks
sudo -u django /var/www/rs_systems/venv/bin/celery -A rs_systems inspect active

# Check registered tasks
sudo -u django /var/www/rs_systems/venv/bin/celery -A rs_systems inspect registered

# Purge all tasks (CAUTION: deletes queued tasks)
sudo -u django /var/www/rs_systems/venv/bin/celery -A rs_systems purge
```

### Memory Issues

If workers consume too much memory, adjust in service file:

```ini
[Service]
MemoryLimit=2G
CELERY_WORKER_MAX_TASKS_PER_CHILD=1000
```

Then reload and restart:
```bash
sudo systemctl daemon-reload
sudo systemctl restart celery-worker
```

## Monitoring

### Flower (Web UI)

For production monitoring, consider installing Flower:

```bash
# Install Flower
sudo -u django /var/www/rs_systems/venv/bin/pip install flower

# Run Flower (basic auth required for production)
sudo -u django /var/www/rs_systems/venv/bin/celery -A rs_systems flower \
    --basic_auth=admin:secure_password \
    --port=5555
```

Create systemd service for Flower:

```bash
sudo nano /etc/systemd/system/celery-flower.service

# Add service configuration similar to worker/beat
# Then enable and start
sudo systemctl enable celery-flower
sudo systemctl start celery-flower
```

Access at: `http://your-server:5555`

### CloudWatch Integration

For AWS deployments, consider logging to CloudWatch:

```bash
# Install CloudWatch agent
# Configure to ship /var/log/celery/*.log to CloudWatch Logs
```

## Security Considerations

1. **Run as non-root user** - Services run as `django` user (not root)
2. **Restrict file permissions** - Log files only readable by django user
3. **Secure environment variables** - Use EnvironmentFile with 600 permissions
4. **Limit resource usage** - MemoryLimit and CPUQuota prevent resource exhaustion
5. **Flower authentication** - Always use basic auth or token auth for Flower in production

## Resource Limits

Adjust based on your server specs:

```ini
# In service file:
LimitNOFILE=65536          # Max open files
MemoryLimit=2G             # Max memory
CPUQuota=400%              # Max 4 CPU cores (400% of one core)
```

## Updates and Deployment

When deploying code updates:

```bash
# 1. Pull latest code
cd /var/www/rs_systems
sudo -u django git pull

# 2. Update dependencies
sudo -u django /var/www/rs_systems/venv/bin/pip install -r requirements.txt

# 3. Restart workers to pick up changes
sudo systemctl restart celery-worker celery-beat

# 4. Verify
sudo systemctl status celery-worker celery-beat
```

## Further Reading

- [Celery Daemonization](https://docs.celeryproject.org/en/stable/userguide/daemonizing.html)
- [systemd Service Documentation](https://www.freedesktop.org/software/systemd/man/systemd.service.html)
- [Flower Documentation](https://flower.readthedocs.io/)
