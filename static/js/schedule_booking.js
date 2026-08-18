/**
 * Book a customer's requested time from the triage rail (FIELD_OPS S4).
 *
 * The rail row renders a plain <form> with a date input, a window select and
 * a Book button, prefilled with whatever the customer asked for. This
 * intercepts the submit and POSTs JSON to /tech/schedule/book/. If the script
 * fails to load, the form still submits and the page reloads — nothing
 * happens silently.
 *
 * Response handling mirrors schedule_swap.js, for the same reason: a
 * read-only or grace-period tenant is stopped by
 * SubscriptionEnforcementMiddleware, which answers JSON only for /api/ paths
 * and otherwise redirects. fetch follows that redirect, so an HTML page
 * arrives as a 200 and res.json() would throw an opaque parse error — hence
 * the content-type check BEFORE res.ok.
 */
(function () {
    'use strict';

    var script = document.currentScript
        || document.querySelector('script[data-book-url]');
    var BOOK_URL = script ? script.getAttribute('data-book-url') : null;
    if (!BOOK_URL) { return; }

    var busy = false;

    function refOf(row, form) {
        // data-job-key is "{service_type}-{id}"; split on the FIRST dash only,
        // since the type itself never contains one but a future id might.
        var key = row.getAttribute('data-job-key') || '';
        var dash = key.indexOf('-');
        var start = form.querySelector('[data-book-start]');
        var end = form.querySelector('[data-book-end]');
        return {
            type: key.slice(0, dash),
            id: key.slice(dash + 1),
            date: form.querySelector('[data-book-date]').value,
            window: form.querySelector('[data-book-window]').value,
            // Only meaningful when the window is EXACT; the server ignores
            // them otherwise, so a stale pair cannot override a preset.
            start_time: start ? start.value : '',
            end_time: end ? end.value : '',
            // What this row believed the job's time was. Empty means
            // "unscheduled", which is the normal case here and is exactly the
            // expectation the server's optimistic lock checks — so a job
            // someone else booked in another tab refuses instead of moving.
            expected: row.getAttribute('data-scheduled-for') || ''
        };
    }

    // Show the from/until clock only when the manager picks a specific window.
    // Delegated, because rows are re-rendered on every page load and there may
    // be dozens of them.
    document.addEventListener('change', function (event) {
        var select = event.target.closest('[data-book-window]');
        if (!select) { return; }
        var form = select.closest('[data-book-form]');
        var exact = form && form.querySelector('[data-book-exact]');
        if (!exact) { return; }
        var on = select.value === 'EXACT';
        exact.classList.toggle('hidden', !on);
        if (!on) {
            exact.querySelectorAll('input').forEach(function (input) {
                input.value = '';
            });
        }
    });

    document.addEventListener('submit', function (event) {
        var form = event.target.closest('[data-book-form]');
        if (!form) { return; }
        event.preventDefault();
        if (busy) { return; }

        var row = form.closest('[data-job-key]');
        if (!row) { return; }

        var button = form.querySelector('button[type="submit"]');
        busy = true;
        if (button) { button.disabled = true; }

        fetch(BOOK_URL, {
            method: 'POST',
            credentials: 'same-origin',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': window.UI ? window.UI.csrfToken() : ''
            },
            body: JSON.stringify(refOf(row, form))
        }).then(function (res) {
            var type = res.headers.get('Content-Type') || '';
            if (type.indexOf('application/json') === -1) {
                throw new Error(
                    'Couldn’t book that time. Reload the page and try again.'
                );
            }
            return res.json().then(function (data) {
                if (!res.ok || !data.ok) {
                    throw new Error(
                        data.error
                        || 'Couldn’t book that time. Reload and try again.'
                    );
                }
                return data;
            });
        }).then(function (data) {
            // Reload rather than moving the row by hand: a booked job leaves
            // the rail and joins a tech's day, possibly on another date
            // entirely. flash() carries the message across the reload.
            if (window.UI) { window.UI.flash(data.message, 'success'); }
            window.location.reload();
        }).catch(function (err) {
            busy = false;
            if (button) { button.disabled = false; }
            if (window.UI) { window.UI.toast(err.message, 'error'); }
        });
    });
})();
