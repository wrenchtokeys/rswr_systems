/**
 * The dispatch board's inline writes (FIELD_OPS S4 book + S5 assign).
 *
 * Two kinds of row form, one handler:
 *
 *   - a triage row's form carries a date, a window and (for a manager who can
 *     assign) a technician — "book this, with this person, then"
 *   - a booked row's form carries only a technician — "same time, different
 *     person"
 *
 * Each form names its own endpoint in `data-post-url`, so a manager who can
 * schedule but not reassign posts to S4's narrower /tech/schedule/book/ and
 * gets exactly the permission they have. Both are plain <form> elements: if
 * this script fails to load, submitting reloads the page rather than doing
 * nothing silently.
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

    var busy = false;

    function value(form, selector) {
        var el = form.querySelector(selector);
        return el ? el.value : '';
    }

    function payloadFor(row, form) {
        // data-job-key is "{service_type}-{id}"; split on the FIRST dash only,
        // since the type itself never contains one but a future id might.
        var key = row.getAttribute('data-job-key') || '';
        var dash = key.indexOf('-');
        var tech = form.querySelector('[data-dispatch-tech]');
        var body = {
            type: key.slice(0, dash),
            id: key.slice(dash + 1),
            // What this row believed the job's time was. Empty means
            // "unscheduled", which is the normal case on the rail and is
            // exactly the expectation the server's optimistic lock checks —
            // so a job someone else booked in another tab refuses instead of
            // moving.
            expected: row.getAttribute('data-scheduled-for') || ''
        };

        // A booked row's move form has no date input at all; the server reads
        // an absent date as "who only, leave the time alone".
        var date = value(form, '[data-dispatch-date]');
        if (date) {
            body.date = date;
            body.window = value(form, '[data-dispatch-window]');
            // Only meaningful when the window is EXACT; the server ignores
            // them otherwise, so a stale pair cannot override a preset.
            body.start_time = value(form, '[data-dispatch-start]');
            body.end_time = value(form, '[data-dispatch-end]');
        }

        if (tech) {
            body.technician_id = tech.value;
            // The second optimistic lock: who the row showed when it rendered.
            body.expected_technician_id =
                row.getAttribute('data-technician-id') || '';
        }
        return body;
    }

    // Delegated listeners throughout — rows re-render on every page load and
    // a busy board has dozens of them.
    document.addEventListener('change', function (event) {
        var form = event.target.closest('[data-dispatch-form]');
        if (!form) { return; }

        // Show the from/until clock only for a specific window.
        if (event.target.matches('[data-dispatch-window]')) {
            var exact = form.querySelector('[data-dispatch-exact]');
            if (exact) {
                var on = event.target.value === 'EXACT';
                exact.classList.toggle('hidden', !on);
                if (!on) {
                    exact.querySelectorAll('input').forEach(function (input) {
                        input.value = '';
                    });
                }
            }
        }

        // Reveal Move only once the picker names somebody else. A <select>
        // is one tap away from a misfire, and this write emails two people.
        if (event.target.matches('[data-dispatch-tech]')) {
            var button = form.querySelector('[data-dispatch-submit]');
            var row = form.closest('[data-job-key]');
            if (button && row) {
                var moved = event.target.value
                    !== (row.getAttribute('data-technician-id') || '');
                button.classList.toggle('hidden', !moved);
            }
        }
    });

    document.addEventListener('submit', function (event) {
        var form = event.target.closest('[data-dispatch-form]');
        if (!form) { return; }
        event.preventDefault();
        if (busy) { return; }

        var url = form.getAttribute('data-post-url');
        var row = form.closest('[data-job-key]');
        if (!url || !row) { return; }

        var button = form.querySelector('button[type="submit"]');
        busy = true;
        if (button) { button.disabled = true; }

        fetch(url, {
            method: 'POST',
            credentials: 'same-origin',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': window.UI ? window.UI.csrfToken() : ''
            },
            body: JSON.stringify(payloadFor(row, form))
        }).then(function (res) {
            var type = res.headers.get('Content-Type') || '';
            if (type.indexOf('application/json') === -1) {
                throw new Error(
                    'Couldn’t save that. Reload the page and try again.'
                );
            }
            return res.json().then(function (data) {
                if (!res.ok || !data.ok) {
                    throw new Error(
                        data.error || 'Couldn’t save that. Reload and try again.'
                    );
                }
                return data;
            });
        }).then(function (data) {
            // Reload rather than moving the row by hand: a dispatched job
            // leaves the rail, joins a tech's day — possibly on another date
            // entirely — and can change what conflicts the board is flagging.
            // flash() carries the message across the reload.
            if (window.UI) { window.UI.flash(data.message, 'success'); }
            window.location.reload();
        }).catch(function (err) {
            busy = false;
            if (button) { button.disabled = false; }
            if (window.UI) { window.UI.toast(err.message, 'error'); }
        });
    });
})();
