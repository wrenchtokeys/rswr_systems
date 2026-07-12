# Manager Settings Roadmap

## Overview
The Manager Settings portal provides managers with a centralized interface for configuring system parameters and managing their teams. This document outlines completed features and planned enhancements.

##  Phase 1: Core Settings Infrastructure (Completed - November 2025)

### Implemented Features

#### Manager Settings Dashboard (`/tech/settings/`)
- **Card-Based Navigation**: Modern tile layout for feature discovery
- **Permission-Based Access**: Restricted to managers (`is_manager=True`) and staff users
- **Future Feature Placeholders**: Visual indicators for planned features
- **Admin Badge**: Special indicator for staff users with elevated privileges

**Technical Implementation**:
- New decorator: `@manager_required` for view-level access control
- Navigation integration: "Manager Settings" link in user dropdown menu
- URL namespace: `/tech/settings/` for all manager configuration

#### Viscosity Rules Management (`/tech/settings/viscosity/`)
**Purpose**: Configure temperature-based resin viscosity recommendations for technicians

**Features Delivered**:
- **Card-Based Interface**: Visual display of each rule with all key information
- **Modal Editing**: Click "Edit" to modify rules in overlay form without page refresh
- **Toggle Switches**: Quick enable/disable functionality in card header
- **Add New Rules**: Green "Add New Rule" button opens creation modal
- **Delete Confirmation**: Safety dialog before removing rules
- **Badge Previews**: See exactly how viscosity recommendations appear to technicians
- **Real-Time Updates**: AJAX operations with toast notifications

**User Experience**:
- No page refreshes for CRUD operations
- Visual feedback for all actions
- Mobile-responsive design
- Professional card aesthetics matching repair form

**Database Model**: `ViscosityRecommendation`
- Temperature range configuration (min/max in ÂF)
- Recommended viscosity level
- Custom suggestion text for technicians
- Badge color selection (6 color options)
- Display order for rule priority
- Active/inactive status toggle

#### Team Overview (`/tech/settings/team/`)
**Purpose**: View performance metrics for managed technicians

**Features Delivered**:
- **Team Summary Stats**: Overall repairs, pending count, completed count
- **Individual Performance Cards**: Stats for each managed technician
  - Total repairs assigned
  - Pending repairs count
  - Completed repairs count
  - Completion rate percentage
  - Visual progress bars
- **Recent Repairs List**: Last 5 repairs for each team member with status badges
- **Contact Information**: Email and phone for each technician

**Access Control**: Only shows technicians in manager's `managed_technicians` M2M relationship

### Technical Stack
**Backend**:
- Django views with `@technician_required` and `@manager_required` decorators
- RESTful AJAX API endpoints for CRUD operations
- JSON responses for all API calls

**Frontend**:
- Pure JavaScript (no frameworks) for simplicity
- AJAX with Fetch API for async operations
- Custom CSS with card-based design system
- Mobile-first responsive layout

**Files Created** (11 files):
1. `apps/technician_portal/decorators.py` - Permission decorators
2. `apps/technician_portal/views.py` - 7 new view functions added
3. `apps/technician_portal/urls.py` - 8 new URL patterns
4. `templates/technician_portal/settings/settings_dashboard.html`
5. `templates/technician_portal/settings/viscosity_rules.html`
6. `templates/technician_portal/settings/team_overview.html`
7. `templates/technician_portal/settings/partials/` - Directory for reusable components
8. `static/js/manager_settings.js` - AJAX modal handling (9.3KB)
9. `static/css/components/manager-settings.css` - Professional styling (16KB)
10. `templates/base.html` - Modified to add navigation link
11. `docs/user-guides/VISCOSITY_CONFIGURATION_GUIDE.md` - Updated documentation

---

##  Phase 2: Pricing Management (Planned)

### Overview
Extend manager settings to include comprehensive pricing configuration capabilities, reducing dependency on database-level pricing modifications.

### Planned Features

#### Custom Pricing Tiers (`/tech/settings/pricing/tiers/`)
**Purpose**: Configure base pricing structure for repair count tiers

**Proposed Features**:
- **Tier Management**: Create, edit, delete pricing tiers
- **Tier Configuration**:
  - Repair count range (e.g., 1-2, 3-5, 6-10, 11+)
  - Base price for tier
  - Description/rationale
  - Active/inactive status
- **Tier Preview**: Visual chart showing pricing progression
- **Default Tier**: Mark one tier as system default

**UI Pattern**: Similar card-based interface with modal editing

#### Per-Customer Pricing Rules (`/tech/settings/pricing/customers/`)
**Purpose**: Override default pricing for specific customers

**Proposed Features**:
- **Customer Selection**: Dropdown or search for customer
- **Pricing Overrides**:
  - Custom tier structure for customer
  - Flat rate option
  - Percentage discount across all tiers
  - Fixed discount per repair
- **Effective Date Range**: Start/end dates for pricing rules
- **Notes Field**: Document pricing agreement rationale

**Business Logic**:
- Customer-specific rules override global tiers
- Multiple rules per customer with date-based priority
- Audit trail for all pricing changes

#### Volume Discount Management (`/tech/settings/pricing/discounts/`)
**Purpose**: Configure automatic discounts based on repair volume

**Proposed Features**:
- **Discount Rules**:
  - Minimum repair count threshold
  - Discount type (percentage or fixed amount)
  - Discount value
  - Duration (per month, per quarter, lifetime)
- **Customer Eligibility**: Apply to all or specific customers
- **Stacking Rules**: Define if discounts can stack with customer pricing

**Technical Considerations**:
- Integration with existing `calculate_repair_cost()` logic
- Backward compatibility with current pricing system
- Database migration for new models

#### Pricing Override Approval Workflow (`/tech/settings/pricing/overrides/`)
**Purpose**: Manage and approve pricing overrides requested by technicians

**Proposed Features**:
- **Pending Overrides Queue**: List of overrides awaiting approval
- **Override Details**:
  - Repair information
  - Technician requesting override
  - Original calculated price
  - Requested price
  - Justification/reason
- **Approval Actions**:
  - Approve with note
  - Deny with reason
  - Request more information
- **Approval Limits**: Respect manager's `approval_limit` field
- **Escalation**: Auto-escalate overrides exceeding limit to higher authority

**Integration**:
- Extends existing repair cost override functionality
- Adds approval workflow layer
- Email/notification triggers for pending approvals

### Database Models (Proposed)

```python
class PricingTier(models.Model):
    """Base pricing structure for repair counts"""
    min_repairs = models.IntegerField()
    max_repairs = models.IntegerField(null=True, blank=True)  # None = unlimited
    base_price = models.DecimalField(max_digits=6, decimal_places=2)
    description = models.TextField(blank=True)
    is_default = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    display_order = models.IntegerField(default=0)

class CustomerPricingRule(models.Model):
    """Customer-specific pricing overrides"""
    customer = models.ForeignKey(Customer)
    rule_type = models.CharField(choices=[...])  # tier_override, flat_rate, percentage, fixed_discount
    pricing_data = models.JSONField()  # Flexible pricing configuration
    effective_start = models.DateField()
    effective_end = models.DateField(null=True, blank=True)
    notes = models.TextField()
    created_by = models.ForeignKey(User)
    created_at = models.DateTimeField(auto_now_add=True)

class VolumeDiscount(models.Model):
    """Automatic discounts based on repair volume"""
    name = models.CharField(max_length=100)
    min_repair_count = models.IntegerField()
    discount_type = models.CharField(choices=[('percentage', 'Percentage'), ('fixed', 'Fixed Amount')])
    discount_value = models.DecimalField(max_digits=6, decimal_places=2)
    duration_type = models.CharField(choices=[...])  # monthly, quarterly, lifetime
    applies_to_all_customers = models.BooleanField(default=True)
    eligible_customers = models.ManyToManyField(Customer, blank=True)

class PricingOverrideRequest(models.Model):
    """Workflow for pricing override approvals"""
    repair = models.ForeignKey(Repair)
    requested_by = models.ForeignKey(Technician)
    original_price = models.DecimalField(max_digits=6, decimal_places=2)
    requested_price = models.DecimalField(max_digits=6, decimal_places=2)
    justification = models.TextField()
    status = models.CharField(choices=[('pending', 'Pending'), ('approved', 'Approved'), ('denied', 'Denied')])
    reviewed_by = models.ForeignKey(User, null=True)
    review_notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    reviewed_at = models.DateTimeField(null=True)
```

---

##  Phase 3: Audit & Reporting (Planned)

### Overview
Provide comprehensive audit trails and reporting capabilities for manager actions and system changes.

### Planned Features

#### Pricing Override Audit Log (`/tech/settings/audit/pricing/`)
**Purpose**: Track all pricing modifications and overrides

**Proposed Features**:
- **Filterable Log Table**:
  - Date range filter
  - Technician filter
  - Customer filter
  - Override type filter (manual, approved, automatic)
- **Log Entry Details**:
  - Timestamp
  - Repair ID and details
  - Technician who made change
  - Original price
  - New price
  - Reason/justification
  - Approval status (if applicable)
- **Export Functionality**: CSV/Excel download for accounting
- **Search**: Full-text search across reasons and notes

**Database Model**:
```python
class PricingAuditLog(models.Model):
    """Comprehensive audit trail for all pricing changes"""
    repair = models.ForeignKey(Repair)
    change_type = models.CharField(choices=[('manual_override', 'Manual Override'), ('approved_request', 'Approved Request'), ('auto_discount', 'Automatic Discount')])
    changed_by = models.ForeignKey(User)
    original_price = models.DecimalField(max_digits=6, decimal_places=2)
    new_price = models.DecimalField(max_digits=6, decimal_places=2)
    reason = models.TextField()
    approved_by = models.ForeignKey(User, null=True, related_name='pricing_approvals')
    timestamp = models.DateTimeField(auto_now_add=True)
    metadata = models.JSONField(default=dict)  # Additional context
```

#### Manager Action History (`/tech/settings/audit/actions/`)
**Purpose**: Track all manager configuration changes

**Proposed Features**:
- **Activity Feed**: Chronological list of manager actions
- **Action Types Tracked**:
  - Viscosity rule changes
  - Pricing configuration updates
  - Team member additions/removals
  - Setting modifications
- **Details Logged**:
  - Timestamp
  - Manager who made change
  - Action type
  - Before/after state (for modifications)
  - Associated entity (repair, customer, technician, etc.)
- **Filtering**: By date, manager, action type, entity

#### Team Performance Reports (`/tech/settings/reports/team/`)
**Purpose**: Advanced analytics for managed technician performance

**Proposed Features**:
- **Date Range Selection**: Custom reporting periods
- **Metrics**:
  - Repairs completed per technician
  - Average completion time
  - Customer satisfaction ratings
  - Revenue generated
  - Override frequency
- **Visualizations**:
  - Performance trend charts
  - Comparison graphs
  - Top performers leaderboard
- **Export**: PDF and Excel reports

**Integration**: Leverage existing repair data, add time tracking

---

##  Phase 4: Advanced Features (Future)

### Team Scheduling
- Calendar view for managed technicians
- Shift management
- Time-off requests
- Workload balancing

### Performance Analytics
- Custom KPI dashboards
- Real-time performance metrics
- Predictive analytics for repair trends
- Customer satisfaction tracking

### Custom Notifications
- Manager-defined notification rules
- Email digest configuration
- Slack/Teams integration
- SMS alerts for critical events

### Integration Settings
- API key management for external services
- Webhook configuration
- Third-party tool connections
- Data export automation

---

## Implementation Priority

### High Priority (Next Quarter)
1. **Pricing Tiers Management** - Most requested feature
2. **Pricing Override Workflow** - Improves oversight
3. **Pricing Audit Log** - Compliance requirement

### Medium Priority (2-3 Quarters)
1. **Customer-Specific Pricing** - Business growth enabler
2. **Volume Discounts** - Competitive advantage
3. **Team Performance Reports** - Management insights

### Low Priority (Future)
1. **Advanced Analytics** - Nice-to-have
2. **Team Scheduling** - Process improvement
3. **Integration Settings** - Scalability feature

---

## Technical Considerations

### Backward Compatibility
- All new features must maintain existing pricing calculation logic
- Database migrations must not break current workflows
- API changes must be versioned

### Performance
- Large audit logs require pagination and indexing
- Reporting features need caching layer
- AJAX operations must remain under 200ms response time

### Security
- All manager actions must be authenticated and authorized
- Audit logs must be append-only (no deletion)
- Sensitive pricing data needs encryption at rest

### Testing
- Unit tests for all pricing calculation changes
- Integration tests for approval workflows
- UI tests for manager settings interfaces

---

## Success Metrics

### Phase 1 (Current)
-  Manager settings accessible to all managers
-  Viscosity rules configurable without code changes
-  Team overview provides actionable insights

### Phase 2 (Pricing)
- Reduce pricing override requests by 50%
- 100% of pricing configurations self-service
- Manager approval workflow reduces admin burden by 75%

### Phase 3 (Audit)
- Complete audit trail for all pricing changes
- Monthly audit reports generated automatically
- Zero compliance issues related to pricing

### Phase 4 (Advanced)
- 90% of manager tasks self-service
- 50% reduction in support tickets
- Positive feedback from manager user surveys

---

## Version History

**v1.0 - November 2025**: Initial roadmap created
- Documented Phase 1 completed features
- Outlined Phases 2-4 planned enhancements

---

## Feedback & Contributions

For feature requests or feedback on this roadmap:
1. Create an issue in the project repository
2. Tag with `manager-settings` label
3. Provide business justification and use cases

For technical questions:
- Review `docs/user-guides/VISCOSITY_CONFIGURATION_GUIDE.md`
- Check `docs/development/CHANGELOG.md` for recent updates
- Consult development team for architecture decisions
