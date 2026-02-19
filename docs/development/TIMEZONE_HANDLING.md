# Timezone Handling in RS Systems

## Overview

The RS Systems application is designed to support technicians and managers working across multiple timezones. This document outlines the timezone handling strategy implemented throughout the application.

## Architecture

### Server-Side Timezone Configuration

**Django Settings** (`rs_systems/settings.py`):
```python
TIME_ZONE = os.environ.get('TIME_ZONE', 'America/Chicago')
USE_TZ = True  # Enable timezone-aware datetime objects
```

- All datetime objects stored in the database are in **UTC**
- Django automatically converts UTC to the configured `TIME_ZONE` when rendering templates
- Server timezone can be configured via `TIME_ZONE` environment variable

### Client-Side Timezone Detection

For forms that collect datetime information (repairs, scheduling, etc.), the application uses **JavaScript-based timezone detection** to ensure users see their local time regardless of server location.

## Implementation Pattern

### Problem

When using HTML5 `datetime-local` inputs:
- The input expects and displays time in the **user's browser timezone**
- Server-side form initialization using `timezone.now()` produces **UTC time**
- Converting to server timezone (`timezone.localtime()`) only works if all users are in the same timezone as the server

### Solution: JavaScript Initialization

**Best Practice**: Initialize `datetime-local` inputs with JavaScript using the browser's local time.

**Example** (`static/js/repair_form.js:40-54`):
```javascript
// Set repair date to current time in user's local timezone
const repairDateInput = document.getElementById('id_repair_date');
if (repairDateInput && !repairDateInput.value) {
    const now = new Date();
    const year = now.getFullYear();
    const month = String(now.getMonth() + 1).padStart(2, '0');
    const day = String(now.getDate()).padStart(2, '0');
    const hours = String(now.getHours()).padStart(2, '0');
    const minutes = String(now.getMinutes()).padStart(2, '0');
    const dateTimeString = `${year}-${month}-${day}T${hours}:${minutes}`;
    repairDateInput.value = dateTimeString;
}
```

**Why This Works**:
- JavaScript `Date()` object uses the browser's local timezone
- Users in Pacific time see 9:00 AM PT
- Users in Eastern time see 12:00 PM ET (same moment, different display)
- Server receives the datetime and Django converts it to UTC for storage

### When Data is Submitted

1. **Browser**: User sees and enters `2025-11-19 21:30` (their local time)
2. **Form Submission**: Browser sends datetime as-is
3. **Django Backend**: Interprets datetime in `USE_TZ=True` context, converts to UTC
4. **Database**: Stores `2025-11-20 03:30:00+00:00` (UTC)
5. **Display**: Django converts back to user's timezone when rendering

## Current Implementation Status

### Forms with Timezone-Aware Initialization

 **Repair Form** (`templates/technician_portal/repair_form.html` + `static/js/repair_form.js`)
- Uses JavaScript initialization for `repair_date` field
- Works correctly for technicians in any timezone

 **Multi-Break Repair Form** (`static/js/multi_break.js`)
- Already implemented with JavaScript initialization
- Reference implementation for other forms

### Forms Requiring Updates

If adding new datetime fields to other forms, follow this pattern:

1. **Add JavaScript initialization** similar to repair_form.js
2. **Avoid server-side `widget.attrs['value']`** for new forms (use JavaScript instead)
3. **Test with multiple timezones** using browser DevTools timezone override

## Testing Timezone Behavior

### Chrome DevTools Timezone Override

1. Open Chrome DevTools (F12)
2. Click 3-dot menu  More Tools  Sensors
3. Set Location to a different timezone (e.g., "Tokyo" for JST)
4. Refresh the page
5. Verify datetime fields show correct local time

### Test Checklist

- [ ] New repair form shows current local time
- [ ] Multi-break form shows current local time
- [ ] Submitted repairs display correct time in technician's timezone
- [ ] Repairs created in one timezone display correctly when viewed from another timezone
- [ ] Existing repair editing preserves original timestamp

## Multi-Location Deployment

### Current Configuration

**Server Location**: AWS US East (UTC-5/UTC-4 depending on DST)
**Configured Timezone**: `America/Chicago` (UTC-6/UTC-5)
**Supported User Locations**: Any timezone (via JavaScript detection)

### Adding Support for Multiple Shop Locations

The current architecture already supports technicians working from different timezones. No additional configuration needed.

**Future Enhancement Ideas**:

1. **User Profile Timezone** (Phase 2+):
   - Add `timezone` field to `Technician` and `CustomerUser` models
   - Store user's preferred timezone
   - Use for email notifications, reports, and scheduled tasks

2. **Automatic Timezone Detection** (Phase 2+):
   - Detect timezone via JavaScript on first login: `Intl.DateTimeFormat().resolvedOptions().timeZone`
   - Store in user session or profile
   - Use for server-side datetime formatting

3. **Shop-Specific Timezones** (Phase 3+):
   - Add `timezone` field to a `Shop` or `Location` model
   - Associate technicians with specific shops
   - Use shop timezone for scheduling and reporting

## Migration Notes

### Existing Forms Updated (November 2025)

**Repair Form** (`apps/technician_portal/forms.py:194-208`):
- Removed duplicate `initial` assignment (was causing double value attributes)
- Kept `timezone.localtime()` conversion as fallback for non-JavaScript browsers
- Added JavaScript initialization as primary method

**Multi-Break Form**:
- Already using JavaScript initialization correctly
- No changes needed

### Backward Compatibility

The implementation maintains backward compatibility:
- JavaScript initialization only runs if field is empty (`if (!repairDateInput.value)`)
- Server-side initialization serves as fallback for browsers with JavaScript disabled
- Existing repairs continue to display correctly

## Best Practices Summary

1.  **DO**: Use JavaScript to initialize `datetime-local` inputs with browser's local time
2.  **DO**: Store all datetimes in UTC in the database
3.  **DO**: Use Django's `timezone.localtime()` when displaying datetimes in templates
4.  **DON'T**: Set `widget.attrs['value']` with server timezone (assumes all users in same timezone)
5.  **DON'T**: Use naive (non-timezone-aware) datetime objects
6.  **DO**: Test with multiple timezones using browser DevTools

## References

- Django Timezone Documentation: https://docs.djangoproject.com/en/4.2/topics/i18n/timezones/
- MDN datetime-local: https://developer.mozilla.org/en-US/docs/Web/HTML/Element/input/datetime-local
- JavaScript Date Timezone: https://developer.mozilla.org/en-US/docs/Web/JavaScript/Reference/Global_Objects/Date

---

**Last Updated**: November 2025
**Related Files**:
- `static/js/repair_form.js` (repair date initialization)
- `static/js/multi_break.js` (multi-break date initialization)
- `apps/technician_portal/forms.py` (form field configuration)
- `rs_systems/settings.py` (timezone configuration)
