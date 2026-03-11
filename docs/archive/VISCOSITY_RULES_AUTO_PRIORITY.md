# Viscosity Rules Auto-Priority System

## Overview

The Viscosity Rules feature uses an **automatic priority assignment system** that eliminates user confusion and maximizes usability. Users never manually enter priority numbers; instead, they see visual position indicators ( 1st, ˆ 2nd,  3rd).

## Table of Contents

- [How It Works](#how-it-works)
- [Priority Calculation Algorithm](#priority-calculation-algorithm)
- [Visual Display System](#visual-display-system)
- [Rule Evaluation Order](#rule-evaluation-order)
- [Database Schema](#database-schema)
- [Implementation Details](#implementation-details)
- [User Experience Flow](#user-experience-flow)
- [Future Enhancements](#future-enhancements)

---

## How It Works

### Core Concept

When a manager creates a new viscosity rule, the system:

1. **Finds** the highest existing `display_order` value in the database
2. **Adds 10** to that value
3. **Assigns** the result as the new rule's priority
4. **Displays** the rule with a visual badge showing its position (1st, 2nd, 3rd...)

### Why This Approach?

**Problem Solved:**
- Users were confused by "Priority (lower = higher priority)" double-negative wording
- Default value of 999 was meaningless to users
- Manual priority input required understanding of the underlying system

**Solution Benefits:**
-  **Zero cognitive load** - no number input required
-  **Self-documenting** - position you see = order evaluated
-  **Flexible** - adding 10 (not 1) leaves room for manual DB adjustments
-  **Visual** - emoji badges instantly communicate priority

---

## Priority Calculation Algorithm

### Code Implementation

**Location:** `apps/technician_portal/views.py:2110-2115`

```python
# Auto-assign priority: get max existing display_order and add 10
# This leaves room for manual reordering in database if needed
max_order = ViscosityRecommendation.objects.aggregate(
    max_order=models.Max('display_order')
)['max_order']
next_order = (max_order or 0) + 10
```

### Calculation Examples

| Scenario | Existing Priorities | Calculation | New Priority |
|----------|-------------------|-------------|--------------|
| **First rule** | None (empty DB) | `(None or 0) + 10` | **10** |
| **Second rule** | `10` | `10 + 10` | **20** |
| **Third rule** | `10, 20` | `20 + 10` | **30** |
| **After deletion** | `10, 30` (20 deleted) | `30 + 10` | **40** |
| **Mixed priorities** | `1, 2, 3` (legacy) | `3 + 10` | **13** |

### Why Increment by 10?

**Spacing for Flexibility:**
- Rules: `10, 20, 30, 40`
- Admin can manually insert priority `15` between `10` and `20` if needed
- Still have room for `11, 12, 13, 14, 16, 17, 18, 19`

**Alternative Considered:**
- Increment by 1: `1, 2, 3, 4` (no room for insertions)
-  Rejected: Too rigid for manual adjustments

---

## Visual Display System

### Priority Badges

Users see visual position indicators instead of raw numbers:

| Position | Badge | CSS Class | Style |
|----------|-------|-----------|-------|
| **1st** |  | `priority-1` | Gold gradient, 1.5rem font |
| **2nd** | ˆ | `priority-2` | Silver gradient, 1.5rem font |
| **3rd** |  | `priority-3` | Bronze gradient, 1.5rem font |
| **4th+** | "4th", "5th"... | `priority-badge` | Gray gradient, 0.875rem font |

### Badge Generation Logic

**Location:** `apps/technician_portal/views.py:2044-2051`

```python
rules_with_position = [
    {
        'rule': rule,
        'position': idx + 1,  # 1-indexed position for display
        'position_suffix': get_ordinal_suffix(idx + 1)  # "st", "nd", "rd", "th"
    }
    for idx, rule in enumerate(rules)
]
```

### Ordinal Suffix Helper

**Location:** `apps/technician_portal/views.py:2063-2071`

```python
def get_ordinal_suffix(n):
    """
    Returns the ordinal suffix for a number (st, nd, rd, th).
    Examples: 1  "st", 2  "nd", 3  "rd", 4  "th", 11  "th"
    """
    if 10 <= n % 100 <= 20:
        return 'th'  # Special case: 11th, 12th, 13th
    else:
        return {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')
```

### Template Display

**Location:** `templates/technician_portal/settings/viscosity_rules.html:36-38`

```django
<span class="priority-badge priority-{{ item.position }}">
    {% if item.position == 1 %}
    {% elif item.position == 2 %}ˆ
    {% elif item.position == 3 %}
    {% else %}{{ item.position }}{{ item.position_suffix }}
    {% endif %}
</span>
```

---

## Rule Evaluation Order

### How Technicians Get Recommendations

When a technician creates a repair and enters the current temperature, the system:

1. **Queries** active rules ordered by `display_order` (lowest first)
2. **Iterates** through rules in priority order
3. **Returns** the first rule that matches the temperature
4. **Stops** checking remaining rules

### Code Flow

**Location:** `apps/technician_portal/models.py:841-867`

```python
@classmethod
def get_recommendation_for_temperature(cls, temperature_f):
    """
    Get the appropriate viscosity recommendation for a given temperature.
    Returns the FIRST matching active rule (ordered by display_order).
    """
    rules = cls.objects.filter(is_active=True).order_by('display_order')

    for rule in rules:
        if rule.matches_temperature(temperature_f):
            return rule  # First match wins!

    return None  # No matching rule
```

### Example Scenarios

**Setup:**
-  1st (priority 10): "Below 32ÂF"  Low viscosity
- ˆ 2nd (priority 20): "32-85ÂF"  Medium viscosity
-  3rd (priority 30): "Above 85ÂF"  High viscosity

**Temperature: 25ÂF**
1. Check  1st: "Below 32ÂF"   **MATCH**  Use Low viscosity
2.  Stop checking (2nd and 3rd never evaluated)

**Temperature: 70ÂF**
1. Check  1st: "Below 32ÂF"   No match
2. Check ˆ 2nd: "32-85ÂF"   **MATCH**  Use Medium viscosity
3.  Stop checking (3rd never evaluated)

**Temperature: 95ÂF**
1. Check  1st: "Below 32ÂF"   No match
2. Check ˆ 2nd: "32-85ÂF"   No match
3. Check  3rd: "Above 85ÂF"   **MATCH**  Use High viscosity

**Temperature: 120ÂF (overlapping rules)**
- If both 2nd and 3rd match, **2nd wins** (lower priority number)
- This is why order matters!

---

## Database Schema

### Model Field

**Model:** `ViscosityRecommendation`
**Location:** `apps/technician_portal/models.py:749-752`

```python
display_order = models.IntegerField(
    default=0,
    help_text="Order in which rules are evaluated (lower = higher priority)"
)
```

### Field Details

| Attribute | Value | Notes |
|-----------|-------|-------|
| **Type** | `IntegerField` | Stores integer priority values |
| **Default** | `0` | Model default (overridden by view) |
| **Nullable** | No | Always has a value |
| **Indexed** | No | Small table, ordering is fast |
| **Unique** | No | Multiple rules can have same priority (not recommended) |

### Migration History

- **Initial:** `0015_add_viscosity_recommendation_model.py` - Created field with default=0
- **No changes needed:** Auto-priority uses existing field, no migration required

---

## Implementation Details

### Backend Components

#### 1. Auto-Assignment View
**File:** `apps/technician_portal/views.py:2087-2127`

```python
@technician_required
@manager_required
def create_viscosity_rule(request):
    """
    AJAX endpoint to create a new viscosity recommendation rule.
    POST /tech/settings/api/viscosity/create/

    Priority is auto-assigned: new rules get (max existing priority + 10)
    This leaves room for manual database adjustments if needed.
    """
    # ... validation ...

    # Auto-assign priority
    max_order = ViscosityRecommendation.objects.aggregate(
        max_order=models.Max('display_order')
    )['max_order']
    next_order = (max_order or 0) + 10

    # Create rule with auto-assigned priority
    rule = ViscosityRecommendation.objects.create(
        name=data['name'],
        # ... other fields ...
        display_order=next_order,  # Auto-assigned!
        is_active=data.get('is_active', True)
    )
```

#### 2. Position Display View
**File:** `apps/technician_portal/views.py:2029-2060`

```python
@technician_required
@manager_required
def manage_viscosity_rules(request):
    """
    Manage viscosity recommendation rules with card-based interface.
    Rules are displayed with auto-calculated priority positions (1st, 2nd, 3rd...)
    based on their display_order field.
    """
    rules = ViscosityRecommendation.objects.all().order_by('display_order', 'id')
    rules_with_position = [
        {
            'rule': rule,
            'position': idx + 1,
            'position_suffix': get_ordinal_suffix(idx + 1)
        }
        for idx, rule in enumerate(rules)
    ]

    context = {
        'rules_with_position': rules_with_position,
        # ... other context ...
    }
```

### Frontend Components

#### 1. Form Removal
**File:** `templates/technician_portal/settings/viscosity_rules.html:119-127`

**Before (confusing):**
```html
<div class="form-group">
    <label for="displayOrder">Priority (lower = higher priority)</label>
    <input type="number" id="displayOrder" name="display_order"
           class="form-input" value="999" min="1">
</div>
```

**After (removed):**
```html
<div class="form-group">
    <label for="ruleName">Rule Name <span class="required">*</span></label>
    <input type="text" id="ruleName" name="name" class="form-input">
    <small class="field-hint">Priority is automatically assigned - new rules are added at the end</small>
</div>
```

#### 2. JavaScript Payload
**File:** `static/js/manager_settings.js:112-121`

**Before:**
```javascript
const data = {
    name: formData.get('name'),
    // ... other fields ...
    display_order: parseInt(formData.get('display_order')) || 999,
    is_active: formData.get('is_active') === 'on'
};
```

**After:**
```javascript
const data = {
    name: formData.get('name'),
    // ... other fields ...
    // display_order removed - backend auto-assigns!
    is_active: formData.get('is_active') === 'on'
};
```

#### 3. Badge Styling
**File:** `static/css/components/manager-settings.css:203-249`

```css
/* Priority Badge Container */
.rule-name-with-priority {
    display: flex;
    align-items: center;
    gap: 0.75rem;
    flex: 1;
}

/* Priority Badge Styling */
.priority-badge {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    min-width: 2.5rem;
    height: 2.5rem;
    padding: 0 0.5rem;
    border-radius: 0.5rem;
    font-size: 1.25rem;
    font-weight: 700;
    box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
}

/* Gold for 1st place */
.priority-1 {
    background: linear-gradient(135deg, #ffd700 0%, #ffed4e 100%);
    font-size: 1.5rem;
}

/* Silver for 2nd place */
.priority-2 {
    background: linear-gradient(135deg, #c0c0c0 0%, #e8e8e8 100%);
    font-size: 1.5rem;
}

/* Bronze for 3rd place */
.priority-3 {
    background: linear-gradient(135deg, #cd7f32 0%, #e5a868 100%);
    font-size: 1.5rem;
    color: white;
}

/* Gray for 4th+ */
.priority-badge:not(.priority-1):not(.priority-2):not(.priority-3) {
    background: linear-gradient(135deg, #6b7280 0%, #9ca3af 100%);
    color: white;
    font-size: 0.875rem;
}
```

---

## User Experience Flow

### Creating a New Rule

1. **Manager clicks** "Add New Rule" button
2. **Modal opens** with form fields:
   - Rule Name
   - Temperature Range (min/max)
   - Recommended Viscosity
   - Suggestion Text
   - Badge Color
   - Active checkbox
3. **Manager fills out** fields (no priority input!)
4. **Manager clicks** "Save Rule"
5. **Backend auto-assigns** priority: `(max + 10)`
6. **Page reloads** showing new rule with badge
7. **New rule appears** at bottom with next position badge

**Example:**
- Existing rules:  Cold, ˆ Standard,  Hot
- Create "Extreme Cold"
- Auto-assigned priority: 40 (after 10, 20, 30)
- Displays as: **4th** (gray badge)

### Viewing Rule Order

1. **Navigate to** `/tech/settings/viscosity/`
2. **See rules** in card grid, sorted by priority
3. **Visual badges** show evaluation order:
   ```
    Cold Weather        (Below 32ÂF)
   ˆ Standard Conditions (32-85ÂF)
    Hot Weather        (Above 85ÂF)
   4th Extreme Heat      (Above 100ÂF)
   ```

### Editing an Existing Rule

1. **Click "Edit"** on a rule card
2. **Modal opens** with populated fields
3. **No priority field** shown (can't change order via UI)
4. **Edit other fields** (name, temps, viscosity, etc.)
5. **Click "Save"**
6. **Rule maintains** same priority position
7. **Badge unchanged** unless rules were added/deleted

### Deleting a Rule

1. **Click "Delete"** on a rule card
2. **Confirm deletion**
3. **Rule removed** from database
4. **Remaining rules** maintain their priorities
5. **Visual positions** update automatically

**Example:**
- Before:  (10), ˆ (20),  (30), 4th (40)
- Delete ˆ (20)
- After:  (10), ˆ (30),  (40)
- Priorities unchanged, positions renumbered!

---

## Future Enhancements

### Phase 2: Drag-and-Drop Reordering (Planned)

**Goal:** Allow managers to visually reorder rules without manual priority editing

**Implementation Plan:**

1. **Frontend Library:** Use SortableJS or HTML5 drag-and-drop API
2. **Visual Feedback:** Show draggable handle icon (®®) on each card
3. **AJAX Endpoint:** `POST /tech/settings/api/viscosity/reorder/`
4. **Payload:** Send new order as array: `[{id: 3, order: 10}, {id: 1, order: 20}, ...]`
5. **Backend:** Batch update `display_order` values
6. **UI Update:** Reload page or update badges via JavaScript

**User Flow:**
1. Manager drags  3rd rule to 1st position
2. Card animates to new position
3. AJAX call updates database
4. Badges update:  becomes 

### Phase 3: Priority Presets (Consideration)

**Goal:** Provide quick priority assignment options for common scenarios

**Options:**
- "Highest Priority" - Insert at position 1 (shift others down)
- "Above [Rule Name]" - Insert between two existing rules
- "Below [Rule Name]" - Insert after a specific rule
- "Lowest Priority" - Add at end (current behavior)

**Tradeoffs:**
-  More control for power users
-  Adds complexity back
-  May confuse casual users
- **Decision:** Not implementing unless user feedback requests it

### Phase 4: Priority Groups (Future Consideration)

**Goal:** Allow multiple rules at same priority level (all evaluated together)

**Use Case:**
- Multiple overlapping temperature ranges
- Regional variations (same priority, different recommendations)

**Implementation:**
- Add `priority_group` field
- Rules in same group all checked, best match selected
- Complex logic, likely not needed for initial use case

---

## Troubleshooting

### Common Issues

#### Issue: New rule appears in wrong position

**Symptom:** Rule shows as 3rd but should be 4th

**Cause:** Browser cached old page before reload

**Solution:**
```javascript
// In manager_settings.js:150-153
setTimeout(() => {
    window.location.reload();  // Force page reload
}, 1000);
```

#### Issue: Gaps in priority numbers (10, 20, 40, 50)

**Symptom:** Missing priority 30 after deletion

**Cause:** Deletion removes rule but doesn't renumber others (by design!)

**Solution:** This is expected behavior. Gaps don't affect functionality.

**Manual Fix (if needed):**
```sql
-- Renumber all rules sequentially
UPDATE technician_portal_viscosityrecommendation
SET display_order = (ROW_NUMBER() OVER (ORDER BY display_order)) * 10;
```

#### Issue: Duplicate priorities after migration

**Symptom:** Two rules both show as  1st

**Cause:** Legacy data with manually set priorities

**Solution:**
```python
# In Django shell
from apps.technician_portal.models import ViscosityRecommendation

rules = ViscosityRecommendation.objects.order_by('display_order', 'id')
for idx, rule in enumerate(rules):
    rule.display_order = (idx + 1) * 10
    rule.save()
```

---

## API Reference

### GET /tech/settings/api/viscosity/<id>/

**Purpose:** Fetch rule details for editing

**Response:**
```json
{
  "success": true,
  "rule": {
    "id": 5,
    "name": "Cold Weather",
    "min_temperature": "",
    "max_temperature": "59.9",
    "recommended_viscosity": "Low",
    "suggestion_text": "Use low viscosity resin",
    "badge_color": "blue",
    "display_order": 10,
    "is_active": true
  }
}
```

### POST /tech/settings/api/viscosity/create/

**Purpose:** Create new rule with auto-assigned priority

**Request:**
```json
{
  "name": "Extreme Cold",
  "min_temperature": null,
  "max_temperature": 32.0,
  "recommended_viscosity": "Very Low",
  "suggestion_text": "Use very low viscosity",
  "badge_color": "blue",
  "is_active": true
}
```

**Response:**
```json
{
  "success": true,
  "message": "Viscosity rule created successfully",
  "rule": {
    "id": 6,
    "name": "Extreme Cold",
    "temp_range": " 32.0ÂF",
    "recommended_viscosity": "Very Low",
    "suggestion_text": "Use very low viscosity",
    "badge_color": "blue",
    "display_order": 40,  // Auto-assigned!
    "is_active": true
  }
}
```

### POST /tech/settings/api/viscosity/<id>/update/

**Purpose:** Update existing rule (priority unchanged)

**Request:** Same as create, but priority not in payload

**Response:** Updated rule data

### POST /tech/settings/api/viscosity/<id>/delete/

**Purpose:** Delete rule

**Response:**
```json
{
  "success": true,
  "message": "Viscosity rule \"Extreme Cold\" deleted successfully"
}
```

---

## Testing

### Automated Tests

**Test File:** Create `tests/manager_settings/test_auto_priority.py`

```python
from django.test import TestCase, Client
from apps.technician_portal.models import ViscosityRecommendation

class AutoPriorityTests(TestCase):
    def test_first_rule_gets_priority_10(self):
        """First rule should get priority 10"""
        rule = ViscosityRecommendation.objects.create(
            name="Test",
            recommended_viscosity="Low",
            suggestion_text="Test",
            badge_color="blue"
        )
        # Note: Must trigger via view, not direct create
        # Direct create uses model default (0)

    def test_sequential_increments(self):
        """Each new rule should be +10 from previous"""
        # Test via API calls
        client = Client()
        # ... create rules via POST ...
        # Assert: 10, 20, 30, 40

    def test_deletion_maintains_order(self):
        """Deleting middle rule shouldn't renumber others"""
        # Create: 10, 20, 30
        # Delete: 20
        # Assert: 10, 30 (not 10, 20)
```

### Manual Testing Checklist

- [ ] Create first rule  verify priority 10
- [ ] Create second rule  verify priority 20
- [ ] Create third rule  verify priority 30
- [ ] Delete second rule  verify first=10, third=30 (not renumbered)
- [ ] Create fourth rule  verify priority 40 (after gap)
- [ ] Verify badges:  ˆ  4th
- [ ] Edit rule  verify priority unchanged
- [ ] Verify evaluation order: lowest priority checked first

---

## References

### Related Documentation

- **User Guide:** `docs/user-guides/ADMIN_GUIDE.md#viscosity-rules`
- **Manager Settings:** `docs/development/MANAGER_SETTINGS_ROADMAP.md`
- **Model Reference:** `apps/technician_portal/models.py:704-841`
- **Changelog:** `docs/development/CHANGELOG.md` (search "Auto-Priority")

### Code Locations

| Component | File | Lines |
|-----------|------|-------|
| Auto-assignment | `views.py` | 2087-2127 |
| Position display | `views.py` | 2029-2060 |
| Ordinal suffix | `views.py` | 2063-2071 |
| Badge template | `viscosity_rules.html` | 34-43 |
| Badge styling | `manager-settings.css` | 203-249 |
| JavaScript | `manager_settings.js` | 32-57, 82-100, 112-121 |

---

## Changelog

| Date | Version | Changes |
|------|---------|---------|
| 2025-11-18 | 1.0.0 | Initial auto-priority implementation |
| | | - Removed manual priority field |
| | | - Added visual badges (ˆ) |
| | | - Implemented auto-assignment (+10 increments) |
| | | - Updated all documentation |

---

**Last Updated:** November 18, 2025
**Author:** RS Systems Development Team
**Status:**  Production Ready
