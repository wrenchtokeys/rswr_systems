// Field dispatch (S2): turns [data-map-query] and [data-call-number]
// elements into working map / phone links.
//
// The hrefs are composed here, in the browser, from data already on the
// page — customer addresses and phone numbers never appear in a
// server-rendered URL query string where they would land in request logs.
// The Google Maps universal URL opens the native maps app on both iOS and
// Android (a plain geo: URI is unreliable on iOS).
(function () {
    'use strict';

    function wire(root) {
        root.querySelectorAll('a[data-map-query]').forEach(function (el) {
            var query = (el.getAttribute('data-map-query') || '').trim();
            if (!query) { el.removeAttribute('href'); return; }
            el.href = 'https://www.google.com/maps/search/?api=1&query='
                + encodeURIComponent(query);
            el.target = '_blank';
            el.rel = 'noopener';
        });
        root.querySelectorAll('a[data-call-number]').forEach(function (el) {
            var digits = (el.getAttribute('data-call-number') || '')
                .replace(/[^+\d]/g, '');
            if (!digits) { el.removeAttribute('href'); return; }
            el.href = 'tel:' + digits;
        });
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', function () {
            wire(document);
        });
    } else {
        wire(document);
    }
})();
