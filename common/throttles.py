"""
Resilient throttle classes that degrade gracefully if the cache backend
is misconfigured or unavailable. DRF's built-in throttles crash with a
500 if cache.get() raises — these catch the exception and allow the
request through (better to skip rate-limiting than to block all API access).
"""

import logging
from rest_framework.throttling import AnonRateThrottle, UserRateThrottle

logger = logging.getLogger(__name__)


class ResilientAnonRateThrottle(AnonRateThrottle):
    def allow_request(self, request, view):
        try:
            return super().allow_request(request, view)
        except Exception:
            logger.warning("AnonRateThrottle unavailable (cache backend error)")
            return True


class ResilientUserRateThrottle(UserRateThrottle):
    def allow_request(self, request, view):
        try:
            return super().allow_request(request, view)
        except Exception:
            logger.warning("UserRateThrottle unavailable (cache backend error)")
            return True
