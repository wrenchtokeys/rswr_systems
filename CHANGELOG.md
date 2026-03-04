
## [Unreleased] - 2026-03-04

### Fixed (Round 2 Code Audit — BUG-020 through BUG-026)
- **BUG-020/021:** InvoiceTrackingService.get_outstanding_invoices() and update_overdue_statuses() now tenant-scoped (was leaking cross-tenant invoice data)
- **BUG-022:** InvoiceTrackingService.get_uninvoiced_repairs() now includes tenant filter for defense-in-depth
- **BUG-023:** DashboardService.get_alerts() now filters batch customer preferences by tenant and passes tenant to sub-services
- **BUG-024:** StripeService._record_stripe_payment() now passes tenant to InvoiceTrackingService
- **BUG-025:** ReminderService._build_reminder_email() uses BillingConfig.get_instance() instead of .first()
- **BUG-026:** InvoiceService now accepts optional tenant parameter and filters repairs accordingly
- **BUG-027:** Fixed NameError crash in send_invoice_email/send_invoice_email_batch views (Invoice model not imported)
- **BUG-028:** InvoiceEmailService now accepts tenant parameter and scopes InvoiceLineItem/Invoice queries
