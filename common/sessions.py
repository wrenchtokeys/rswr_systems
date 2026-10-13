"""How long a signed-in device stays signed in.

Two pieces, and they only work together:

`keep_signed_in(request)` gives a session the long lifetime
(`settings.REMEMBER_ME_SESSION_AGE`). It is what the login form's "Keep me
signed in" box calls.

`SlidingSessionMiddleware` makes that lifetime count from the last VISIT, not
from the login. Django stamps a session's expiry only when the session is
saved, and it is saved only when something writes to it — so a technician who
opened the app every working day was still thrown out on a fixed date, mid-job.
Touching the session once a day re-stamps both the cookie and the row.

Once a day, not every request (`SESSION_SAVE_EVERY_REQUEST`): that setting is a
database write on every page, photo and JSON poll, to move a 90-day deadline by
seconds.

A browser-length session (box unticked — the shared shop computer) is left
alone: it has no deadline to slide, and saving it would not give it one.
"""
from django.conf import settings
from django.utils import timezone

STAMP_KEY = '_kept_alive'


def keep_signed_in(request):
    """Give this session the long, sliding lifetime."""
    request.session.set_expiry(settings.REMEMBER_ME_SESSION_AGE)


class SlidingSessionMiddleware:
    """Re-stamp a signed-in session's expiry on the first request of each day.

    Must sit after AuthenticationMiddleware. Anonymous requests are never
    touched — writing to an anonymous session would create a row and set a
    cookie for every crawler and health check.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, 'user', None)
        if user is not None and user.is_authenticated:
            session = request.session
            if not session.get_expire_at_browser_close():
                today = timezone.now().date().isoformat()
                if session.get(STAMP_KEY) != today:
                    session[STAMP_KEY] = today
        return self.get_response(request)
