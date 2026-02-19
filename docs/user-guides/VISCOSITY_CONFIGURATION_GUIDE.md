# Viscosity Recommendation Configuration Guide

## Overview
The system provides intelligent, real-time resin viscosity recommendations to technicians based on windshield temperature. These recommendations are fully configurable by managers through a modern, card-based interface in the technician portal.

## Accessing Configuration

### For Managers (Recommended)
1. **Login to Technician Portal**: Login with your manager account at `/tech/login/`
2. **Open User Menu**: Click your username in the top-right corner
3. **Click "Manager Settings"**: Select the sliders icon option from the dropdown
4. **Navigate to Viscosity Rules**: Click the "Viscosity Rules" card on the settings dashboard
5. **Manage Rules**: Use the card-based interface to view, add, edit, or delete rules

### For Administrators (Alternative)
1. **Login to Django Admin**: Navigate to `/admin/` and login with staff credentials
2. **Navigate to Viscosity Recommendations**: Click on "Viscosity recommendations" under the "TECHNICIAN_PORTAL" section
3. **View Rules**: Traditional Django admin list view interface

**Note**: Managers (users with `is_manager=True`) can only access the technician portal settings page. Staff users (administrators) have access to both interfaces.

## Understanding Viscosity Rules

Each rule consists of:
- **Name**: Descriptive name (e.g., "Cold Weather", "Standard Conditions")
- **Temperature Range**: Min/Max temperature thresholds in 헑
  - Leave `min_temperature` blank for "all temperatures below max"
  - Leave `max_temperature` blank for "all temperatures above min"
- **Recommended Viscosity**: The viscosity level to suggest (e.g., "Low", "Medium", "High")
- **Suggestion Text**: The message technicians will see
- **Badge Color**: Visual indicator color (blue, green, orange, red, yellow, purple)
- **Display Order**: Priority (lower number = higher priority when rules could overlap)
- **Active Status**: Whether the rule is currently in use

## Default Rules

The system comes with 3 default rules:

| Name | Temperature Range | Viscosity | Badge Color |
|------|------------------|-----------|-------------|
| Cold Weather |  59.9헑 | Low | Blue |
| Standard Conditions | 60.0헑 - 84.9헑 | Medium | Green |
| Hot Weather |  85.0헑 | High | Orange |

## Using the Manager Settings Interface

### Card-Based Interface Features
- **Visual Cards**: Each rule is displayed as an interactive card showing all key information
- **Toggle Switch**: Quickly enable/disable rules with one click
- **Badge Preview**: See exactly how the viscosity badge will appear to technicians
- **Modal Editing**: Click "Edit" to open a detailed form overlay
- **Drag-and-Drop**: Reorder rules by priority (coming soon)
- **Real-time Updates**: Changes take effect immediately without page refresh

### Adding a New Rule

1. Click **"Add New Rule"** button (green button in top-right)
2. Fill in the modal form:
   - **Basic Information**:
     - **Rule Name**: Give it a descriptive name (e.g., "Cold Weather")
     - **Priority**: Set display order (1 = highest priority)
   - **Temperature Range**:
     - **Minimum Temperature**: Lower bound in 헑 (or leave blank for "all temps below max")
     - **Maximum Temperature**: Upper bound in 헑 (or leave blank for "all temps above min")
   - **Recommendation**:
     - **Recommended Viscosity**: The viscosity level (e.g., "Low", "Medium", "High")
     - **Badge Color**: Choose visual color (blue, green, orange, red, yellow, purple)
     - **Suggestion Text**: Helpful message technicians will see
   - **Active**: Check to enable rule immediately
3. Click **"Save Rule"**
4. The new rule card will appear in the grid

### Editing Existing Rules (Manager Interface)

1. Find the rule card you want to edit
2. Click the **"Edit"** button on the card
3. The modal form will open with current values pre-filled
4. Modify any fields
5. Click **"Save Rule"**
6. Changes take effect immediately

**Quick Actions**:
- **Toggle Active/Inactive**: Use the switch in the card header to enable/disable without opening the modal
- **Delete**: Click the red "Delete" button and confirm

### Editing Rules (Django Admin)

**Quick Edit (In List View)**:
- **Display Order**: Click the number and type new value
- **Active Status**: Check/uncheck the checkbox
- Click **"Save"** at the bottom

**Full Edit**:
1. Click on the rule name
2. Modify any fields in the detailed form
3. Click **"Save"**

## Deleting Rules

### Manager Interface
1. Click the **red "Delete" button** on the rule card
2. Confirm deletion in the popup dialog
3. Rule is removed immediately

### Django Admin
1. Select rules using checkboxes
2. Choose "Delete selected viscosity recommendations" from the action dropdown
3. Click **"Go"**
4. Confirm deletion

## Best Practices

### Temperature Boundaries
- Avoid overlapping ranges (e.g., don't have one rule end at 60헑 and another start at 60헑)
- Use decimal precision for clean boundaries:
  - Rule 1: max = 59.9헑
  - Rule 2: min = 60.0헑

### Badge Colors
- **Blue**: Cold conditions
- **Green**: Optimal/normal conditions
- **Orange**: Warm/caution conditions
- **Red**: Critical/extreme conditions
- **Yellow**: Warning/borderline conditions
- **Purple**: Special cases

### Suggestion Text
- Be specific and actionable
- Example: "Low viscosity recommended for cold conditions" 
- Avoid: "Use this one" 

### Display Order
- Lower numbers have higher priority
- Important if temperature ranges could overlap
- Rule with order=1 will be checked before order=2

## How Technicians See Recommendations

When a technician enters a windshield temperature in the repair form:

1. **Real-time Update**: Suggestion appears automatically after 500ms
2. **Visual Badge**: Colored badge with icon shows recommended viscosity
3. **Helpful Text**: Your configured suggestion text provides guidance
4. **Optional Field**: Temperature is optional - suggestions only show when entered

### Example Display
```
Temperature: 72헑

  Medium viscosity recommended for    
    optimal conditions                   

```

## Troubleshooting

### Rule Not Appearing
- Check **Is Active** is enabled
- Verify temperature range includes the test value
- Check **Display Order** - higher priority rule may be matching first

### Wrong Rule Showing
- Review temperature boundaries for overlaps
- Check **Display Order** for rule priority
- Verify min/max temperature values are correct decimals

### No Recommendation Showing
- Ensure at least one active rule covers the temperature range
- Check that temperature field has a value
- Verify API endpoint is working: `/tech/api/viscosity-suggestion/?temperature=72`

## Management Command

To reset rules to defaults:
```bash
python manage.py setup_viscosity_rules --reset
```

 **Warning**: This will delete all existing rules and recreate the 3 defaults.

## Technical Notes

- **Database Model**: `ViscosityRecommendation` in `apps.technician_portal.models`
- **API Endpoint**: `/tech/api/viscosity-suggestion/`
- **Admin Class**: `ViscosityRecommendationAdmin` in `apps.technician_portal.admin`
- **Temperature Precision**: Uses `DecimalField` for accurate comparisons

## Support

For technical issues or questions:
- Check Django admin error messages
- Review server logs for API errors
- Contact system administrator if issues persist
