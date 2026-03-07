# Retest All Bug Fixes — BUG-001 through BUG-037

**Date:** March 7, 2026
**Branch:** `autonomous-work`
**Server:** `python manage.py runserver 0.0.0.0:8001`

Mark each: ✅ PASS | ❌ FAIL | ⏭️ SKIP

You'll need:
- **Shop A** owner account (existing shop with customers/repairs)
- **Shop B** owner account (separate tenant)
- **Tech account** under Shop A
- **Expired trial account** (set `trial_end` to past date in admin)

---

## 🚨 CRITICAL — Security / Multi-Tenant

### BUG-001: Cross-tenant customer leak on repair form
| # | Step | Expected | Result |
|---|------|----------|--------|
| 1 | Log in as Shop B owner | Dashboard loads | |
| 2 | Go to create repair form | Form loads | |
| 3 | Check customer dropdown | Only Shop B customers — NO Shop A customers | |
| 4 | Check technician dropdown | Only Shop B technicians | |

### BUG-002: Trial/subscription enforcement
| # | Step | Expected | Result |
|---|------|----------|--------|
| 1 | Log in as expired trial user | Redirected to `/pricing/` | |
| 2 | Try to access `/tech/repairs/create/` directly | Blocked — redirected to `/pricing/` | |
| 3 | Try to access `/owner/settings/` directly | Blocked — redirected to `/pricing/` | |
| 4 | Try API call (e.g. `/api/v1/customers/`) | Returns 402 JSON with upgrade_url | |

### BUG-003: Cross-tenant tax leak
| # | Step | Expected | Result |
|---|------|----------|--------|
| 1 | Log in as Shop B (new shop, never configured tax) | Dashboard loads | |
| 2 | Go to tax settings | Tax should be DISABLED by default | |
| 3 | No tax rates from Shop A should appear | Empty tax rate list | |

---

## 🔴 HIGH — Broken Functionality

### BUG-004: Signup crash (make_random_password)
| # | Step | Expected | Result |
|---|------|----------|--------|
| 1 | Go to `/saas/signup/` | Form loads | |
| 2 | Fill out signup, check "add myself as technician" | | |
| 3 | Submit | Account created — no error | |

### BUG-005: Self-add as tech requires name fields
| # | Step | Expected | Result |
|---|------|----------|--------|
| 1 | During signup, check "add myself as technician" | | |
| 2 | Leave technician name fields empty | | |
| 3 | Submit | Should succeed — uses owner's name automatically | |

### BUG-006: "Skip for now" button broken
| # | Step | Expected | Result |
|---|------|----------|--------|
| 1 | Sign up new account, reach onboarding | | |
| 2 | On "add first customer" step, click "Skip for now" | Proceeds to next step or dashboard — no validation error | |

### BUG-007: Change primary tech to owner returns 403
| # | Step | Expected | Result |
|---|------|----------|--------|
| 1 | Log in as owner | | |
| 2 | Go to `/tech/customers/` → pick a customer | Customer detail loads | |
| 3 | Change primary technician to the owner | Saves successfully — no 403 | |

### BUG-008: Password reset success for non-existent email
| # | Step | Expected | Result |
|---|------|----------|--------|
| 1 | Go to forgot password page | | |
| 2 | Enter a bogus email like `nobody@fake.com` | | |
| 3 | Submit | Message says "If an account exists..." (not "email is on its way") | |

---

## 🟠 MEDIUM — UX / Logic

### BUG-009: Progressive pricing assumed for all shops
| # | Step | Expected | Result |
|---|------|----------|--------|
| 1 | Log in as new shop with default pricing | | |
| 2 | Go to create repair form | Warning banner about default pricing visible | |
| 3 | Banner links to settings | Link works | |

### BUG-010: No setup guidance for new users
| # | Step | Expected | Result |
|---|------|----------|--------|
| 1 | Log in as new shop owner (hasn't configured anything) | | |
| 2 | Check dashboard | Setup checklist visible (business info, pricing, tax, customer, tech) | |
| 3 | Complete a checklist item (e.g. add business info) | That item disappears from checklist | |
| 4 | Complete all items | Checklist disappears entirely | |

### BUG-011: Viscosity rank badges confusing
| # | Step | Expected | Result |
|---|------|----------|--------|
| 1 | Go to viscosity rules page | | |
| 2 | Check rule numbering | Shows `#1`, `#2`, `#3` — not medal emojis | |
| 3 | Hover over rank | Tooltip explains "rules checked top to bottom" | |

### BUG-012: Viscosity settings page confusing
| # | Step | Expected | Result |
|---|------|----------|--------|
| 1 | Go to viscosity rules page | | |
| 2 | Check top of page | Explanation box present describing what viscosity rules do | |
| 3 | Explanation includes example | Shows how temperature → viscosity matching works | |

### BUG-013: Viscosity not showing on create form
| # | Step | Expected | Result |
|---|------|----------|--------|
| 1 | Go to create repair form | | |
| 2 | Enter a temperature value | Viscosity suggestion appears (if rules configured) | |
| 3 | Go to edit repair form for existing repair | | |
| 4 | Change temperature | Viscosity suggestion appears | |
| 5 | Suggestion doesn't overwrite existing viscosity value on edit | Existing value preserved | |

### BUG-014: Real customer names as placeholders
| # | Step | Expected | Result |
|---|------|----------|--------|
| 1 | Go to add customer form | | |
| 2 | Check placeholder text in name field | Says "Acme Trucking" or similar — NOT "EOS Trucking" or "Penske" | |

### BUG-015: Settings pages lack help text
| # | Step | Expected | Result |
|---|------|----------|--------|
| 1 | Go to owner settings → Business Information | Description text present | |
| 2 | Check progressive pricing section | Explanation of what it does and when to disable | |

---

## 🔵 LOW — Minor UX

### BUG-016: No notification when assigned repair completed
| # | Step | Expected | Result |
|---|------|----------|--------|
| 1 | As owner/manager, assign a repair to a tech | | |
| 2 | As that tech, mark the repair as completed | | |
| 3 | Check owner notifications | Owner got notified of completion | |
| 4 | Check manager notifications (if applicable) | Managers also notified | |

### BUG-017: Unnecessary tech fields when assigning repair
| # | Step | Expected | Result |
|---|------|----------|--------|
| 1 | As admin, go to create repair wizard | | |
| 2 | Reach step 3 (tech fields like drill bit, temperature) | Info banner says these are optional when assigning | |

### BUG-019: Self-invite prevention
| # | Step | Expected | Result |
|---|------|----------|--------|
| 1 | As owner, go to invite member | | |
| 2 | Enter your OWN email | Warning message — suggests "Add myself" instead | |

---

## 🔒 Round 2 & 3 — Tenant Isolation (Code Audit Fixes)

These are harder to manually test — they're internal service-layer fixes. Best verified by checking the automated tests pass, but here are smoke tests:

### BUG-020 to BUG-028: Billing service tenant isolation
| # | Step | Expected | Result |
|---|------|----------|--------|
| 1 | As Shop A owner, go to billing/invoices | Only Shop A's invoices shown | |
| 2 | As Shop B owner, go to billing/invoices | Only Shop B's invoices shown | |
| 3 | Generate an invoice for Shop A customer | Invoice created — no crash | |
| 4 | Send invoice email | Email sends — no NameError crash | |

### BUG-029: REST API unscoped
| # | Step | Expected | Result |
|---|------|----------|--------|
| 1 | As Shop A user, hit `/api/v1/customers/` | Only Shop A customers returned | |
| 2 | As Shop A user, hit `/api/v1/repairs/` | Only Shop A repairs returned | |
| 3 | As Shop A user, hit `/api/v1/technicians/` | Only Shop A technicians returned | |

### BUG-030/031: Dashboard cross-tenant stats
| # | Step | Expected | Result |
|---|------|----------|--------|
| 1 | As Shop A owner, check dashboard stats | Tech count matches Shop A only | |
| 2 | As Shop B owner, check dashboard stats | Tech count matches Shop B only | |

### BUG-032/033: Rewards cross-tenant
| # | Step | Expected | Result |
|---|------|----------|--------|
| 1 | If rewards configured, check pending redemptions | Only current tenant's redemptions shown | |

### BUG-034: Referral leaderboard
| # | Step | Expected | Result |
|---|------|----------|--------|
| 1 | Check referral leaderboard (if feature exists) | Only current tenant's referrers shown | |

### BUG-035/036: Customer portal profile
| # | Step | Expected | Result |
|---|------|----------|--------|
| 1 | Go to customer portal profile creation | Customer dropdown only shows current tenant | |

---

## 🆕 BUG-037: Expired account can't upgrade (redirect loop)
| # | Step | Expected | Result |
|---|------|----------|--------|
| 1 | Log in as expired trial user | Redirected to `/pricing/` | |
| 2 | Click any plan's upgrade button | Reaches `/owner/billing/` — NOT a page reload/loop | |
| 3 | Billing page loads with plan options | Can select a plan and proceed to Stripe | |
| 4 | Verify `/owner/settings/` still blocked | Redirected to `/pricing/` | |
| 5 | Verify `/tech/` still blocked | Redirected to `/pricing/` | |

---

## Quick Summary

| Category | Bugs | Count |
|----------|------|-------|
| Critical — tenant isolation | 001, 002, 003, 020-029, 035-036 | 15 |
| High — broken features | 004, 005, 006, 007, 008, 037 | 6 |
| Medium — UX/logic | 009-015, 030-031, 034 | 10 |
| Low — minor UX | 016, 017, 019, 025, 032-033 | 6 |
| **Total** | | **37** |

*BUG-018 (repair form slides) is DEFERRED — needs design discussion.*
