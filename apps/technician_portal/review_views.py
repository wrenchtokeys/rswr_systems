"""
Public views for review request click tracking and opt-out.

These endpoints require no authentication — they use the ReviewRequest's
UUID token for identification.
"""
import logging

from django.http import HttpResponse
from django.shortcuts import redirect, get_object_or_404
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_http_methods

from apps.technician_portal.review_models import ReviewConfig, ReviewRequest

logger = logging.getLogger(__name__)


@require_GET
def review_click(request, token):
    """
    GET /reviews/click/<uuid:token>/

    Marks the ReviewRequest as 'clicked' and redirects to the Google review URL.
    """
    rr = get_object_or_404(ReviewRequest, token=token)

    if rr.status == 'sent':
        rr.status = 'clicked'
        rr.clicked_at = timezone.now()
        rr.save(update_fields=['status', 'clicked_at'])

    # Redirect to Google review URL
    config = ReviewConfig.get_for_tenant(rr.tenant)
    review_url = config.google_review_url

    if review_url:
        return redirect(review_url)

    # Fallback: friendly message if URL not configured
    return HttpResponse(
        "<h2>Thank you!</h2><p>We appreciate you taking the time. "
        "Please search for our business on Google to leave a review.</p>",
        content_type='text/html',
    )


@csrf_exempt
@require_http_methods(["GET", "POST"])
def review_opt_out(request, token):
    """
    GET/POST /reviews/opt-out/<uuid:token>/

    Sets review_opt_out=True on the CustomerUser. No auth required.
    CAN-SPAM compliant unsubscribe link. POST (csrf-exempt) is the RFC 8058
    one-click unsubscribe target — mail clients POST here directly from the
    List-Unsubscribe header, with no page render and no CSRF token.
    """
    rr = get_object_or_404(ReviewRequest, token=token)

    if rr.customer_user:
        rr.customer_user.review_opt_out = True
        rr.customer_user.save(update_fields=['review_opt_out'])
        logger.info(
            "Review opt-out: customer_user pk=%s opted out via token=%s",
            rr.customer_user.pk, token,
        )

    return HttpResponse(
        "<h2>You've been unsubscribed</h2>"
        "<p>You will no longer receive review request emails from us. "
        "If this was a mistake, please contact the shop directly.</p>",
        content_type='text/html',
    )
