/**
 * Optimistic row state (UI_MAGIC S11).
 *
 * A status change in this app costs a round trip: the row sits unchanged, the
 * button greys out, and a second later the page reloads. This shows the answer
 * first and reconciles after — and, when the server disagrees, puts the row
 * back where the user can see it happen.
 *
 * Three states, and the middle one is the point:
 *   begin(rows)             the new value is on screen, the row is dimmed
 *   commit(token, [opts])   agreed — the dim lifts, optionally with a tick
 *   rollback(token, ids)    refused — the row's old markup returns, amber
 *
 * Rollback restores the row's saved innerHTML rather than trying to undo each
 * edit. Every handler on these rows is an inline `onclick` attribute, which
 * survives that round trip; a listener added with addEventListener would not,
 * so do not reach for this on a row that has one.
 *
 * Usage:
 *   var token = Optimistic.begin(ids, function (row, id) { ...mutate... });
 *   fetch(...).then(function (data) {
 *       var refused = ids.filter(function (i) { return data.paid_ids.indexOf(i) < 0; });
 *       if (refused.length) Optimistic.rollback(token, refused);
 *       Optimistic.commit(token, { check: true });
 *   });
 */
(function () {
    'use strict';

    var CHECK_SVG =
        '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M3 8.4l3.1 3.1L13 4.7"/></svg>';

    function rowsFor(id) {
        // Two rows per record on these pages: the mobile card and the desktop
        // table row. Both are in the DOM at every width; only one is painted.
        return Array.prototype.slice.call(
            document.querySelectorAll('[data-optimistic-row="' + id + '"]')
        );
    }

    /**
     * @param {Array} ids      record ids being changed
     * @param {Function} apply (rowElement, id) — make the change look done
     * @returns {Object} token — pass it back to commit() or rollback()
     */
    function begin(ids, apply) {
        var saved = {};
        ids.forEach(function (id) {
            var rows = rowsFor(id);
            saved[id] = rows.map(function (row) { return row.innerHTML; });
            rows.forEach(function (row) {
                try {
                    apply(row, id);
                } catch (e) {
                    /* A row that cannot be flipped is not a reason to lose the
                       action; it just reconciles on the next load like before. */
                }
                row.classList.add('row-pending');
                row.setAttribute('aria-busy', 'true');
            });
        });
        return { ids: ids.slice(), saved: saved };
    }

    function settle(row) {
        row.classList.remove('row-pending');
        row.removeAttribute('aria-busy');
    }

    /**
     * @param {Object} token
     * @param {Object} [opts]  {ids: only these, check: draw a tick in [data-optimistic-check]}
     */
    function commit(token, opts) {
        opts = opts || {};
        var ids = opts.ids || token.ids;
        ids.forEach(function (id) {
            rowsFor(id).forEach(function (row) {
                settle(row);
                if (!opts.check) return;
                var slot = row.querySelector('[data-optimistic-check]');
                if (!slot || slot.querySelector('.paid-check')) return;
                var tick = document.createElement('span');
                tick.className = 'paid-check';
                tick.innerHTML = CHECK_SVG;
                slot.insertBefore(tick, slot.firstChild);
            });
            delete token.saved[id];
        });
    }

    /** Put the listed rows back, visibly. Everything not listed stays optimistic. */
    function rollback(token, ids) {
        (ids || token.ids).forEach(function (id) {
            var html = token.saved[id];
            if (!html) return;
            rowsFor(id).forEach(function (row, i) {
                if (html[i] !== undefined) row.innerHTML = html[i];
                settle(row);
                row.classList.remove('row-rollback');
                // Reading offsetWidth restarts an animation that is already on
                // the element — without it a second failure would be silent.
                void row.offsetWidth;
                row.classList.add('row-rollback');
            });
            delete token.saved[id];
        });
    }

    /** Repaint a `{% status_badge %}` pill in place. Same markup the tag emits. */
    function setBadge(row, classes, label) {
        var badge = row.querySelector('[data-optimistic-badge]');
        if (!badge) return;
        badge.className =
            'inline-flex items-center px-2 py-0.5 rounded-full text-xs font-semibold ' + classes;
        badge.textContent = label;
    }

    window.Optimistic = {
        begin: begin,
        commit: commit,
        rollback: rollback,
        setBadge: setBadge
    };
})();
