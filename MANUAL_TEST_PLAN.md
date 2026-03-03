# RS Systems Manual Test Plan
**Date:** March 2, 2026
**Scope:** All features in PR #43 (amelia → main) — untested work from ~Feb 15 - Mar 2
**Server:** `python manage.py runserver 0.0.0.0:8000`

---

## Pre-Test Setup

1. Pull latest `amelia` branch
2. Run migrations: `python manage.py migrate`
3. Create test accounts if needed:
   - **Owner account** (is_staff or tenant owner)
   - **Technician account** (linked to a Technician record)
   - **Customer account** (linked to a CustomerUser)
4. Ensure at least 1 customer with repairs exists

---

## 1. Password Reset Flow

| # | Step | Expected |
|---|------|----------|
| 1.1 | Go to login page, click "Forgot Password" | Reset form loads |
| 1.2 | Enter valid email, submit | "Email sent" confirmation |
| 1.3 | Check email for reset link | Email arrives from notifications@rockstarwindshield.repair |
| 1.4 | Click link, enter new password | Password changed, redirect to login |
| 1.5 | Login with new password | Success |
| 1.6 | Enter non-existent email | Should NOT reveal that email doesn't exist (security) |

---

## 2. Signup & Onboarding

| # | Step | Expected |
|---|------|----------|
| 2.1 | Go to `/saas/signup/` | Signup form renders |
| 2.2 | Fill form with valid data, submit | Account created, redirect to onboarding |
| 2.3 | Submit with missing required fields | Form re-renders with errors AND preserves entered data |
| 2.4 | Submit with duplicate email | Proper error message |
| 2.5 | Check for verification email | Email arrives with verification link |
| 2.6 | Click verification link | Email marked verified |
| 2.7 | Check branding says "RS Systems" (not Rockstar Windshield) | Correct branding throughout |

---

## 3. Terms of Service & Privacy Policy

| # | Step | Expected |
|---|------|----------|
| 3.1 | Go to `/saas/terms/` | Terms page renders |
| 3.2 | Go to `/saas/privacy/` | Privacy page renders |
| 3.3 | Check signup page links to both | Links work, not broken |

---

## 4. Owner Dashboard & Settings

| # | Step | Expected |
|---|------|----------|
| 4.1 | Login as owner, go to `/saas/owner/` | Dashboard loads |
| 4.2 | Check "Recent Activity" section | No template errors, shows recent repairs/events |
| 4.3 | Go to `/saas/owner/settings/` | Settings page loads with tabs |

---

## 5. Progressive Pricing

| # | Step | Expected |
|---|------|----------|
| 5.1 | Owner settings → find progressive pricing toggle | Toggle present |
| 5.2 | Enable progressive pricing at tenant level | Setting saves |
| 5.3 | Check individual customer → progressive pricing option | Per-customer toggle visible |
| 5.4 | Disable progressive pricing for one customer | That customer gets flat pricing |
| 5.5 | Create a repair for progressive-enabled customer | Price reflects progressive tiers |
| 5.6 | Create a repair for progressive-disabled customer | Price is flat rate |
| 5.7 | Check pricing preview updates correctly | Preview matches actual calculated price |
| 5.8 | Configure custom pricing tiers (if UI exists) | Tiers save and apply correctly |

---

## 6. Viscosity Rules

| # | Step | Expected |
|---|------|----------|
| 6.1 | Go to tech portal → Settings → Viscosity Rules | Page loads |
| 6.2 | Owner settings → find viscosity rules link | Link present under General tab |
| 6.3 | Create a new viscosity rule | Rule saves |
| 6.4 | Edit existing rule | Changes persist |
| 6.5 | Toggle rule active/inactive | Status updates |
| 6.6 | Delete a rule | Rule removed |
| 6.7 | Create a repair → check viscosity suggestion API | Returns correct suggestion based on rules |

---

## 7. Domain & Branding Update (rockstarwindshield.repair → rssystems.io)

| # | Step | Expected |
|---|------|----------|
| 7.1 | Search all visible pages for old domain references | No "rockstarwindshield.repair" in UI text |
| 7.2 | Check email templates/subjects | New domain in links |
| 7.3 | Check login page branding | Says "RS Systems" |
| 7.4 | Check technician login page | Updated branding |

---

## 8. Technician Dashboard — Today's Work Queue

| # | Step | Expected |
|---|------|----------|
| 8.1 | Login as technician, go to `/tech/` | Dashboard loads with Work Queue section |
| 8.2 | Assign repairs to this tech with today's date | Repairs appear in queue |
| 8.3 | Check queue shows repair details (customer, unit, status) | All info present |
| 8.4 | Update status from queue (if supported) | Status changes |
| 8.5 | No repairs assigned today | Queue shows empty state message |

---

## 9. Repair Creation — Wizard Form (KNOWN ISSUES)

**⚠️ Drake notes: wizard feels limiting, missing windshield location grid**

| # | Step | Expected |
|---|------|----------|
| 9.1 | Go to `/tech/repairs/create/` | Wizard form loads (6 steps: Customer, Vehicle, Damage, Photos, Pricing, Review) |
| 9.2 | Step through each wizard step | Steps advance, back button works |
| 9.3 | **Check Damage step for windshield grid** | **KNOWN MISSING — only has X/Y number inputs instead of interactive diagram** |
| 9.4 | Fill all fields, submit | Repair created successfully |
| 9.5 | Submit with missing required fields | Validation errors shown |
| 9.6 | Check if all repair fields are present (compare to legacy form) | Note any missing fields vs `/tech/repairs/<id>/update/` form |
| 9.7 | Check admin vs non-admin tech see correct fields | `is_admin` context properly controls visibility |
| 9.8 | Check customer types JSON loads for autocomplete | No JS console errors |

**Comparison test:**
| 9.9 | Open update form for an existing repair (`/tech/repairs/<id>/update/`) | Has full windshield diagram with tap-to-mark |
| 9.10 | Note ALL fields present on update form but missing from wizard | Document gaps |

---

## 10. Windshield Damage Location Diagram

| # | Step | Expected |
|---|------|----------|
| 10.1 | Edit an existing repair → Damage section | Interactive windshield diagram renders |
| 10.2 | Tap/click on windshield | Red dot appears at click location |
| 10.3 | Check hidden fields update | `damage_location_x` and `damage_location_y` populated |
| 10.4 | Click "Clear" | Dot removed, fields cleared |
| 10.5 | Save repair with location set | Values persist on reload |
| 10.6 | View repair detail | Location displayed (if shown) |

---

## 11. One-Click Approval/Deny Links

| # | Step | Expected |
|---|------|----------|
| 11.1 | Create a repair that triggers a notification to customer | Notification email sent |
| 11.2 | Check email contains Approve/Deny links | Links present with token-based URLs |
| 11.3 | Click Approve link (not logged in) | Repair approved WITHOUT requiring login |
| 11.4 | Check repair status changed to approved | Status updated in DB |
| 11.5 | Click same Approve link again | "Already used" message |
| 11.6 | Create another repair, click Deny link | Repair denied |
| 11.7 | Wait for token expiry (or manually expire) and click | "Expired" message |
| 11.8 | Go to `/app/quick-approve/<random-uuid>/` | 404 or "invalid token" (not a crash) |

---

## 12. Customer Portal — Invitation System

| # | Step | Expected |
|---|------|----------|
| 12.1 | Tech portal → Customer detail → Send invitation | Invitation form appears |
| 12.2 | Enter customer's email, send | Email sent with invitation link |
| 12.3 | Check invitation appears in customer detail page | Listed with status "Pending" |
| 12.4 | Resend invitation | New email sent |
| 12.5 | Cancel invitation | Status changes to cancelled |
| 12.6 | Open invitation link (`/app/invite/<token>/`) | Acceptance page loads |
| 12.7 | Accept invitation — new user | Account created, linked to customer |
| 12.8 | Accept invitation — existing user | User linked to customer |
| 12.9 | Use expired/cancelled invitation link | Error message (not crash) |

---

## 13. Customer Portal — Self-Service Team Management

| # | Step | Expected |
|---|------|----------|
| 13.1 | Login as customer, go to `/app/team/` | Team management page loads |
| 13.2 | Invite a team member (email) | Invitation sent |
| 13.3 | Check invitation listed | Shows pending status |
| 13.4 | Resend team invitation | Success |
| 13.5 | Cancel team invitation | Invitation cancelled |
| 13.6 | Accept team invite as new user | Account created, added to team |
| 13.7 | Check team member appears in list | Member visible |

---

## 14. Customer Portal — Outstanding Invoice Visibility

| # | Step | Expected |
|---|------|----------|
| 14.1 | Login as customer with outstanding invoices | Dashboard shows outstanding invoices |
| 14.2 | Check invoice amounts and dates | Correct |
| 14.3 | Customer with no outstanding invoices | No invoice section or "All paid" message |
| 14.4 | Click invoice to view detail | Detail page loads |

---

## 15. Customer Portal — Replacements

| # | Step | Expected |
|---|------|----------|
| 15.1 | Go to `/app/replacements/` | Replacement list loads |
| 15.2 | View a replacement detail | Detail page renders |
| 15.3 | Approve a pending replacement | Status changes to approved |
| 15.4 | Deny a replacement | Status changes to denied |

---

## 16. Replacement Management (Tech/Owner Side)

| # | Step | Expected |
|---|------|----------|
| 16.1 | Go to `/saas/tech/replacements/` | List page with filtering and pagination |
| 16.2 | Create new replacement | Form saves |
| 16.3 | Edit replacement | Changes persist |
| 16.4 | Update replacement status | Status changes |
| 16.5 | Complete a replacement → check repair count reset | Customer's repair count resets (for progressive pricing) |
| 16.6 | Check tax fields on replacement | Tax calculated if tax enabled |

---

## 17. Tax Rate Management

| # | Step | Expected |
|---|------|----------|
| 17.1 | Go to `/saas/owner/tax-rates/` | Tax rates page loads |
| 17.2 | Toggle tax on/off for tenant | Setting saves |
| 17.3 | Add a tax rate (state + county + city + special) | Rate saves, total auto-calculated |
| 17.4 | Edit a tax rate | Changes persist |
| 17.5 | Delete a tax rate | Rate removed |
| 17.6 | Create invoice with tax enabled | Tax line item appears on invoice |
| 17.7 | Create invoice with tax disabled | No tax on invoice |
| 17.8 | Verify check/cash payments include same tax as Stripe | Totals match |

---

## 18. Multi-Break / Batch Repairs

| # | Step | Expected |
|---|------|----------|
| 18.1 | Create a multi-break repair | Form works, batch created |
| 18.2 | Convert single repair to batch | Conversion succeeds (check tenant field set) |
| 18.3 | View batch detail (tech portal) | All repairs in batch listed |
| 18.4 | View batch detail (customer portal) | Customer sees batch |
| 18.5 | Approve/deny batch from customer portal | All repairs in batch updated |
| 18.6 | Start work on batch | Status updates |

---

## 19. Email Verification (Signup)

| # | Step | Expected |
|---|------|----------|
| 19.1 | Sign up new account | Verification email sent |
| 19.2 | Click verification link | Email confirmed |
| 19.3 | Try to verify with bad/expired token | Error message |

---

## 20. Portal Middleware (MessageFailure Fix)

| # | Step | Expected |
|---|------|----------|
| 20.1 | Navigate between portal pages rapidly | No MessageFailure crashes |
| 20.2 | Access portal page with expired session messages | Page loads normally |
| 20.3 | Check repair_date shows in API serializer | Field present in JSON responses |

---

## 21. Login System

| # | Step | Expected |
|---|------|----------|
| 21.1 | Login with username | Success |
| 21.2 | Login with email (case-insensitive) | Success |
| 21.3 | Login with wrong password | Error message |
| 21.4 | After login, redirected to correct portal (not login page loop) | Correct redirect |

---

## Smoke Test Checklist (Quick Pass)

Run through these quickly to catch obvious breakage:

- [ ] `/saas/signup/` loads
- [ ] `/saas/terms/` loads
- [ ] `/saas/privacy/` loads
- [ ] `/saas/owner/` loads (as owner)
- [ ] `/saas/owner/settings/` loads
- [ ] `/saas/owner/tax-rates/` loads
- [ ] `/saas/tech/replacements/` loads
- [ ] `/tech/` dashboard loads (as tech)
- [ ] `/tech/repairs/` list loads
- [ ] `/tech/repairs/create/` loads (wizard)
- [ ] `/tech/customers/` list loads
- [ ] `/tech/settings/` loads
- [ ] `/tech/settings/viscosity/` loads
- [ ] `/app/` dashboard loads (as customer)
- [ ] `/app/repairs/` loads
- [ ] `/app/replacements/` loads
- [ ] `/app/invoices/` loads
- [ ] `/app/team/` loads
- [ ] No 500 errors in any of the above

---

## Known Issues to Address

1. **Repair wizard missing windshield location grid** — wizard has raw X/Y number inputs; legacy/update form has the interactive diagram. Need to port the diagram into wizard Step 3 (Damage).
2. **Wizard may be missing fields** — compare create wizard vs update form for completeness.
3. **Multiple repair form templates** — `repair_wizard.html`, `repair_form.html`, `repair_form_legacy.html`, `repair_form_modern.html`, `repair_form_old.html.bak` — need cleanup.

---

*Test against local dev server. Mark each item PASS/FAIL/SKIP with notes.*
