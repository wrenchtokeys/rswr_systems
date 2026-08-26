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
 * photo_backfill.js is a fourth consumer of a different kind: it captures
 * taps on its own full-page image rather than in this modal, and borrows
 * only percentFromEvent so a tap there means what a tap here means.
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
    var pending = null;      // {x, y} percent, wherever the marker sits
    var tapped = false;      // ...and whether a finger put it there
    var onConfirm = null;
    var ready = false;
    var defaultConfirmLabel = 'Save close-up';
    // Bumped on every open(). A suggestion that arrives after the tech has
    // moved on to another photo carries a stale id and is dropped, which is
    // why suggest() takes one — see photo_crop_detail.js.
    var session = 0;
    var lateSuggestion = null;   // arrived before the image finished loading

    var DEFAULT_HINT = "Tap the damage so we can save a close-up with this job. " +
                       "Skip if you're in a hurry.";

    function resetMarker() {
        pending = null;
        tapped = false;
        lateSuggestion = null;
        if (marker) marker.classList.add('hidden');
        if (confirmBtn) confirmBtn.disabled = true;
    }

    /**
     * Where on the image did that pointer land, in percent of its rendered
     * box? Exported below as PhotoCropModal.percentFromEvent because the
     * backfill queue (P4a.1) taps a full-page image rather than this modal
     * and must mean the same thing by a tap — see PHOTO_ML_SESSIONS.md on
     * the percent-of-EXIF-upright convention.
     */
    function percentFromEvent(image, e) {
        var rect = image.getBoundingClientRect();
        if (!rect.width || !rect.height) return null;
        return {
            x: Math.min(Math.max((e.clientX - rect.left) / rect.width * 100, 0), 100),
            y: Math.min(Math.max((e.clientY - rect.top) / rect.height * 100, 0), 100)
        };
    }

    function placeMarker(e) {
        var point = percentFromEvent(img, e);
        if (!point) return;
        tapped = true;
        showMarkerAt(point.x, point.y);
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
         *
         * Returns a session token for suggest()/setHint(), or false if the
         * modal isn't on this page.
         */
        open: function (opts) {
            if (!ready || !opts || !opts.src) return false;
            resetMarker();
            session += 1;
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
                } else if (lateSuggestion) {
                    // The suggestion beat the image here. Marker positions
                    // are read off the rendered <img>, so it had to wait.
                    showMarkerAt(lateSuggestion.x, lateSuggestion.y);
                    lateSuggestion = null;
                }
            };
            img.onerror = function () {
                onConfirm = null;
                if (opts.onSkip) opts.onSkip();
            };
            img.src = opts.src;
            return session;
        },

        /**
         * Pre-place the marker on a machine-suggested point.
         *
         * Never overrides the technician: if they have already tapped, or
         * the modal has moved on to a different photo, this does nothing and
         * returns false. The tech is always free to tap over the suggestion.
         */
        suggest: function (token, xPct, yPct) {
            if (!ready || token !== session || tapped) return false;
            if (typeof xPct !== 'number' || typeof yPct !== 'number') return false;
            if (!img.complete || !img.offsetWidth) {
                lateSuggestion = { x: xPct, y: yPct };
                return true;
            }
            showMarkerAt(xPct, yPct);
            return true;
        },

        /**
         * Percent-of-rendered-image coordinates for a pointer event, or
         * null if the image has no box yet. Pure — it needs no modal on the
         * page, so a surface that captures a tap without this modal (the
         * backfill queue) can still share the one conversion.
         */
        percentFromEvent: percentFromEvent,

        /** Replace the sub-line, if this is still the same open modal. */
        setHint: function (token, text) {
            if (!ready || token !== session || !hint) return false;
            hint.textContent = text;
            return true;
        }
    };

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
