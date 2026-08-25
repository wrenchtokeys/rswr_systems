/**
 * List skeletons for navigation waits (UI_MAGIC S11).
 *
 * The jobs and invoices lists are server-rendered, so every filter, sort,
 * search and page change is a full navigation. Between the click and the
 * server's first byte the browser keeps painting the OLD list, unchanged and
 * fully interactive — the one moment in this app where nothing at all says
 * "working". This fills it.
 *
 * What it paints is a tracing of the list already on screen: each row is
 * cloned, and every text run inside the clone is swapped for a `.sk-bar` of
 * that run's measured width. Nothing here knows what a job row or an invoice
 * row looks like, and no page has to hand-author a skeleton that will drift
 * from its table. Column widths, row heights and alignment survive because
 * the markup does.
 *
 * Markup contract:
 *   <tbody data-skeleton-list>   or   <div data-skeleton-list> ... </div>
 * Rows are the element's own children. Add it to the mobile card list AND
 * the desktop table body; only the visible one ever gets traced.
 *
 * When it fires: a same-origin navigation to the SAME pathname as the current
 * page — i.e. this list, re-queried. That one rule is why a row -> detail
 * click is excluded for free, and with it S10's row-into-title morph, which a
 * skeleton would have replaced with a grey bar flying into a heading.
 *
 * Nothing paints for the first 180ms. A list that comes back faster than that
 * should look like it never left.
 */
(function () {
    'use strict';

    var GRACE_MS = 180;
    // If a navigation is cancelled (Escape, a failed DNS lookup, a download
    // link that turned out not to navigate), nothing tells us. Undo by hand.
    var FAILSAFE_MS = 12000;

    var startTimer = null;
    var failsafeTimer = null;
    var painted = [];   // [{ original, skeleton }]

    function lists() {
        return document.querySelectorAll('[data-skeleton-list]');
    }

    // --- Tracing ------------------------------------------------------------

    function textRuns(root) {
        var out = [];
        var walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
            acceptNode: function (node) {
                return node.nodeValue && node.nodeValue.trim()
                    ? NodeFilter.FILTER_ACCEPT
                    : NodeFilter.FILTER_REJECT;
            }
        });
        while (walker.nextNode()) out.push(walker.currentNode);
        return out;
    }

    // Icons, images and form controls carry no text run, so the walk above
    // cannot see them — they would survive into the skeleton as themselves.
    function glyphs(root) {
        return Array.prototype.slice.call(
            root.querySelectorAll('i, svg, img, input, select, textarea')
        );
    }

    // Status pills and row tints are the one thing a traced skeleton must NOT
    // keep. Blanking the text but leaving the badge blue says "the status is
    // known, the rest is loading", which is backwards — the colour is from the
    // list being left, and after a status filter it is exactly the thing about
    // to change. A pill keeps its shape in skeleton grey; a whole-row tint goes.
    function tinted(root) {
        var els = Array.prototype.slice.call(root.querySelectorAll('[class*="bg-"]'));
        if (root.className && root.className.indexOf('bg-') !== -1) els.unshift(root);
        return els;
    }

    function bar(width, height) {
        var el = document.createElement('span');
        el.className = 'sk-bar';
        el.style.width = Math.max(12, Math.round(width)) + 'px';
        el.style.height = Math.max(8, Math.round(height)) + 'px';
        return el;
    }

    /** One bar per rendered LINE of a text run, so wrapped text stays two bars tall. */
    function barsFor(rects) {
        if (rects.length === 1) return bar(rects[0].width, Math.min(rects[0].height, 12));
        var wrap = document.createElement('span');
        wrap.className = 'sk-lines';
        for (var i = 0; i < rects.length; i++) {
            wrap.appendChild(bar(rects[i].width, Math.min(rects[i].height, 12)));
        }
        return wrap;
    }

    function measureRun(node) {
        var range = document.createRange();
        range.selectNodeContents(node);
        var rects = Array.prototype.slice.call(range.getClientRects())
            .filter(function (r) { return r.width > 0 && r.height > 0; });
        range.detach && range.detach();
        return rects;
    }

    /**
     * Clone `row` and blank it out.
     *
     * The two trees are identical, so the same walk in the same order visits
     * the same nodes in each — that is what lets a measurement taken on the
     * live row be applied to its twin without threading any ids through.
     */
    function traceRow(row) {
        var rowRect = row.getBoundingClientRect();
        if (!rowRect.height) return null;

        var liveRuns = textRuns(row).map(measureRun);
        var liveGlyphs = glyphs(row).map(function (el) {
            return el.getBoundingClientRect();
        });
        // true = a chip (keep the shape, in grey); false = a slab (drop the tint).
        var liveTint = tinted(row).map(function (el) {
            return el.getBoundingClientRect().width < rowRect.width * 0.5;
        });

        var clone = row.cloneNode(true);

        // An id or a view-transition key duplicated into the skeleton is a real
        // bug, not a cosmetic one: two elements sharing a
        // `view-transition-name` abort the whole transition (S10).
        var tagged = clone.querySelectorAll('[id], [data-vt-key], [data-vt-hero]');
        for (var t = 0; t < tagged.length; t++) {
            tagged[t].removeAttribute('id');
            tagged[t].removeAttribute('data-vt-key');
            tagged[t].removeAttribute('data-vt-hero');
        }
        if (clone.removeAttribute) {
            clone.removeAttribute('id');
            clone.removeAttribute('data-vt-key');
        }

        var cloneRuns = textRuns(clone);
        for (var i = 0; i < cloneRuns.length && i < liveRuns.length; i++) {
            var rects = liveRuns[i];
            var node = cloneRuns[i];
            if (!rects.length) { node.nodeValue = ''; continue; }
            node.parentNode.replaceChild(barsFor(rects), node);
        }

        var cloneTint = tinted(clone);
        for (var b = 0; b < cloneTint.length && b < liveTint.length; b++) {
            cloneTint[b].style.backgroundColor = liveTint[b] ? 'var(--sk-tone)' : 'transparent';
        }

        var cloneGlyphs = glyphs(clone);
        for (var g = 0; g < cloneGlyphs.length && g < liveGlyphs.length; g++) {
            var rect = liveGlyphs[g];
            var el = cloneGlyphs[g];
            if (!rect.width || !rect.height) { el.remove(); continue; }
            el.parentNode.replaceChild(bar(rect.width, Math.min(rect.height, 16)), el);
        }

        // Cells are emptied, so the table would re-lay-out its columns from
        // nothing and every one of them would jump. Pin the geometry we just
        // measured. On a <tr> `height` is a minimum, which is what we want.
        clone.style.height = Math.round(rowRect.height) + 'px';
        var liveCells = row.children;
        var cloneCells = clone.children;
        for (var c = 0; c < cloneCells.length && c < liveCells.length; c++) {
            var w = liveCells[c].getBoundingClientRect().width;
            if (w) cloneCells[c].style.width = Math.round(w) + 'px';
        }
        return clone;
    }

    function paintOne(container) {
        var rows = Array.prototype.slice.call(container.children);
        if (!rows.length) return;
        // A hidden breakpoint twin (`sm:hidden` / `hidden sm:block`) measures
        // as zero everywhere; tracing it would produce a stack of empty boxes.
        if (!container.getBoundingClientRect().height) return;

        var skeleton = document.createElement(container.tagName);
        skeleton.className = container.className + ' sk-list';
        skeleton.setAttribute('aria-hidden', 'true');
        skeleton.setAttribute('aria-busy', 'true');
        skeleton.setAttribute('data-skeleton-tracing', '');

        for (var i = 0; i < rows.length; i++) {
            var traced = traceRow(rows[i]);
            if (traced) skeleton.appendChild(traced);
        }
        if (!skeleton.children.length) return;

        container.parentNode.insertBefore(skeleton, container.nextSibling);
        container.hidden = true;
        painted.push({ original: container, skeleton: skeleton });
    }

    function paint() {
        startTimer = null;
        if (painted.length) return;
        var containers = lists();
        for (var i = 0; i < containers.length; i++) paintOne(containers[i]);
        if (painted.length) {
            // The only thing this attribute does is turn the cursor to
            // `progress` (see input.css). It is a page-wide "working" that
            // needs no markup from the page, which is the bar for anything
            // this file adds outside the list itself.
            document.documentElement.setAttribute('data-list-loading', '');
            failsafeTimer = setTimeout(restore, FAILSAFE_MS);
        }
    }

    function restore() {
        clearTimeout(startTimer); startTimer = null;
        clearTimeout(failsafeTimer); failsafeTimer = null;
        for (var i = 0; i < painted.length; i++) {
            painted[i].skeleton.remove();
            painted[i].original.hidden = false;
        }
        painted = [];
        document.documentElement.removeAttribute('data-list-loading');
    }

    function start() {
        if (startTimer || painted.length) return;
        if (!lists().length) return;
        startTimer = setTimeout(paint, GRACE_MS);
    }

    // --- When to fire -------------------------------------------------------

    /** Same list, re-queried — as opposed to a row opening its detail page. */
    function isSameList(url) {
        try {
            var u = new URL(url, location.href);
            return u.origin === location.origin && u.pathname === location.pathname;
        } catch (e) {
            return false;
        }
    }

    document.addEventListener('click', function (e) {
        if (e.defaultPrevented || e.button !== 0) return;
        if (e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
        var a = e.target.closest && e.target.closest('a[href]');
        if (!a || a.target === '_blank' || a.hasAttribute('download')) return;
        if (a.getAttribute('href').charAt(0) === '#') return;
        if (isSameList(a.href)) start();
    }, true);

    document.addEventListener('submit', function (e) {
        var form = e.target;
        if (!form || form.tagName !== 'FORM') return;
        if ((form.method || 'get').toLowerCase() !== 'get') return;
        if (isSameList(form.getAttribute('action') || location.href)) start();
    }, true);

    // The status <select> on the jobs list navigates with `location.href = …`,
    // which no click or submit listener can see. The Navigation API can.
    if (window.navigation && window.navigation.addEventListener) {
        window.navigation.addEventListener('navigate', function (e) {
            if (e.navigationType === 'traverse') return;   // Back must not skeleton, and must not poison bfcache
            if (e.destination && e.destination.sameDocument) return;
            if (e.hashChange) return;
            // A POST to this same path is a mutation, not a re-query. It is the
            // other half of S11's job — an optimistic row — and a skeleton
            // would erase the flip it just made. (`formData` is null on a GET
            // form submission and set on a POST one.)
            if (e.formData) return;
            if (e.destination && isSameList(e.destination.url)) start();
        });
    }

    // pageswap (S10's snapshot) has already fired by the time pagehide does,
    // so undoing here is invisible — and it keeps a skeleton out of bfcache.
    window.addEventListener('pagehide', restore);
    window.addEventListener('pageshow', restore);

    window.ListLoading = { start: start, restore: restore };
})();
