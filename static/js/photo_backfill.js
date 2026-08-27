/**
 * The unmarked-photo burn-down (P4a.1, docs/strategy/PHOTO_ML_SESSIONS.md).
 *
 * Seventy-seven damage photos in production, one of them marked. The detail
 * page can mark any of them, one job at a time, and nobody was ever going to
 * open seventy-seven jobs. So: the whole worklist arrives as JSON, this
 * shows one photo at a time, and a tap plus a confirm moves to the next.
 *
 * Two taps per photo, not one, and that is deliberate — a single tap that
 * both marks and saves means every mis-tap is a wrong mark saved on a real
 * customer's invoice, with no undo on this page. The confirm is also where
 * the keyboard shortcut lives, which is what actually makes a desk session
 * fast: tap, Enter, tap, Enter.
 *
 * It POSTs to the same save_photo_crop endpoint as photo_crop_detail.js and
 * borrows PhotoCropModal.percentFromEvent for the tap-to-percent conversion,
 * so the two surfaces cannot drift apart on what a tap means. It does not
 * use the modal itself: this page is the modal, repeatedly.
 *
 * ES5 on purpose, same as the rest of the tap-to-crop code.
 */
(function () {
    'use strict';

    var queue = [];
    var index = 0;          // which photo is on screen
    var saved = 0;          // how many marks landed this session
    var pending = null;     // {x, y} percent, wherever the marker sits
    var csrfToken = '';
    var busy = false;

    var el = {};

    function $(id) { return document.getElementById(id); }

    function toast(message, level) {
        if (window.UI && typeof UI.toast === 'function') {
            UI.toast(message, level || 'info');
        }
    }

    function clearMarker() {
        pending = null;
        el.marker.classList.add('hidden');
        el.save.disabled = true;
    }

    function showMarkerAt(xPct, yPct) {
        pending = { x: xPct, y: yPct };
        // The image is centred in its container, so the marker is positioned
        // against the image's own box inside it — same arithmetic the shared
        // modal uses.
        el.marker.style.left = (el.image.offsetLeft + xPct / 100 * el.image.offsetWidth) + 'px';
        el.marker.style.top = (el.image.offsetTop + yPct / 100 * el.image.offsetHeight) + 'px';
        el.marker.classList.remove('hidden');
        el.save.disabled = false;
    }

    function onTap(e) {
        if (busy) return;
        var point = window.PhotoCropModal
            ? PhotoCropModal.percentFromEvent(el.image, e)
            : null;
        if (!point) return;
        showMarkerAt(point.x, point.y);
    }

    /** Warm the next photo's request while this one is being looked at. */
    function preloadNext() {
        var next = queue[index + 1];
        if (!next || !next.src) return;
        var img = new Image();
        img.src = next.src;
    }

    function updateProgress() {
        var total = queue.length;
        el.position.textContent = Math.min(index + 1, total);
        el.done.textContent = saved === 1 ? '1 marked' : saved + ' marked';
        el.bar.style.width = (total ? (index / total) * 100 : 0) + '%';
    }

    function finish() {
        el.card.classList.add('hidden');
        // The footnotes describe the worklist this page loaded with, which
        // the summary has just superseded.
        var notes = $('photoBackfillNotes');
        if (notes) notes.classList.add('hidden');
        el.finished.classList.remove('hidden');
        var skipped = queue.length - saved;
        var summary = saved === 1 ? '1 break marked' : saved + ' breaks marked';
        if (skipped > 0) {
            summary += skipped === 1 ? ', 1 skipped' : ', ' + skipped + ' skipped';
        }
        el.summary.textContent = summary + '.';
        el.finished.scrollIntoView({ block: 'nearest' });
    }

    function show() {
        if (index >= queue.length) {
            finish();
            return;
        }
        var item = queue[index];
        clearMarker();
        el.broken.classList.add('hidden');
        el.title.textContent = item.title;
        el.subtitle.textContent = item.subtitle || '';
        el.jobLink.href = item.detail_url;
        el.hint.textContent = item.prompt + '.';
        updateProgress();

        el.image.classList.remove('hidden');
        el.image.onload = function () {
            // A photo the sweep already guessed at opens on that guess, so
            // confirming it is a glance rather than a fresh hunt. Marker
            // positions are read off the rendered <img>, so this waits for
            // layout — same reason the shared modal does.
            if (item.at && typeof item.at.x === 'number') {
                showMarkerAt(item.at.x, item.at.y);
                el.hint.textContent =
                    'We guessed this one. Confirm it, or tap to move the mark.';
            }
            preloadNext();
        };
        el.image.onerror = function () {
            // HEIC off Safari, a missing file, a dead S3 object. Nothing the
            // technician can do about it here, so don't make them decide.
            el.image.classList.add('hidden');
            el.broken.classList.remove('hidden');
            el.hint.textContent = "Can't show this one — moving on.";
            setTimeout(advance, 900);
        };
        el.image.src = item.src;
    }

    function advance() {
        index += 1;
        show();
    }

    function save() {
        if (busy || !pending) return;
        var item = queue[index];
        var tap = pending;

        var body = new FormData();
        body.append('source_field', item.field);
        body.append('center_x_pct', tap.x.toFixed(2));
        body.append('center_y_pct', tap.y.toFixed(2));
        // Echo any machine suggestion back so the row keeps the guess beside
        // the human's mark — the distance between them is the only honest
        // measure of whether the suggester is worth keeping.
        if (item.suggested) {
            body.append('suggested_x_pct', item.suggested.x);
            body.append('suggested_y_pct', item.suggested.y);
            body.append('suggested_by', item.suggested.by);
            body.append('suggestion_score', item.suggested.score);
        }

        busy = true;
        el.save.disabled = true;
        el.skip.disabled = true;
        fetch(item.save_url, {
            method: 'POST',
            headers: { 'X-CSRFToken': csrfToken, 'X-Requested-With': 'XMLHttpRequest' },
            body: body,
            credentials: 'same-origin'
        }).then(function (response) {
            return response.json().catch(function () { return {}; });
        }).then(function (data) {
            busy = false;
            el.skip.disabled = false;
            if (!data || !data.success) {
                el.save.disabled = false;
                toast((data && data.error) || "Couldn't save that close-up.", 'error');
                return;
            }
            saved += 1;
            if (!data.cropped) {
                // The tap is on record but the original wouldn't open;
                // retry_photo_crops picks it up later. Still a mark.
                toast('Mark saved — the close-up will follow.', 'info');
            }
            advance();
        }).catch(function () {
            busy = false;
            el.save.disabled = false;
            el.skip.disabled = false;
            toast("Couldn't save that close-up.", 'error');
        });
    }

    function onKeydown(e) {
        if (e.target && /^(INPUT|TEXTAREA|SELECT)$/.test(e.target.tagName)) return;
        if (e.key === 'Enter') {
            if (!el.save.disabled) { e.preventDefault(); save(); }
        } else if (e.key === 's' || e.key === 'S' || e.key === 'ArrowRight') {
            e.preventDefault();
            if (!busy) advance();
        }
    }

    function init() {
        var data = $('photoBackfillQueue');
        if (!data) return;
        try {
            queue = JSON.parse(data.textContent) || [];
        } catch (err) {
            return;
        }
        if (!queue.length) return;

        el = {
            card: $('photoBackfillCard'),
            finished: $('photoBackfillFinished'),
            summary: $('photoBackfillSummary'),
            image: $('photoBackfillImage'),
            marker: $('photoBackfillMarker'),
            broken: $('photoBackfillBroken'),
            title: $('photoBackfillTitle'),
            subtitle: $('photoBackfillSubtitle'),
            jobLink: $('photoBackfillJobLink'),
            hint: $('photoBackfillHint'),
            position: $('photoBackfillPosition'),
            done: $('photoBackfillDone'),
            bar: $('photoBackfillBar'),
            save: $('photoBackfillSave'),
            skip: $('photoBackfillSkip')
        };
        for (var key in el) {
            if (!el[key]) return;
        }

        var csrf = document.querySelector('#photoBackfillCsrf input[name="csrfmiddlewaretoken"]');
        csrfToken = csrf ? csrf.value : '';

        // One pointer path covers mouse and touch alike; click is the
        // fallback for WebViews without pointer events.
        if (window.PointerEvent) {
            el.image.addEventListener('pointerdown', onTap);
        } else {
            el.image.addEventListener('click', onTap);
        }
        el.save.addEventListener('click', save);
        el.skip.addEventListener('click', function () { if (!busy) advance(); });
        document.addEventListener('keydown', onKeydown);
        // The marker is placed in pixels against the rendered image, so a
        // rotation or a resize would leave it pointing somewhere else.
        window.addEventListener('resize', function () {
            if (pending) showMarkerAt(pending.x, pending.y);
        });

        show();
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
