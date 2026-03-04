
## [Unreleased] - 2026-03-04

### Fixed (Round 2 Code Audit — BUG-020 through BUG-027)
- **BUG-020:** Fixed NameError crash in send_invoice_email/send_invoice_email_batch views (Invoice model not imported)
- **BUG-021:** InvoiceTrackingService.get_outstanding_invoices() now tenant-scoped (was leaking cross-tenant data)
- **BUG-022:** InvoiceTrackingService.update_overdue_statuses() no longer mutates ALL tenants' invoices
- **BUG-023:** InvoiceTrackingService.get_uninvoiced_repairs() now scopes InvoiceLineItem query by tenant
- **BUG-024:** StripeService._record_stripe_payment() — added audit logging of tenant context
- **BUG-025:** InvoiceService.build_invoice_data() now filters Customer by tenant
- **BUG-026:** DashboardService alerts now filters batch customer prefs by tenant (returns empty without tenant)
- **BUG-027:** InvoiceEmailService now accepts tenant param and scopes all payment link queries; all callers updated
