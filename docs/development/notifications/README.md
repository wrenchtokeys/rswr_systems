# Notification System Documentation

**Status**:  Phases 1-5 Complete |  Ready for Phase 6 Testing
**Last Updated**: November 30, 2025
**Version**: 1.0

---

## Overview

Complete documentation for the RS Systems notification system implementation. This multi-phase project adds comprehensive notification capabilities with email (AWS SES), SMS (AWS SNS), and in-app notifications for technicians, managers, and customers.

## Quick Navigation

- ** [Configuration Guide](NOTIFICATION_CONFIGURATION_GUIDE.md)** - Branding, settings, phone numbers
- ** [Setup & Testing Guide](SETUP_AND_TESTING_GUIDE.md)** - Comprehensive setup and testing
- ** [Phase 6 Testing Checklist](PHASE_6_TESTING_CHECKLIST.md)** - Ready to begin testing
- ** [Simple Testing Guide](SIMPLE_TESTING_GUIDE.md)** - Quick developer reference
- ** [AWS Setup Guide](setup/AWS_SETUP_GUIDE.md)** - AWS SES/SNS configuration
- ** [Redis Setup Guide](setup/REDIS_LOCAL_SETUP.md)** - Local Redis installation

---

## Project Scope

**4-Tier Priority System:**
- **URGENT**: SMS + Email + In-app (approvals, denials, critical assignments)
- **HIGH**: SMS + In-app (new requests, completions, reassignments)
- **MEDIUM**: Email + In-app (status updates, photos, rewards)
- **LOW**: In-app only (notes, minor updates)

**Infrastructure:**
- AWS SES for email delivery
- AWS SNS for SMS delivery
- Celery + Redis for async task processing
- Signal-based event triggers
- Customizable email templates with branding

---

## Documentation Structure

```
docs/development/notifications/
 README.md (this file)                    # Documentation index + quick start
 NOTIFICATION_CONFIGURATION_GUIDE.md      # Configuration reference
 SIMPLE_TESTING_GUIDE.md                  # Simple developer guide
 SETUP_AND_TESTING_GUIDE.md              # Comprehensive setup & testing
 PHASE_6_TESTING_CHECKLIST.md            # Testing checklist

 completion/                              # Phase completion summaries
    PHASE_1_SUMMARY.md                  # Foundation & Models ( Complete)
    PHASE_2_SUMMARY.md                  # AWS Infrastructure ( Complete)
    PHASE_3_SUMMARY.md                  # Email Templates ( Complete)
    PHASE_4_SUMMARY.md                  # Service Layer ( Complete)
    PHASE_5_SUMMARY.md                  # User Preferences ( Complete)

 implementation/                          # Implementation specifications
    PHASE_1_FOUNDATION_MODELS.md
    PHASE_2_AWS_INFRASTRUCTURE.md
    PHASE_3_EMAIL_CUSTOMIZATION.md
    PHASE_4_SERVICE_LAYER.md
    PHASE_5_USER_PREFERENCES.md
    PHASE_6_MONITORING_TESTING.md       # Next phase

 setup/                                   # Infrastructure setup guides
     AWS_SETUP_GUIDE.md                  # AWS SES/SNS configuration
     REDIS_LOCAL_SETUP.md                # Redis installation
     setup_notifications.sh              # Automated setup script
     start_notifications.sh              # Service startup script
```

---

## Phase Implementation Summary

###  Phase 1: Foundation & Models (COMPLETE)
**[Implementation Spec](implementation/PHASE_1_FOUNDATION_MODELS.md)** | **[Completion Summary](completion/PHASE_1_SUMMARY.md)**

Core database models and architecture:
- Unified `Notification` model (polymorphic recipients)
- `NotificationPreference` models (technician & customer)
- `NotificationTemplate` model (reusable templates)
- `NotificationDeliveryLog` model (audit trail)
- Database migrations and contact verification fields

**Key Deliverables**:  All models created, migrations applied, admin interface configured, 23 unit tests passing

---

###  Phase 2: AWS Infrastructure (COMPLETE)
**[Implementation Spec](implementation/PHASE_2_AWS_INFRASTRUCTURE.md)** | **[Completion Summary](completion/PHASE_2_SUMMARY.md)**

Cloud infrastructure setup:
- AWS SES configuration (email delivery)
- AWS SNS configuration (SMS delivery)
- Celery + Redis configuration
- Test commands for SES/SNS
- Systemd deployment files

**Key Deliverables**:  SES/SNS configured, Celery workers running, Redis operational, deployment guides complete

---

###  Phase 3: Email Customization (COMPLETE)
**[Implementation Spec](implementation/PHASE_3_EMAIL_CUSTOMIZATION.md)** | **[Completion Summary](completion/PHASE_3_SUMMARY.md)**

Professional email template system:
- `EmailBrandingConfig` model (singleton)
- Base email template (responsive, email-client compatible)
- 5+ notification-specific templates (HTML + plain text)
- Admin interface with color picker and logo preview
- Email preview system for staff

**Key Deliverables**:  Email branding functional, all templates created, preview system working, admin interface complete

---

###  Phase 4: Service Layer & Event Triggers (COMPLETE)
**[Implementation Spec](implementation/PHASE_4_SERVICE_LAYER.md)** | **[Completion Summary](completion/PHASE_4_SUMMARY.md)**

Core notification business logic:
- `NotificationService` (create, queue, render)
- `EmailService` (send via SES)
- `SMSService` (send via SNS)
- Celery tasks (async delivery, retry, digest)
- Signal handlers (automatic triggers on repair events)

**Key Deliverables**:  All services implemented, signal handlers firing, Celery tasks executing, delivery logs recording

---

###  Phase 5: User Preferences (COMPLETE)
**[Implementation Spec](implementation/PHASE_5_USER_PREFERENCES.md)** | **[Completion Summary](completion/PHASE_5_SUMMARY.md)**

User interface for notification control:
- Technician preferences page (channel toggles, quiet hours, digest mode)
- Notification center (bell component, unread count)
- Notification history (paginated, filterable)
- Contact verification workflow
- Customer preferences page

**Key Deliverables**:  Preference pages functional, notification bell working, history view complete, verification workflow ready

---

###  Phase 6: Monitoring, Testing & Deployment (NEXT)
**[Implementation Spec](implementation/PHASE_6_MONITORING_TESTING.md)** | **[Testing Checklist](PHASE_6_TESTING_CHECKLIST.md)**

Production readiness:
- Comprehensive test suite (unit, integration, E2E)
- Monitoring setup (CloudWatch metrics, alarms, Sentry)
- Admin dashboard enhancements
- Deployment procedures and runbooks
- Performance optimizations

**Status**:  **Ready to Begin Testing** - See [Phase 6 Testing Checklist](PHASE_6_TESTING_CHECKLIST.md)

---

## Quick Start

### 3-Step Local Setup

```bash
# Step 1: Install & Start Redis
brew install redis && brew services start redis
redis-cli ping  # Should return: PONG

# Step 2: Run Setup Script
bash docs/development/notifications/setup/setup_notifications.sh

# Step 3: Start All Services
bash docs/development/notifications/setup/start_notifications.sh
```

**Access at**: http://localhost:8000

**Detailed Instructions**: See [SETUP_AND_TESTING_GUIDE.md](SETUP_AND_TESTING_GUIDE.md)

### Manual Setup (Alternative)

```bash
# Install dependencies
pip install -r requirements.txt

# Run migrations
python manage.py migrate

# Create notification templates
python manage.py setup_notification_templates

# Start services (4 terminals)
python manage.py runserver                           # Terminal 1
celery -A rs_systems worker --loglevel=info          # Terminal 2
celery -A rs_systems beat --loglevel=info            # Terminal 3
celery -A rs_systems flower                          # Terminal 4 (optional)
```

### Verify Setup

1. **Login**: http://localhost:8000/tech/login/ (use `testtech` / `testpass123`)
2. **Dashboard**: Check notification bell icon in header
3. **Preferences**: http://localhost:8000/tech/notifications/preferences/
4. **Create test repair** in Django shell to trigger a notification
5. **Refresh dashboard** — bell icon should show unread count

### Testing

```bash
# Test AWS services
python manage.py test_ses your@email.com             # Email test
python manage.py test_sns +12025551234               # SMS test

# Run test suite
python manage.py test core.tests                     # Unit tests

# Django checks
python manage.py check                               # System validation
```

**Full Testing Guide**: See [PHASE_6_TESTING_CHECKLIST.md](PHASE_6_TESTING_CHECKLIST.md)

### Technician Portal URLs

| Path | Description |
|------|-------------|
| `/tech/` | Dashboard with notification bell |
| `/tech/notifications/preferences/` | Notification preferences |
| `/tech/notifications/history/` | Notification history |
| `/tech/notifications/<id>/mark-read/` | Mark single as read (POST) |
| `/tech/notifications/mark-all-read/` | Mark all as read (POST) |
| `/tech/notifications/unread-count/` | Unread count (GET, AJAX) |
| `/tech/verify-email/` | Send email verification |
| `/tech/verify-phone/` | Send phone verification |

### Monitoring

**Celery Flower**: http://localhost:5555 — view active tasks, success/failure rates, worker status.

**Django Admin**: http://localhost:8000/admin/ — view notifications, delivery logs, templates, preferences.

### Security Notes

- **Development**: Emails print to console, SMS shows code in message, DEBUG=True
- **Production**: Real emails via AWS SES, real SMS via AWS SNS, CSRF protection, HTTPS required, rate limiting

---

## Architecture Diagram

```

                    Repair Events                        
  (Created, Approved, Denied, Assigned, Completed)       

                     
                     

                 Django Signals                          
  (post_save handlers detect status changes)            

                     
                     

              NotificationService                        
   Create Notification record                          
   Check user preferences                              
   Render email/SMS templates                          
   Determine delivery channels (priority-based)        

                                                     
                                                     
          
     Celery Task Queue                 In-App Notification    
  (Redis Broker)                      (Database record)       
          
                      
                      
  
 EmailService     SMSService  
                              
  Render         Validate   
  Send (SES)     Send (SNS) 
  Log result     Log result 
  
                        
                        
  
   AWS SES         AWS SNS    
   (Email)          (SMS)     
  
                        
                        

   NotificationDeliveryLog        
  (Audit trail for all deliveries)

```

---

## Event-to-Priority Mapping Reference

| Event | Recipient | Priority | Channels | Template |
|-------|-----------|----------|----------|----------|
| Repair created (PENDING) | Customer | HIGH | SMS + In-app | `repair_pending_approval` |
| Repair approved | Technician | URGENT | SMS + Email + In-app | `repair_approved` |
| Repair denied | Technician | URGENT | SMS + Email + In-app | `repair_denied` |
| Technician assigned | Technician | HIGH | SMS + In-app | `repair_assigned` |
| Technician reassigned | Old Tech | MEDIUM | Email + In-app | `repair_reassigned_away` |
| Repair in progress | Customer | MEDIUM | Email + In-app | `repair_in_progress` |
| Repair completed | Customer | HIGH | SMS + In-app | `repair_completed` |
| Batch approved | Technician | URGENT | SMS + Email + In-app | `batch_approved` |
| Batch denied | Technician | URGENT | SMS + Email + In-app | `batch_denied` |
| Reward redemption | Technician | MEDIUM | Email + In-app | `reward_redemption` |

---

## Cost Estimates

**Assumptions:**
- 100 technicians, 50 customers
- 10 notifications/user/day = 1,500/day = 45,000/month

**Monthly Costs:**
- Email (27,000 @ $0.0001): **$2.70**
- SMS (13,500 @ $0.00645): **$87.08**
- Redis ElastiCache (t3.micro): **$12.96**
- **Total: ~$102/month**

**Optimization Tips:**
- Use email for non-urgent (much cheaper)
- Allow SMS opt-out for non-critical categories
- Implement daily digests
- Monitor weekly and adjust

---

## Support & Troubleshooting

### Common Issues

**Emails not sending?**
 See [SETUP_AND_TESTING_GUIDE.md - Troubleshooting](SETUP_AND_TESTING_GUIDE.md#troubleshooting)

**High SMS costs?**
 Review priority mapping, encourage email preferences, see [setup/AWS_SETUP_GUIDE.md](setup/AWS_SETUP_GUIDE.md)

**Celery tasks stuck?**
 Check Redis connection, restart workers, see [setup/REDIS_LOCAL_SETUP.md](setup/REDIS_LOCAL_SETUP.md)

**Notifications not triggering?**
 Verify signal handlers, see [SETUP_AND_TESTING_GUIDE.md](SETUP_AND_TESTING_GUIDE.md#testing-each-component)

### Getting Help

- **Setup Guide**: [SETUP_AND_TESTING_GUIDE.md](SETUP_AND_TESTING_GUIDE.md)
- **Testing Checklist**: [PHASE_6_TESTING_CHECKLIST.md](PHASE_6_TESTING_CHECKLIST.md)
- **AWS Configuration**: [setup/AWS_SETUP_GUIDE.md](setup/AWS_SETUP_GUIDE.md)
- **Redis Setup**: [setup/REDIS_LOCAL_SETUP.md](setup/REDIS_LOCAL_SETUP.md)
- **Deployment**: `../../deployment/README.md`

---

## Next Steps

### Immediate (Phase 6):
1. **Testing**: Follow [PHASE_6_TESTING_CHECKLIST.md](PHASE_6_TESTING_CHECKLIST.md)
2. **Local Testing**: Complete all Phase 1-5 tests
3. **Integration Testing**: End-to-end workflow validation
4. **Performance Testing**: Load and stress testing

### Post-Phase 6:
1. **Week 1**: Internal testing with staff
2. **Week 2**: Pilot with 25% of technicians
3. **Week 3**: Full technician rollout
4. **Week 4**: Customer rollout
5. **Month 2**: Optimize based on usage patterns
6. **Quarter 2**: Advanced features (push notifications, webhooks, analytics)

---

## Contributing

When updating notification system:

1. Update appropriate documentation in `completion/` or `implementation/`
2. Add tests for new functionality
3. Update this README if architecture changes
4. Document any new environment variables in `.env.example`
5. Update cost estimates if infrastructure changes
6. Keep [SETUP_AND_TESTING_GUIDE.md](SETUP_AND_TESTING_GUIDE.md) current

---

## Documentation Index

### Quick Reference
- [Configuration Guide](NOTIFICATION_CONFIGURATION_GUIDE.md)
- [Simple Testing Guide](SIMPLE_TESTING_GUIDE.md)
- [Setup & Testing Guide](SETUP_AND_TESTING_GUIDE.md)
- [Phase 6 Testing Checklist](PHASE_6_TESTING_CHECKLIST.md)

### Completion Summaries
- [Phase 1: Foundation & Models](completion/PHASE_1_SUMMARY.md)
- [Phase 2: AWS Infrastructure](completion/PHASE_2_SUMMARY.md)
- [Phase 3: Email Templates](completion/PHASE_3_SUMMARY.md)
- [Phase 4: Service Layer](completion/PHASE_4_SUMMARY.md)
- [Phase 5: User Preferences](completion/PHASE_5_SUMMARY.md)

### Implementation Specs
- [Phase 1 Spec](implementation/PHASE_1_FOUNDATION_MODELS.md)
- [Phase 2 Spec](implementation/PHASE_2_AWS_INFRASTRUCTURE.md)
- [Phase 3 Spec](implementation/PHASE_3_EMAIL_CUSTOMIZATION.md)
- [Phase 4 Spec](implementation/PHASE_4_SERVICE_LAYER.md)
- [Phase 5 Spec](implementation/PHASE_5_USER_PREFERENCES.md)
- [Phase 6 Spec](implementation/PHASE_6_MONITORING_TESTING.md)

### Setup Guides
- [AWS SES/SNS Setup](setup/AWS_SETUP_GUIDE.md)
- [Redis Local Setup](setup/REDIS_LOCAL_SETUP.md)

---

**Status**:  Phases 1-5 Complete |  Ready for Phase 6 Testing
**Last Updated**: November 30, 2025
**Version**: 1.0
