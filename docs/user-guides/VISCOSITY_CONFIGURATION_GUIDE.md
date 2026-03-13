# Viscosity Recommendations Configuration Guide

How to set up and manage temperature-based resin viscosity recommendations for your technicians.

## Table of Contents
- [What Are Viscosity Recommendations?](#what-are-viscosity-recommendations)
- [Who Can Configure This?](#who-can-configure-this)
- [Quick Setup via Configure Your Shop](#quick-setup-via-configure-your-shop)
- [Default Rules](#default-rules)
- [Manual Editing via Settings](#manual-editing-via-settings)
- [Managing Rules](#managing-rules)
- [What Technicians See](#what-technicians-see)
- [Troubleshooting](#troubleshooting)

---

## What Are Viscosity Recommendations?

When technicians log a repair and enter the windshield temperature, RS Systems can automatically suggest the right resin viscosity. This helps ensure:
- Proper resin selection for the conditions
- Consistent technique across your team
- Fewer callbacks from poor resin choice

The recommendation appears as a colored badge next to the temperature field during repair entry:

```
Temperature: 85°F

  🟢 Medium viscosity — Ideal conditions.
     Standard cure time and best penetration.
```

This feature is **optional**. You can enable it, disable it, or customize the rules entirely.

---

## Who Can Configure This?

**Shop owners** and **managers** can configure viscosity recommendations.

- **Owners**: Full access via "Configure Your Shop" (`/owner/setup/`) and the direct settings page (`/tech/settings/viscosity/`)
- **Managers** (technicians with the manager flag): Access via the Manager Settings portal (`/tech/settings/viscosity/`)
- **Regular technicians**: Can view recommendations during repairs, but cannot change the rules

> **Previously**: An earlier version of the system incorrectly required the `@technician_required` permission for the viscosity settings page, which locked out some owners. This bug has been fixed — owners and managers can now access the settings page without needing a technician profile.

---

## Quick Setup via Configure Your Shop

The easiest way to enable viscosity recommendations is through the **Configure Your Shop** page:

```
1. Go to /owner/setup/
   (Or: Owner Dashboard → "Configure Your Shop")

2. Scroll to the "Viscosity Recommendations" section
   (Section 5 of 6 in the setup accordion)

3. Check "Enable viscosity recommendations"

4. Click "Save Viscosity Settings"
```

**What happens on first enable**:
- If you've never set up viscosity rules before, the system **automatically creates 5 default rules** covering the full temperature range
- These defaults are immediately active for your technicians
- You can customize them at any time

**If you had existing rules** that were previously disabled, enabling this will re-activate them without recreating them.

**To disable**:
- Uncheck "Enable viscosity recommendations" and save
- Your rules are preserved but hidden from technicians until you re-enable

The setup page also shows a preview of your current rules so you can confirm everything looks right before leaving the page.

---

## Default Rules

When viscosity recommendations are enabled for the first time, five rules are automatically created:

| Rule Name | Temperature Range | Recommended Viscosity | Badge Color |
|-----------|------------------|----------------------|-------------|
| **Cold Glass** | Below 60°F | Low | Blue |
| **Cool Glass** | 60°F – 74.9°F | Low-Medium | Green |
| **Ideal Conditions** | 75°F – 95°F | Medium | Green |
| **Warm Glass** | 95.1°F – 105°F | High | Orange |
| **Hot Glass — Cool First** | Above 105°F | Cool Glass First | Red |

**Default suggestion text**:

- **Cold Glass**: "Use low viscosity resin. Allow extra cure time in cold conditions. Consider warming the glass with a heat gun before injection for best results."
- **Cool Glass**: "Low to medium viscosity resin. Standard injection pressure. Good conditions for most repairs."
- **Ideal Conditions**: "Medium viscosity resin. Ideal repair conditions — standard cure time and best penetration."
- **Warm Glass**: "Use high viscosity resin. Work quickly — resin cures faster in heat. Shade the repair area if possible."
- **Hot Glass — Cool First**: "Glass is too hot for optimal repair. Cool the windshield first — park in shade, run A/C, or use cooling spray. Once below 105°F, use high viscosity resin."

These defaults work well for most shops. You can edit any rule to match your preferred resin brands or technique.

---

## Manual Editing via Settings

For fine-grained control, you can edit rules individually at:

**URL**: `/tech/settings/viscosity/`

This page is accessible to owners and managers. It shows all your rules as cards with full edit/delete controls.

### Getting There

- **From Owner Dashboard**: Settings → Manager Settings → Viscosity Rules
- **From Configure Your Shop** (`/owner/setup/`): The viscosity section includes a link: "Edit rules directly →"
- **Direct URL**: `https://[your-domain]/tech/settings/viscosity/`

---

## Managing Rules

### Adding a New Rule

1. Click **"Add New Rule"** (green button at the top)
2. Fill in the modal form:

| Field | Description |
|-------|-------------|
| **Rule Name** | Descriptive name (e.g., "Cold Weather", "Summer Heat") |
| **Min Temperature** | Lowest temperature this rule applies to (leave blank for no minimum) |
| **Max Temperature** | Highest temperature (leave blank for no maximum) |
| **Recommended Viscosity** | What technicians should use (e.g., "Low", "Medium", "High") |
| **Suggestion Text** | The message shown to technicians |
| **Badge Color** | Blue, Green, Orange, Red, Yellow, or Purple |
| **Display Order** | Lower numbers show first in lists |
| **Active** | Check to enable; uncheck to hide without deleting |

3. Click **"Save Rule"**

### Editing an Existing Rule

1. Find the rule card
2. Click **"Edit"**
3. Modify fields in the modal
4. Click **"Save Rule"**

### Enabling/Disabling a Rule

Each rule card has an **Active** toggle switch. Toggle it to enable or disable that specific rule without deleting it.

### Deleting a Rule

Click the red **"Delete"** button on the rule card and confirm. Deleted rules cannot be recovered — if you might want it back, disable it instead.

### Tips for Good Rules

- **Don't overlap temperature ranges** — if 72°F matches two rules, the one with the lower display order wins
- **Cover the full range** — leave the lowest rule's minimum blank and the highest rule's maximum blank so every temperature gets a suggestion
- **Keep suggestion text short** — technicians read this quickly in the field; 1–2 sentences is ideal
- **Use badge colors consistently** — green for good conditions, orange for caution, red for stop/act first, blue for cold

---

## What Technicians See

Viscosity suggestions appear automatically when technicians enter a windshield temperature during repair creation or editing.

**In the repair form**:
```
Windshield Temperature: [__72__] °F

 🟢 Ideal Conditions
 Medium viscosity — Ideal repair conditions.
 Standard cure time and best penetration.
```

The suggestion updates in real time as the technician types a temperature — no page reload needed.

If no temperature is entered, no suggestion appears. If a temperature is entered but no rule matches, no suggestion appears (the field still works fine).

Technicians **cannot** change the rules from the repair form — they can only see the recommendation and decide whether to follow it.

---

## Troubleshooting

### "I enabled it but technicians don't see suggestions"

- Check that at least one rule is **active** (toggle switch is on)
- Check that the temperature the technician entered falls within a rule's range
- Make sure temperature ranges don't have a gap that the entered temperature falls into

### "The /tech/settings/viscosity/ page says permission denied"

- Ensure your account has owner or manager access
- Owners: Make sure you're logged in with your owner account (the one associated with the shop's Tenant)
- Managers: Your technician profile must have `is_manager` checked — ask your shop owner to enable it
- If you're an owner and still blocked, contact RS Systems support at contact@rssystems.io

### "I want to reset to defaults"

There's no one-click reset, but you can:
1. Delete all existing rules
2. Disable viscosity, then re-enable it from `/owner/setup/`
3. The system will re-create the 5 default rules on enable

### "A technician is getting the wrong suggestion"

- Check for overlapping temperature ranges in your rules
- Verify the rule with the correct range is active
- Check the display order — if two rules match, the lower display order number wins

---

**Last Updated**: March 13, 2026
**For**: RS Systems v2.4
**Target Users**: Shop Owners and Managers
