# RS Systems Documentation

Documentation index for the RS Systems windshield repair management platform.

---

## Getting Started

| Guide | Description |
|-------|-------------|
| [BILLING_GUIDE.md](BILLING_GUIDE.md) | Invoicing, payments, Stripe setup, sales tax |
| [DEVELOPER_GUIDE.md](DEVELOPER_GUIDE.md) | System architecture, code standards, API development |
| [TROUBLESHOOTING.md](TROUBLESHOOTING.md) | Common issues and solutions |

---

## By Directory

### `deployment/`
- [AWS_DEPLOYMENT.md](deployment/AWS_DEPLOYMENT.md) -- AWS Elastic Beanstalk deployment
- [PRODUCTION_CHECKLIST.md](deployment/PRODUCTION_CHECKLIST.md) -- Pre/post deployment verification

### `security/`
- [SECURITY_OVERVIEW.md](security/SECURITY_OVERVIEW.md) -- Security features and roadmap
- [INCIDENT_RESPONSE.md](security/INCIDENT_RESPONSE.md) -- Emergency response procedures

### `development/`
- [ROADMAP.md](development/ROADMAP.md) -- Project roadmap (completed, next up, backlog)
- [CHANGELOG.md](development/CHANGELOG.md) -- Version history (canonical changelog)
- [UI_DESIGN_GUIDE.md](development/UI_DESIGN_GUIDE.md) -- Design system and UI components
- [FRONTEND_GUIDE.md](development/FRONTEND_GUIDE.md) -- CSS architecture, D3.js visualizations, linting
- [TESTING.md](development/TESTING.md) -- Testing procedures
- [MANAGER_SETTINGS_ROADMAP.md](development/MANAGER_SETTINGS_ROADMAP.md) -- Manager settings feature plan
- [SUBSCRIPTION_LIFECYCLE.md](development/SUBSCRIPTION_LIFECYCLE.md) -- Trial/subscription lifecycle plan
- [notifications/README.md](development/notifications/README.md) -- Notification system docs (architecture, setup, testing)

### `operations/`
- [NOTIFICATION_OPERATIONS.md](operations/NOTIFICATION_OPERATIONS.md) -- Daily ops guide + troubleshooting runbook
- [INCIDENT_2026-07-06_REPAIR_FORM_500.md](operations/INCIDENT_2026-07-06_REPAIR_FORM_500.md) -- Staticfiles-manifest-race incident report

### `proposals/`
- [README.md](proposals/README.md) -- Feature proposal index with shipped/draft status tracking

### `archive/`
Historical/superseded docs kept for reference — not actively maintained. See
[archive/](archive/) for the full list (past audits, retired roadmaps, one-time test plans,
superseded strategy docs).

### `user-guides/`
- [ADMIN_GUIDE.md](user-guides/ADMIN_GUIDE.md) -- Administrator interface
- [TECHNICIAN_GUIDE.md](user-guides/TECHNICIAN_GUIDE.md) -- Technician portal
- [CUSTOMER_GUIDE.md](user-guides/CUSTOMER_GUIDE.md) -- Customer portal
- [USER_FLOWS.md](user-guides/USER_FLOWS.md) -- Complete user journeys by role
- [MULTI_BREAK_QUICK_START.md](user-guides/MULTI_BREAK_QUICK_START.md) -- Multi-break batch repair guide
- [VISCOSITY_CONFIGURATION_GUIDE.md](user-guides/VISCOSITY_CONFIGURATION_GUIDE.md) -- Viscosity rules configuration

---

## Quick Access

- **Billing & Stripe**: [BILLING_GUIDE.md](BILLING_GUIDE.md)
- **Deployment**: [deployment/AWS_DEPLOYMENT.md](deployment/AWS_DEPLOYMENT.md)
- **Notifications**: [development/notifications/README.md](development/notifications/README.md)
- **Notification ops**: [operations/NOTIFICATION_OPERATIONS.md](operations/NOTIFICATION_OPERATIONS.md)
- **UI components**: [development/UI_DESIGN_GUIDE.md](development/UI_DESIGN_GUIDE.md)
- **Security**: [security/SECURITY_OVERVIEW.md](security/SECURITY_OVERVIEW.md)
