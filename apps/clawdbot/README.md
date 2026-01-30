# Clawdbot App - Amelia's Workspace

This Django app is Amelia's (Clawdbot AI) dedicated workspace within RS Systems for building and testing automation features.

## Overview

The clawdbot app provides:
- **Status/Health endpoints** for monitoring
- **Invoice generation API** for automating billing workflows
- **Repair data queries** for building reports and analytics

## Endpoints

### Status & Health

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/clawdbot/` | GET | Status check - returns capabilities and available endpoints |
| `/clawdbot/health/` | GET | Health check - verifies database connectivity |

### Customer & Repair Data

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/clawdbot/customers/` | GET | List all customers with repair counts |
| `/clawdbot/repairs/<customer_id>/` | GET | List completed repairs for a customer |

**Query Parameters for `/repairs/`:**
- `days` (int, default: 30) - Number of days to look back
- `status` (string, default: COMPLETED) - Filter by repair status

### Invoice Generation

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/clawdbot/invoices/preview/<customer_id>/` | GET | Preview invoice data as JSON |
| `/clawdbot/invoices/generate/<customer_id>/` | GET | Download PDF invoice |

**Query Parameters:**
- `days` (int, default: 30) - Number of days to include
- `repair_ids` (comma-separated ints) - Specific repair IDs to include

## Usage Examples

### List customers
```bash
curl https://rockstarwindshield.repair/clawdbot/customers/
```

### Preview an invoice
```bash
curl https://rockstarwindshield.repair/clawdbot/invoices/preview/1/
```

### Download PDF invoice
```bash
curl -o invoice.pdf https://rockstarwindshield.repair/clawdbot/invoices/generate/1/
```

### Invoice for specific repairs only
```bash
curl -o invoice.pdf "https://rockstarwindshield.repair/clawdbot/invoices/generate/1/?repair_ids=10,11,12"
```

### Invoice for last 7 days
```bash
curl -o invoice.pdf "https://rockstarwindshield.repair/clawdbot/invoices/generate/1/?days=7"
```

## Architecture

```
apps/clawdbot/
├── __init__.py
├── apps.py              # Django app config
├── urls.py              # URL routing
├── views.py             # API views
├── README.md            # This file
└── services/
    ├── __init__.py
    └── invoice_service.py  # Invoice generation logic
```

## Development

### Local Testing
```bash
cd /home/ubuntu/rswr_systems
source venv/bin/activate
python manage.py runserver 0.0.0.0:8001

# Test endpoints
curl http://localhost:8001/clawdbot/
curl http://localhost:8001/clawdbot/invoices/preview/1/
```

### Dependencies
- `reportlab` - PDF generation (add to requirements.txt)

## Changelog

### v0.2.0 (2026-01-27)
- Added invoice generation service
- Added customer/repair listing endpoints
- Added invoice preview and PDF download

### v0.1.0 (2026-01-26)
- Initial status and health endpoints
- Basic clawdbot app structure

---

*Maintained by Amelia (Clawdbot AI)*
