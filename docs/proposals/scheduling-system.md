# Proposal: Scheduling & Appointment System

**Author:** Amelia  
**Date:** 2026-04-01  
**Status:** Draft — awaiting Drake's review

---

## Problem

RS Systems tracks repairs after they happen, but has no concept of *when* they'll happen. Right now:

- Fleet managers can't say "our trucks will be at the yard Tuesday morning"
- Techs can't see their day's schedule — they check texts/calls
- Walk-in / retail customers have no way to book an appointment
- Shop owners have no visibility into tomorrow's workload vs capacity

The repair queue shows what needs doing, but not when. For fleet accounts this is manageable (the tech just shows up). For retail customers and growing shops with multiple techs, the lack of scheduling becomes a real bottleneck.

## Solution: Scheduling Layer

Add scheduling as a thin layer on top of the existing repair queue — not a replacement. A repair can optionally have a scheduled time window. This integrates with every existing workflow without breaking anything.

---

## Phase 1: Fleet Scheduling (2 weeks)

The biggest immediate value. Fleet managers tell you when trucks are available.

### Customer Portal — "Schedule Availability"
- Fleet customer can set **preferred date/time windows** per repair or batch
- Options: "Morning (7am-12pm)", "Afternoon (12pm-5pm)", "All Day", or specific time
- Available on: repair request form, repair detail page, batch detail page
- Simple date picker + time window selector — not a full calendar

### Technician Portal — "My Schedule"
- New dashboard tab: **Today's Schedule** 
- Shows scheduled repairs sorted by time, grouped by location/customer
- Color-coded: overdue (red), upcoming (yellow), unscheduled (gray)
- Tech can drag to reorder or tap to reschedule
- Unscheduled repairs appear in a separate "Unscheduled" section

### Owner Portal — "Schedule Overview"
- Calendar view showing all techs' scheduled work
- Daily/weekly toggle
- See gaps, overlaps, overloaded days at a glance
- Filter by tech, customer, status

### Data Model

```python
# New fields on Repair / GlassService (the abstract base)
scheduled_date = models.DateField(null=True, blank=True, db_index=True)
scheduled_time_window = models.CharField(
    max_length=20, null=True, blank=True,
    choices=[
        ('MORNING', 'Morning (7am-12pm)'),
        ('AFTERNOON', 'Afternoon (12pm-5pm)'),
        ('ALL_DAY', 'All Day'),
        ('SPECIFIC', 'Specific Time'),
    ]
)
scheduled_time = models.TimeField(null=True, blank=True)  # Only if SPECIFIC
scheduled_by = models.ForeignKey(
    'auth.User', null=True, blank=True, on_delete=models.SET_NULL,
    related_name='scheduled_%(class)ss'
)
scheduled_at = models.DateTimeField(null=True, blank=True)  # When the scheduling happened

# New model for tech availability / blocked time
class TechnicianScheduleBlock(TenantModel):
    technician = models.ForeignKey(Technician, on_delete=models.CASCADE)
    date = models.DateField(db_index=True)
    start_time = models.TimeField()
    end_time = models.TimeField()
    block_type = models.CharField(max_length=20, choices=[
        ('UNAVAILABLE', 'Unavailable'),
        ('LUNCH', 'Lunch Break'),
        ('DRIVE_TIME', 'Drive Time'),
        ('OTHER', 'Other'),
    ])
    notes = models.TextField(blank=True)
```

### Queue Status Integration
- `REQUESTED` → customer can set preferred date/time
- `APPROVED` → tech/owner can confirm or adjust the schedule
- `SCHEDULED` ← **new status** (between APPROVED and IN_PROGRESS)
- `IN_PROGRESS` → tech started the work
- `COMPLETED` → done

The new `SCHEDULED` status means: approved, assigned, and has a confirmed date/time.

### Notifications
- Customer gets notified when their preferred time is confirmed or adjusted
- Tech gets morning summary: "You have 4 repairs scheduled today"
- Owner gets daily capacity alert if a tech is overbooked

---

## Phase 2: Retail / Walk-in Booking (2 weeks)

Extend scheduling to non-fleet customers — people who found you on Google and want to book an appointment.

### Public Booking Page
- Each shop gets a public booking URL: `https://rssystems.io/book/<tenant-slug>/`
- Shows available time slots based on tech availability
- Customer fills out: name, phone, vehicle info, damage description, preferred time
- Optional: photo upload of the damage
- Creates a `REQUESTED` repair with scheduling info pre-filled

### Integration with Website Widget
- The existing website widget proposal gets a "Book Appointment" mode
- Same embeddable JS, but renders a scheduling form instead of just a quote form
- Feeds into the same booking pipeline

### Smart Availability
- System calculates available slots based on:
  - Number of active techs
  - Existing scheduled repairs
  - Tech schedule blocks (lunch, drive time, days off)
  - Configurable slots per tech per day (owner setting)
- Prevents double-booking
- Shows "limited availability" vs "wide open" indicators

### Pricing Preview
- Based on damage type selected, show estimated price range
- Uses the shop's existing pricing tiers (volume discounts for fleet, standard for retail)
- "Starting at $45" style — not a binding quote
- Links to the shop's warranty policy

---

## Phase 3: AI Chat Scheduling — MCP Integration (4 weeks)

Natural language scheduling via chat. This is the ambitious one.

### The Vision
A customer (fleet or retail) can text/chat the shop and say:
> "I have a truck with a star break on the passenger side. Can someone come out Thursday morning?"

And the system:
1. Identifies damage type (star break)
2. Checks Thursday morning availability
3. Provides pricing estimate ($45 for star break repair)
4. Creates the repair request with scheduling
5. Confirms with the customer
6. Notifies the assigned tech

### Architecture: MCP (Model Context Protocol)

RS Systems exposes an MCP server that any AI chat client can connect to.

```
Customer ←→ Chat Interface ←→ MCP Client ←→ RS Systems MCP Server
                                                    ↓
                                              Django Backend
                                              (repairs, scheduling,
                                               pricing, availability)
```

**MCP Tools exposed:**
- `check_availability(date, time_window, tenant)` → available slots
- `get_pricing(damage_type, tenant)` → price estimate
- `create_appointment(customer_info, damage_info, schedule, tenant)` → repair request
- `check_appointment_status(repair_id)` → current status
- `reschedule_appointment(repair_id, new_date, new_time)` → update
- `cancel_appointment(repair_id)` → cancel with reason
- `get_warranty_info(tenant)` → warranty policy summary

**Chat Interfaces (in order of priority):**
1. **SMS/Text** — via Twilio or similar. Most accessible for retail customers
2. **Website chat widget** — embedded on shop's website
3. **WhatsApp Business** — huge for fleet managers
4. **Technician chat** — techs can schedule via natural language too ("schedule the EOS truck for tomorrow at 9")

### Tech Chat Use Cases
- "What's on my schedule today?"
- "Move the Penske truck to 2pm"
- "Block off 12-1 for lunch"
- "How many repairs did I do this week?"
- "What's the warranty on repair #247?"

### Customer Chat Use Cases
- "I need a windshield repair"
- "When are you available this week?"
- "How much does it cost to fix a long crack?"
- "Can you come to my office at 123 Main St?"
- "I need to reschedule my Thursday appointment"

### Fleet Manager Chat Use Cases
- "We have 3 trucks at the Conway yard ready for inspection"
- "What's the status on unit 4872?"
- "Can you send someone tomorrow morning? We have 5 units"
- "What's our invoice total for March?"

---

## Integration Points

### Existing System Touchpoints
| Feature | Integration |
|---------|------------|
| Repair queue | `scheduled_date` + `scheduled_time_window` fields on Repair |
| Customer portal | "Schedule" button on repair detail, calendar view |
| Tech portal | "My Schedule" tab, daily view |
| Owner dashboard | Capacity metrics, schedule overview |
| Notifications | Schedule confirmations, reminders, changes |
| Invoice system | No change — invoicing stays post-completion |
| Warranty system | No change — warranty tracks completed repairs |
| Batch repairs | Schedule applies to entire batch (one visit) |
| Website widget | "Book Appointment" mode |
| Review requests | Trigger after completed scheduled appointment |

### New Notifications
- **Customer:** "Your repair is scheduled for Tuesday, April 8 (Morning). Your technician is Drake."
- **Customer:** "Reminder: Your windshield repair is tomorrow at 9am."
- **Tech:** "Morning summary: 4 repairs today. First: EOS Trucking at 8am."
- **Owner:** "⚠️ Drake has 7 repairs scheduled for Thursday — consider reassigning."

---

## Scope & Risk

### What This Is NOT
- Not a full calendar app (Google Calendar exists)
- Not a dispatch/routing system (that's a separate product)
- Not real-time GPS tracking
- Not a CRM (we handle leads through the website widget)

### Risk Mitigation
- **Phase 1 is standalone** — fleet scheduling works without Phase 2 or 3
- **Phase 2 builds on Phase 1** — same data model, just adds public access
- **Phase 3 is optional** — MCP chat is a "wow factor" differentiator, not a requirement
- **No existing workflows break** — scheduling fields are all nullable
- **Migration is zero-risk** — all new fields are optional

### Competitive Advantage
Most glass shop software has zero scheduling. The ones that do are clunky calendar UIs bolted on. Natural language booking via text would be a genuine first in the industry.

---

## Estimated Timeline

| Phase | Scope | Effort | Depends On |
|-------|-------|--------|------------|
| Phase 1 | Fleet scheduling + tech schedule + owner overview | 2 weeks | Nothing |
| Phase 2 | Retail booking + public page + smart availability | 2 weeks | Phase 1 |
| Phase 3 | MCP server + chat interfaces | 4 weeks | Phase 1 + 2 |

**Total: 8 weeks** for the full vision. Phase 1 alone delivers immediate value.

---

## Open Questions for Drake

1. **Do fleet customers actually want to schedule?** Or do they just call/text you and say "trucks are ready"? If the current flow works for fleet, Phase 1 could focus on retail booking instead.
2. **SMS provider preference?** Twilio is the obvious choice for Phase 3, but there's also MessageBird, Vonage, etc. Cost matters.
3. **How many retail customers do you get now?** If it's mostly fleet, Phase 2 might be lower priority.
4. **MCP timeline** — Phase 3 is the most ambitious. Worth building, but should we stabilize Phases 1-2 first and let the scheduling data accumulate before adding AI on top?
5. **Google Calendar sync?** Some techs might want their RS Systems schedule to show up in Google Calendar. Easy to add as a Phase 2 add-on (iCal feed).
