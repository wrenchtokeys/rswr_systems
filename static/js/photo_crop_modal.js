/**
 * The "tap the break" modal, shared by every surface that captures a crop.
 *
 * Owns #photoCropModal (templates/technician_portal/partials/photo_crop_modal.html)
 * and nothing else: show an image, let the tech tap a point on it, hand the
 * tap back as percent-of-natural-size coordinates. Who supplies the image and
 * what happens to the tap is the caller's business —
 *   photo_tap_crop.js    upload forms, writes hidden inputs posted with the job
 *   photo_crop_detail.js repair detail page, POSTs the tap on its own
 *   multi_break.js       one tap per break, kept in the breaks[] JS state
 *
 * Percent (not pixels) is the whole trick: the tap means the same point no
 * matter what size the image was displayed at. See
 * docs/strategy/PHOTO_ML_SESSIONS.md.
 *
 * ES5 on purpose, same as image_compress.js — old field phones.
 */
(function () {
    'use strict';

    var modal, img, marker, title, hint, confirmBtn;
    var pending = null;      // {x, y} percent, set by a tap
    var onConfirm = null;
    var ready = false;
    var defaultConfirmLabel = 'Save close-up';

    var DEFAULT_HINT = "Tap the damage so we can save a close-up with this job. " +
                       "Skip if you're in a hurry.";

    function resetMarker() {
        pending = null;
        if (marker) marker.classList.add('hidden');
        if (confirmBtn) confirmBtn.disabled = true;
    }

    function placeMarker(e) {
        var rect = img.getBoundingClientRect();
        if (!rect.width || !rect.height) return;
        var xPct = Math.min(Math.max((e.clientX - rect.left) / rect.width * 100, 0), 100);
        var yPct = Math.min(Math.max((e.clientY - rect.top) / rect.height * 100, 0), 100);
        showMarkerAt(xPct, yPct);
    }

    function showMarkerAt(xPct, yPct) {
        pending = { x: xPct, y: yPct };
        // The image is centered in its container; position the marker
        // relative to the image's box inside that container.
        marker.style.left = (img.offsetLeft + xPct / 100 * img.offsetWidth) + 'px';
        marker.style.top = (img.offsetTop + yPct / 100 * img.offsetHeight) + 'px';
        marker.classList.remove('hidden');
        confirmBtn.disabled = false;
    }

    function confirmTap() {
        if (!pending || !onConfirm) return;
        var handler = onConfirm;
        var tap = pending;
        onConfirm = null;
        if (window.UI && UI.closeModal) UI.closeModal(modal);
        handler(tap.x, tap.y);
    }

    function init() {
        modal = document.getElementById('photoCropModal');
        if (!modal) return;
        img = document.getElementById('photoCropImage');
        marker = document.getElementById('photoCropMarker');
        title = document.getElementById('photoCropTitle');
        hint = document.getElementById('photoCropHint');
        confirmBtn = document.getElementById('photoCropConfirm');
        if (!img || !marker || !title || !confirmBtn) return;

        // One pointer path covers mouse and touch alike (see schedule_swap.js);
        // click is the fallback for WebViews without pointer events.
        if (window.PointerEvent) {
            img.addEventListener('pointerdown', placeMarker);
        } else {
            img.addEventListener('click', placeMarker);
        }
        confirmBtn.addEventListener('click', confirmTap);
        defaultConfirmLabel = confirmBtn.textContent;
        ready = true;
    }

    window.PhotoCropModal = {
        /** Is the modal partial on this page and wired up? */
        available: function () {
            return ready;
        },

        /**
         * Show `opts.src` and call `opts.onConfirm(xPct, yPct)` if the tech
         * taps and confirms. Closing, skipping or a src that won't decode
         * (HEIC off Safari) just calls `opts.onSkip` — never onConfirm.
         *
         *   src           image URL or object URL
         *   title         heading, e.g. "Tap the break"
         *   hint          sub-line; omitted falls back to the default
         *   confirmLabel  button text; omitted keeps the template's
         *   at            {x, y} percent to pre-place the marker (re-crop)
         */
        open: function (opts) {
            if (!ready || !opts || !opts.src) return false;
            resetMarker();
            onConfirm = opts.onConfirm || null;
            title.textContent = opts.title || 'Tap the break';
            if (hint) hint.textContent = opts.hint || DEFAULT_HINT;
            // Always reassign — the modal is shared, so last call's
            // label would otherwise stick.
            confirmBtn.textContent = opts.confirmLabel || defaultConfirmLabel;

            img.onload = function () {
                if (window.UI && UI.openModal) UI.openModal('photoCropModal');
                // A re-crop opens on the previous tap so "it's a bit left of
                // that" is a nudge, not a fresh hunt for the break.
                if (opts.at && typeof opts.at.x === 'number') {
                    showMarkerAt(opts.at.x, opts.at.y);
                }
            };
            img.onerror = function () {
                onConfirm = null;
                if (opts.onSkip) opts.onSkip();
            };
            img.src = opts.src;
            return true;
        }
    };

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
