# RS Systems — Scaling Guide

*Last updated: 2026-03-15*

This document covers the current infrastructure, known scaling thresholds, and the upgrade path for each component as traffic grows.

---

## Current Architecture

```
User → CloudFlare → ALB → Elastic Beanstalk (single instance)
                                  │
                                  ├── Gunicorn (Django 5.1)
                                  ├── PostgreSQL (RDS)
                                  ├── S3 (media/photos)
                                  └── DatabaseCache (ratelimit, throttling)
```

**No Redis. No Celery. No background workers.**
Notifications are synchronous. Billing tasks run via management commands + EB cron.

---

## Component Scaling Thresholds

### 1. Caching — DatabaseCache → Redis

**Current:** `django.core.cache.backends.db.DatabaseCache`
Every cache read/write is a SQL query against the `django_cache` table in RDS.

| Traffic | Impact | Action |
|---------|--------|--------|
| < 50 concurrent users | Negligible | None needed |
| 50–200 concurrent users | ~5-10% DB load increase | Monitor RDS CPU |
| 200+ concurrent users | Cache queries compete with app queries | **Upgrade to Redis** |

**Upgrade path:**
1. Create ElastiCache Redis instance (cache.t3.micro, ~$15/mo)
2. Set `REDIS_URL` in EB environment variables
3. Deploy — code auto-detects and switches to `RedisCache` (zero code changes)

**What uses the cache:**
- `django-ratelimit` (login, registration)
- DRF throttling (API rate limits)
- Future: template fragment caching, session storage

---

### 2. Web Server — Single Instance → Auto Scaling Group

**Current:** Single EB instance running Gunicorn

| Traffic | Impact | Action |
|---------|--------|--------|
| < 100 req/sec | Fine | None needed |
| 100–500 req/sec | Response times increase | **Add auto scaling** |
| 500+ req/sec | Possible timeouts | Auto scaling + CDN for static |

**Upgrade path:**
1. EB console → Configuration → Capacity → change to "Load balanced" (if not already)
2. Set min=1, max=3 instances
3. Configure scaling triggers (CPU > 70%, latency > 2s)
4. Ensure sessions use DB backend (already do) — sticky sessions not needed

**Important:** `LocMemCache` would break with multiple instances (each worker has its own cache). `DatabaseCache` and `RedisCache` both work across instances. This is why we chose DatabaseCache over LocMemCache.

---

### 3. Database — RDS Scaling

**Current:** RDS PostgreSQL (instance size set in AWS console)

| Metric | Warning | Critical |
|--------|---------|----------|
| CPU utilization | > 60% sustained | > 80% sustained |
| Free storage | < 5 GB | < 1 GB |
| Connection count | > 80% of max | > 95% of max |
| Read latency | > 10ms avg | > 50ms avg |

**Upgrade path (in order):**
1. **Read replicas** — offload reporting/analytics queries
2. **Instance size** — scale vertically (db.t3.medium → db.t3.large)
3. **Connection pooling** — PgBouncer or RDS Proxy (~$15/mo)
4. **Query optimization** — N+1 fixes, index tuning (ongoing)

---

### 4. Background Tasks — Synchronous → Task Queue

**Current:** Email notifications are synchronous (sent during request). Billing tasks run via management commands on EB cron.

| Symptom | Trigger | Action |
|---------|---------|--------|
| Slow page loads after actions that send email | > 50 emails/day | **Add task queue** |
| Batch invoice generation timing out | > 500 invoices/batch | **Add task queue** |
| Webhook processing blocking responses | > 100 webhooks/hour | **Add task queue** |

**Upgrade path:**
1. Add Redis (needed anyway for cache at this point)
2. Re-enable Celery with Redis as broker
3. Move email, webhook processing, and batch jobs to async tasks
4. Run Celery worker as a separate EB worker environment or ECS task

---

### 5. Media/Photos — S3 (Already Scaled)

**Current:** S3 with direct URLs. No CDN.

| Traffic | Impact | Action |
|---------|--------|--------|
| < 1000 photos/day | Fine | None needed |
| 1000+ photos/day served | S3 egress costs increase | **Add CloudFront CDN** |

**Upgrade path:**
1. Create CloudFront distribution pointing to S3 bucket
2. Update `AWS_S3_CUSTOM_DOMAIN` to CloudFront domain
3. ~$0.085/GB egress vs $0.09/GB direct from S3

---

### 6. Stripe Connect — Onboarding & Fee Collection

**Current:** Stripe Connect shipped and live (March 2026) — direct charges with per-tenant `application_fee_amount`, see `docs/proposals/stripe-connect-implementation-plan.md`. Remaining scale question is onboarding throughput and Phase 3 dashboard reporting as tenant count grows.

| Milestone | Action |
|-----------|--------|
| Tenant Connect-onboarding volume grows | Watch `PlatformFeeRecord` table growth and webhook processing latency |

---

## Scaling Decision Checklist

When you notice performance issues, check in this order:

1. **Is RDS CPU > 60%?** → Check for N+1 queries, missing indexes, or scale instance
2. **Are response times > 2s?** → Check if it's DB, email sending, or Stripe API calls
3. **Is the cache table growing large?** → Consider Redis upgrade
4. **Are you running multiple EB instances?** → Ensure DatabaseCache or Redis (not LocMemCache)
5. **Are emails slowing down requests?** → Time to add Celery

---

## Environment Variables for Scaling

These env vars control scaling behavior with zero code changes:

| Variable | Default | Effect |
|----------|---------|--------|
| `REDIS_URL` | *(not set)* | Set to switch cache from DatabaseCache → Redis |
| `REDIS_CACHE_URL` | *(not set)* | Override cache-specific Redis URL (if different from broker) |
| `USE_S3` | `False` | Set `True` to store media in S3 instead of local filesystem |
| `SENTRY_DSN` | *(not set)* | Set to enable error tracking (recommended) |
| `AWS_CLOUDWATCH_ENABLED` | `False` | Set `True` to enable CloudWatch metrics |

---

## Cost Estimates at Scale

| Component | Current Cost | At 100 shops | At 500 shops |
|-----------|-------------|-------------|-------------|
| EB (single instance) | ~$15/mo | ~$30/mo (2 instances) | ~$60/mo (3-4 instances) |
| RDS PostgreSQL | ~$15/mo | ~$30/mo (larger instance) | ~$60/mo + read replica |
| ElastiCache Redis | $0 | ~$15/mo | ~$15/mo |
| S3 + CloudFront | ~$1/mo | ~$5/mo | ~$15/mo |
| Celery workers | $0 | ~$15/mo (1 worker) | ~$30/mo (2 workers) |
| **Total** | **~$31/mo** | **~$95/mo** | **~$180/mo** |

These are rough estimates. Actual costs depend on usage patterns (photos per repair, invoice volume, API calls).

---

## What NOT to Do

- **Don't add Redis "just in case"** — it's another service to monitor and pay for. Add it when DatabaseCache shows strain.
- **Don't switch to LocMemCache** — it's per-process, breaks with multiple gunicorn workers or EB instances.
- **Don't add Celery without Redis** — Celery needs a broker. If you need Celery, you need Redis (or SQS).
- **Don't enable auto-scaling without testing** — verify sessions, cache, and file uploads work across instances first.
- **Don't optimize prematurely** — profile first, then fix the actual bottleneck.
