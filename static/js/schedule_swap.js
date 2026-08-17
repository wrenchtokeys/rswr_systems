// Drag to swap two appointments (FIELD_OPS S7).
//
// A manager drags one booked job onto another in the same technician's day
// and the two trade start times. Only loaded for managers — a technician's
// schedule page never includes this file, so there are no handles to find.
// The endpoint re-checks authorization anyway.
//
// Hand-rolled Pointer Events rather than a library: this app vendors its own
// assets (no npm, no CDN), and one pointer path covers mouse and touch alike.
// The drag starts only from the handle, because the row already holds three
// interactive children — an external map anchor, a tel: link, and the
// View/Start/Continue button.
//
// Two paths to the same swap:
//   * drag a handle onto another row (direct manipulation, no confirm)
//   * click a handle, then click another handle (keyboard/assistive reachable,
//     confirms first because there is no drag to "see")
(function () {
    'use strict';

    var script = document.currentScript
        || document.querySelector('script[data-swap-url]');
    var SWAP_URL = script && script.getAttribute('data-swap-url');
    if (!SWAP_URL) { return; }

    // Past this many pixels a press becomes a drag rather than a click.
    var DRAG_THRESHOLD = 8;

    var drag = null;      // active pointer drag
    var selected = null;  // row picked by the click-click path
    var busy = false;     // a swap is in flight; ignore further gestures

    function rowOf(el) {
        return el && el.closest ? el.closest('[data-job-key]') : null;
    }

    function groupOf(row) {
        return row ? row.closest('[data-swap-group]') : null;
    }

    function timeOf(row) {
        var raw = row.getAttribute('data-scheduled-for');
        var when = raw ? new Date(raw) : null;
        if (!when || isNaN(when.getTime())) { return ''; }
        return when.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });
    }

    function nameOf(row) {
        return row.getAttribute('data-job-name') || 'this job';
    }

    function refOf(row) {
        var key = row.getAttribute('data-job-key') || '';
        var split = key.indexOf('-');
        return {
            type: key.slice(0, split),
            id: parseInt(key.slice(split + 1), 10),
            scheduled_for: row.getAttribute('data-scheduled-for')
        };
    }

    // Why this row can't take a drop — null means it can. Refusing in the
    // browser with a reason beats a dead handle or a silent no-op; the server
    // enforces every one of these again.
    function refuse(source, target) {
        if (!target || target === source) { return null; }
        var block = target.getAttribute('data-swap-block');
        if (block === 'completed') {
            return 'That job is already done — its time can’t change.';
        }
        if (block === 'batch') {
            return 'Multi-break jobs move together — open the job to change its time.';
        }
        var targetGroup = groupOf(target);
        if (targetGroup !== groupOf(source)) {
            if (targetGroup && targetGroup.getAttribute('data-swap-group') === 'triage') {
                return 'Those jobs have no time yet. Drop onto a booked job to trade times.';
            }
            return 'Jobs can only trade times within one technician’s day. '
                + 'To move work to another tech, reassign it.';
        }
        return null;
    }

    function clearTargets() {
        document.querySelectorAll('.swap-row-target').forEach(function (el) {
            el.classList.remove('swap-row-target');
        });
    }

    function clearSelection() {
        if (selected) { selected.classList.remove('swap-row-selected'); }
        selected = null;
    }

    function submit(source, target) {
        if (busy) { return; }
        busy = true;
        document.body.classList.add('swap-busy');

        fetch(SWAP_URL, {
            method: 'POST',
            credentials: 'same-origin',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': window.UI ? window.UI.csrfToken() : ''
            },
            body: JSON.stringify({ a: refOf(source), b: refOf(target) })
        }).then(function (res) {
            // Content type is checked BEFORE res.ok on purpose. A read-only or
            // grace-period tenant is stopped by SubscriptionEnforcementMiddleware,
            // which returns JSON only for /api/ paths and otherwise redirects —
            // fetch follows that redirect, so an HTML page arrives as a 200 and
            // res.json() would throw an opaque parse error.
            var type = res.headers.get('Content-Type') || '';
            if (type.indexOf('application/json') === -1) {
                throw new Error(
                    'Couldn’t save that change. Reload the page and try again.'
                );
            }
            return res.json().then(function (data) {
                if (!res.ok || !data.ok) {
                    throw new Error(
                        data.error
                        || 'Couldn’t save that change. Reload and try again.'
                    );
                }
                return data;
            });
        }).then(function (data) {
            // Reload rather than reordering by hand: the server computes the
            // order, and a successful swap changes both times AND both
            // positions. flash() carries the message across the reload.
            if (window.UI) { window.UI.flash(data.message, 'success'); }
            window.location.reload();
        }).catch(function (err) {
            busy = false;
            document.body.classList.remove('swap-busy');
            if (window.UI) { window.UI.toast(err.message, 'error'); }
        });
    }

    // --- click, then click: the non-drag path -----------------------------
    function pickByClick(row) {
        if (!selected) {
            selected = row;
            row.classList.add('swap-row-selected');
            if (window.UI) {
                window.UI.toast(
                    'Now pick the job to trade times with.', 'info');
            }
            return;
        }
        if (selected === row) { clearSelection(); return; }

        var source = selected;
        var reason = refuse(source, row);
        clearSelection();
        if (reason) {
            if (window.UI) { window.UI.toast(reason, 'warning'); }
            return;
        }
        var message = nameOf(source) + ' moves to ' + timeOf(row) + ', and '
            + nameOf(row) + ' to ' + timeOf(source) + '.';
        if (window.UI && window.UI.confirm) {
            window.UI.confirm({
                title: 'Trade times?',
                message: message,
                confirmLabel: 'Trade times'
            }).then(function (ok) {
                if (ok) { submit(source, row); }
            });
        } else {
            submit(source, row);
        }
    }

    // --- pointer drag ------------------------------------------------------
    document.addEventListener('pointerdown', function (e) {
        if (busy || e.button > 0) { return; }
        var handle = e.target.closest && e.target.closest('.swap-handle');
        if (!handle) { return; }
        var row = rowOf(handle);
        if (!row) { return; }
        drag = { row: row, handle: handle, x: e.clientX, y: e.clientY,
                 moved: false, pointerId: e.pointerId };
    });

    document.addEventListener('pointermove', function (e) {
        if (!drag || e.pointerId !== drag.pointerId) { return; }

        if (!drag.moved) {
            if (Math.abs(e.clientX - drag.x) < DRAG_THRESHOLD
                && Math.abs(e.clientY - drag.y) < DRAG_THRESHOLD) { return; }
            drag.moved = true;
            clearSelection();
            drag.row.classList.add('swap-row-dragging');
            document.body.classList.add('swap-dragging');
            // Capture so the gesture survives the pointer leaving the handle.
            if (drag.handle.setPointerCapture) {
                try { drag.handle.setPointerCapture(e.pointerId); } catch (err) { /* ignore */ }
            }
        }

        // The dragged row is pointer-events:none while dragging (see
        // input.css), so this finds what is underneath it, not itself.
        e.preventDefault();
        var under = document.elementFromPoint(e.clientX, e.clientY);
        var target = rowOf(under);
        clearTargets();
        if (target && target !== drag.row && !refuse(drag.row, target)) {
            target.classList.add('swap-row-target');
        }
    }, { passive: false });

    function endDrag(e) {
        if (!drag || (e && e.pointerId !== drag.pointerId)) { return; }
        var state = drag;
        drag = null;
        state.row.classList.remove('swap-row-dragging');
        document.body.classList.remove('swap-dragging');
        clearTargets();

        if (!state.moved) {
            pickByClick(state.row);
            return;
        }

        var under = e ? document.elementFromPoint(e.clientX, e.clientY) : null;
        var target = rowOf(under);
        if (!target) {
            // Landed on something that isn't a swappable row. The triage rail
            // is the case worth naming: it sits directly above the tech cards,
            // is the most tempting wrong target on the page, and renders its
            // own markup rather than the shared row partial — so there is no
            // row here to refuse, only a group.
            var group = under && under.closest
                ? under.closest('[data-swap-group]') : null;
            if (group && group.getAttribute('data-swap-group') === 'triage'
                && window.UI) {
                window.UI.toast(
                    'Those jobs have no time yet. Drop onto a booked job to '
                    + 'trade times.', 'warning');
            }
            return;
        }
        if (target === state.row) { return; }
        var reason = refuse(state.row, target);
        if (reason) {
            if (window.UI) { window.UI.toast(reason, 'warning'); }
            return;
        }
        submit(state.row, target);
    }

    document.addEventListener('pointerup', endDrag);
    document.addEventListener('pointercancel', endDrag);

    document.addEventListener('keydown', function (e) {
        if (e.key !== 'Escape') { return; }
        if (drag) {
            drag.row.classList.remove('swap-row-dragging');
            document.body.classList.remove('swap-dragging');
            clearTargets();
            drag = null;
        }
        clearSelection();
    });
})();
