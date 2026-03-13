# Multi-Break Repair Entry - Quick Start Guide

**For Technicians**: How to create multiple repairs for the same unit in one session

---

## When to Use Multi-Break Entry

Use this feature when you discover **multiple breaks on the same unit** during a single inspection:

 **Use Multi-Break For:**
- Unit 1001 has 3 chips in different locations
- Single windshield with crack + star break + chip
- Multiple damage points discovered during lot walking
- Batch inspection where you find several breaks on one unit

 **Don't Use Multi-Break For:**
- Multiple different units (use regular repair entry for each)
- Single break on a unit (use standard Create Repair form)

---

## How to Access

1. Log in to Technician Portal: `https://yourdomain.com/tech/login/`
2. Navigate to: **Repairs  Multi-Break Entry**
3. Or visit directly: `/tech/repairs/create-multi-break/`

---

## Step-by-Step Instructions

### Step 1: Fill Base Information

All breaks share this information:

| Field | Description |
|-------|-------------|
| **Customer** | Select the customer (company name) |
| **Unit Number** | Enter the unit identifier (e.g., 1001, TRUCK-05) |
| **Repair Date** | Auto-filled with current time (adjust if needed) |

 **Tip**: The pricing preview will automatically appear after selecting customer and unit.

---

### Step 2: Add Each Break

Click the **"Add Break"** button to open the modal for each damage point:

#### Break Modal Fields:

**Damage Information:**
1. **Damage Type** (Required)
   - Select from dropdown: Chip, Crack, Star Break, Bull's Eye, etc.

2. **Drilled Before Repair** (Optional)
   - Check if windshield was drilled before repair
   - Important for quality tracking

**Technical Conditions:**
3. **Windshield Temperature** (Optional)
   - Enter temperature in °F
   - Ideal range: 60-95°F (best conditions: 75-95°F)
   - Example: "72.5"
   - If your shop owner has enabled viscosity recommendations, a colored suggestion badge will appear automatically as you type the temperature (e.g., "🟢 Medium viscosity — Ideal conditions")

4. **Resin Viscosity** (Optional)
   - Enter resin type/viscosity
   - Example: "Low(l)", "Medium(m)", "High(h)"
   - If viscosity recommendations are enabled, the suggested value will be shown — you can follow the suggestion or enter your own

**Photo Documentation:**
5. **Photo Before** (Optional)
   - Click to upload or use camera
   - Mobile: Tap to take photo directly
   - Supported: JPEG, PNG, HEIC (auto-converted)
   -  **Tip**: Can be added now or later when editing the repair

6. **Photo After** (Optional)
   - Upload repair completion photo
   - Recommended for quality assurance
   -  **Tip**: Often added after repair is completed

**Notes:**
7. **Notes** (Optional)
   - Add any specific details about this break
   - Example: "Small chip on driver side near wiper"

**Manager Price Override** (Managers Only):
8. **Override Price** (Optional, Manager Only)
   - Custom price for this break
   - Must provide override reason
   - Subject to your approval limit

9. **Override Reason** (Required if override set)
   - Explanation for custom pricing
   - Example: "Special customer discount"

Click **"Save Break"** when done.

---

### Step 3: Review Your Breaks

After saving, each break appears as a card showing:

- Break number (1, 2, 3...)
- Damage type
- Photo thumbnails
- Notes
- **Photo status warnings** (if missing):
  -  "Missing both photos" (orange badge)
  -  "Missing before photo" (orange badge)
  -  "Missing after photo" (orange badge)
- **Technical details** (if provided):
  -  Pre-drilled indicator
  -  Windshield temperature
  -  Resin viscosity
  -  Manager override (if applicable)

You can:
-  **Edit** any break (click Edit button) to add photos or update details
-  **Delete** a break if added by mistake

 **Tip**: Orange warning badges are reminders, not blockers. You can still submit without photos and add them later.

---

### Step 4: Review Pricing

The pricing preview shows:

```
Customer: Acme Corp [Custom Pricing]
Unit 1001: 3 breaks | $50.00 - $35.00

Break 1: $50.00 (Repair #1)
Break 2: $40.00 (Repair #2)
Break 3: $35.00 (Repair #3)

Total: $125.00
```

**How Pricing Works:**
- Each break increments the repair count for pricing
- Break 1 = priced as next repair for this unit
- Break 2 = priced as following repair
- Custom pricing (if enabled) applies automatically

---

### Step 5: Submit

Click **"Submit All Repairs (3)"** when ready.

 **What Happens:**
- All repairs created together (atomic transaction)
- Each break becomes a separate repair record
- All linked with same batch ID
- Customer sees them grouped for approval
- You're redirected to repair list filtered by this customer

---

## Important Notes

### Progressive Pricing

Each break in your batch counts as a separate repair for pricing:

| Scenario | Example |
|----------|---------|
| Unit has 0 repairs | Break 1: $50, Break 2: $40, Break 3: $35 |
| Unit has 2 repairs | Break 1: $35, Break 2: $30, Break 3: $25 |

### Customer Approval

- If customer has **auto-approval** enabled: All breaks approved automatically
- Otherwise: Customer must approve entire batch (all-or-nothing)
- Customer sees: "3 breaks found on Unit 1001"

### Photo Flexibility

- **Photos are optional** at submission time
- You can submit repairs without photos and add them later
- **Common workflow 1** (Pre-approval):
  1. Document damage found (add breaks with damage types)
  2. Take before photos (damage documentation)
  3. Submit for customer approval (PENDING status)
  4. After approval, perform repairs
  5. Edit repairs to add after photos
  6. Mark as completed
- **Common workflow 2** (Auto-approve):
  1. Perform repairs immediately
  2. Take both before/after photos
  3. Submit complete batch
  4. Repairs auto-approved (APPROVED status)
- Mobile devices: Use camera directly
- HEIC photos from iPhone: Automatically converted to JPEG
- Recommended: Take photos in good lighting
- **Warning badges**: Orange badges on break cards remind you which photos are missing

### Data Safety

- **LocalStorage autosave**: Your work is saved as you go
- **If you accidentally close the browser**: On return, you'll be asked if you want to restore
-  **Limitation**: Photos cannot be restored (browser security), you'll need to re-upload

### Transaction Safety

- All breaks submitted together as one transaction
- If any break fails, **none are created** (prevents partial batches)
- Database ensures data integrity

---

## Common Workflows

### Typical Lot Walking Inspection

1. Walk lot with tablet/phone
2. Find Unit 1001 has 3 damage points
3. Take photos of all 3 breaks
4. Open multi-break form
5. Select customer and Unit 1001
6. Add each break with its photos
7. Review pricing ($125 total)
8. Submit batch
9. Move to next unit

**Time saved**: ~5 minutes vs. creating 3 separate repair entries

---

### Large Windshield with Multiple Damage

1. Inspect windshield, find 5 breaks
2. Photograph each damage point
3. Enter batch with all 5 breaks
4. System calculates: $50 + $40 + $35 + $30 + $25 = $180
5. Customer approves entire batch at once
6. Complete all repairs together

---

## Troubleshooting

### "Missing required information" error

**For Batch Submission (Multi-Break Entry)**:
- Ensure customer, unit number, and repair date are filled
- Ensure at least one break is added
- Each break must have damage type
- Photos are OPTIONAL at batch submission time (can be added later)

**When Editing Individual Repairs (After Batch Created)**:
- Photos uploaded during batch creation are automatically associated
- You can complete repairs without re-uploading photos
- Form will recognize existing photos from batch submission

### Pricing preview not showing

- Check that customer is selected
- Check that unit number is entered
- Wait a moment for AJAX request to complete

### Photos not uploading

- Check file size (max typically 10MB per photo)
- Ensure file format is supported (JPEG, PNG, HEIC, WebP)
- Check internet connection
- Try compressing image if too large

### Browser refresh lost my work

- Check for restore prompt on page load
- Note: Photos cannot be auto-restored (re-upload required)
- Tip: Submit batches promptly to avoid data loss

---

## Best Practices

 **Do:**
- Take clear, well-lit photos
- Add descriptive notes for complex breaks
- Review pricing before submitting
- Use multi-break for efficiency

 **Don't:**
- Mix different units in one batch (one unit per batch)
- Skip photo documentation
- Leave browser tab open for hours (submit promptly)
- Use for single breaks (use standard form instead)

---

## Support

Questions? Contact your supervisor or system administrator.

**Feature Version**: 1.5
**Release Date**: November 8, 2025 (Latest fixes: November 14, 2025)
**Documentation**: `/docs/user-guides/MULTI_BREAK_QUICK_START.md`
