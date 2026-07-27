# SES Bounce → Shop Notification Setup

When an invoice email bounces (bad address, full mailbox that never recovers,
spam complaint), the shop gets:

- an in-app notification for every manager technician, and
- a branded email to the shop's business address (and owner) with an
  "Open Invoice" button to re-send.

Matching works via `Invoice.last_sent_to` (recorded on every send) against the
bounced recipient, for invoices sent in the last 14 days.

## One-time AWS setup

1. **Create an SNS topic** (region `us-east-1`, same as SES):
   ```bash
   aws sns create-topic --name rs-systems-ses-events
   ```

2. **Point SES feedback notifications at the topic.**
   SES Console → *Verified identities* → `rssystems.io` (and/or
   `notifications@rssystems.io`) → *Notifications* → set **Bounce feedback**
   and **Complaint feedback** to the `rs-systems-ses-events` topic.
   Leave "Include original headers" off (not needed).

3. **Generate a webhook secret** and set it on the EB environment:
   ```bash
   python -c "import secrets; print(secrets.token_urlsafe(32))"
   eb setenv SES_WEBHOOK_SECRET=<the value>
   ```
   ⚠️ Remember the EB config-deploy static-files gotcha: `eb setenv` triggers a
   config deploy; confighooks re-run collectstatic (fixed in PR #107), so this
   is safe now — but verify the site after.

4. **Subscribe the endpoint to the topic** (after step 3 is deployed):
   ```bash
   aws sns subscribe \
     --topic-arn arn:aws:sns:us-east-1:<ACCOUNT_ID>:rs-systems-ses-events \
     --protocol https \
     --notification-endpoint "https://rssystems.io/api/billing/webhooks/ses/<SES_WEBHOOK_SECRET>/"
   ```
   The endpoint auto-confirms the subscription (it fetches the SNS
   `SubscribeURL`). Check the subscription shows **Confirmed** in the SNS
   console.

## Verify

- SES Console → verified identity → *Send test email* → choose the
  **bounce** simulator (`bounce@simulator.amazonses.com`) — or send a real
  invoice to that address from a test tenant.
- The shop owner should receive the "Invoice Email Not Delivered" email and
  see the in-app notification.
- Webhook logs: `eb logs` — look for `Invoice ... did not reach`.

## Notes

- Transient bounces (mailbox temporarily full, greylisting) are ignored —
  only permanent bounces and spam complaints alert the shop.
- The URL secret is the authentication. Rotating it: `eb setenv` a new value,
  then update the SNS subscription endpoint.
- Synchronous failures (SES rejects the send outright) were already handled:
  the invoice stays DRAFT and the UI shows an error. This pipeline covers the
  asynchronous case where SES accepts the mail and the destination later
  rejects it.
