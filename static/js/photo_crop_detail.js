/**
 * Crop / re-crop a repair photo from the detail page.
 *
 * The upload forms capture the tap alongside the photo; this covers
 * everything they can't — a prompt that got skipped, a customer-submitted
 * photo, a photo from before tap-to-crop existed, or a mark that landed off
 * the break. The tap POSTs on its own to save_photo_crop and the thumbnail
 * updates in place; nothing else on the page is touched.
 *
 * For a photo nobody has marked yet, the modal opens and *then* asks the
 * server to guess where the break is (P3). The guess is never blocking and
 * never binding — see askForSuggestion.
 *
 * Markup comes from partials/photo_crop_control.html; the modal from
 * photo_crop_modal.js, which must load first.
 *
 * ES5 on purpose, same as the rest of the tap-to-crop code.
 */
(function () {
    'use strict';

    var endpoint = null;
    var suggestEndpoint = null;
    var csrfToken = null;

    // How long a suggestion gets before the tech is left to tap unaided.
    // The modal is already open and usable the whole time — this only
    // decides when we stop waiting for a marker.
    var SUGGEST_TIMEOUT_MS = 3000;

    var DEFAULT_HINT = 'Tap the damage to save a close-up alongside this photo.';

    function toast(message, level) {
        if (window.UI && typeof UI.toast === 'function') {
            UI.toast(message, level || 'info');
        }
    }

    function refreshThumb(button, field, url) {
        var wrap = button.parentNode;
        var thumb = wrap.querySelector('[data-crop-thumb="' + field + '"]');
        if (!thumb) {
            thumb = document.createElement('img');
            thumb.className =
                'h-10 w-10 rounded object-cover border border-gray-200 shrink-0';
            thumb.alt = 'Saved close-up of the break';
            thumb.setAttribute('data-crop-thumb', field);
            wrap.insertBefore(thumb, button);
        }
        // Cache-bust: the crop replaces the file at a name the browser has
        // already cached from the previous tap.
        thumb.src = url + (url.indexOf('?') === -1 ? '?' : '&') + 't=' + new Date().getTime();
    }

    /**
     * Ask the server where it thinks the break is and drop a marker there.
     *
     * The modal is already open by the time this runs — a suggestion must
     * never be something the tech waits on. If it is slow, wrong, or the
     * server declines to guess, they tap exactly as they did before P3.
     * The suggestion is remembered on the button so that confirming posts
     * it back: the gap between it and the final mark is how we find out
     * whether any of this is working.
     */
    function askForSuggestion(button, field, token) {
        if (!suggestEndpoint) return;
        var body = new FormData();
        body.append('source_field', field);

        var settled = false;
        var timer = setTimeout(function () {
            if (settled) return;
            settled = true;
            PhotoCropModal.setHint(token, DEFAULT_HINT);
        }, SUGGEST_TIMEOUT_MS);

        fetch(suggestEndpoint, {
            method: 'POST',
            headers: { 'X-CSRFToken': csrfToken, 'X-Requested-With': 'XMLHttpRequest' },
            body: body,
            credentials: 'same-origin'
        }).then(function (response) {
            return response.json().catch(function () { return {}; });
        }).then(function (data) {
            if (settled) return;
            settled = true;
            clearTimeout(timer);
            if (!data || !data.found) {
                PhotoCropModal.setHint(token, DEFAULT_HINT);
                return;
            }
            if (!PhotoCropModal.suggest(token, data.x_pct, data.y_pct)) return;
            button.setAttribute('data-crop-suggested-x', data.x_pct);
            button.setAttribute('data-crop-suggested-y', data.y_pct);
            button.setAttribute('data-crop-suggested-by', data.engine || '');
            button.setAttribute('data-crop-suggested-score', data.score);
            PhotoCropModal.setHint(
                token,
                "We think the break is here — tap to move the mark if it's off."
            );
        }).catch(function () {
            if (settled) return;
            settled = true;
            clearTimeout(timer);
            PhotoCropModal.setHint(token, DEFAULT_HINT);
        });
    }

    function send(button, field, xPct, yPct) {
        var body = new FormData();
        body.append('source_field', field);
        body.append('center_x_pct', xPct.toFixed(2));
        body.append('center_y_pct', yPct.toFixed(2));
        // Echo the suggestion back so the row records what was offered
        // next to what the technician settled on.
        var suggestedBy = button.getAttribute('data-crop-suggested-by');
        if (suggestedBy) {
            body.append('suggested_x_pct', button.getAttribute('data-crop-suggested-x'));
            body.append('suggested_y_pct', button.getAttribute('data-crop-suggested-y'));
            body.append('suggested_by', suggestedBy);
            body.append('suggestion_score', button.getAttribute('data-crop-suggested-score'));
        }

        button.disabled = true;
        fetch(endpoint, {
            method: 'POST',
            headers: { 'X-CSRFToken': csrfToken, 'X-Requested-With': 'XMLHttpRequest' },
            body: body,
            credentials: 'same-origin'
        }).then(function (response) {
            return response.json().catch(function () { return {}; });
        }).then(function (data) {
            button.disabled = false;
            if (!data || !data.success) {
                toast((data && data.error) || "Couldn't save that close-up.", 'error');
                return;
            }
            button.innerHTML = '<i class="fas fa-crosshairs mr-1"></i>Move the mark';
            // A human has now vouched for this mark, so drop the note that
            // says a machine placed it.
            var guessed = document.querySelector('[data-crop-unconfirmed="' + field + '"]');
            if (guessed) guessed.parentNode.removeChild(guessed);
            var pending = document.querySelector('[data-crop-pending="' + field + '"]');
            if (data.crop_url) {
                refreshThumb(button, field, data.crop_url);
                if (pending) pending.parentNode.removeChild(pending);
                toast('Close-up saved.', 'success');
            } else {
                // The tap is on record but the original wouldn't open;
                // retry_photo_crops picks it up later.
                toast('Mark saved — the close-up will follow.', 'info');
            }
        }).catch(function () {
            button.disabled = false;
            toast("Couldn't save that close-up.", 'error');
        });
    }

    function onClick(e) {
        var button = e.target.closest ? e.target.closest('[data-crop-field]') : null;
        if (!button) return;
        e.preventDefault();
        if (!window.PhotoCropModal || !PhotoCropModal.available()) return;

        var field = button.getAttribute('data-crop-field');
        var at = null;
        var atX = button.getAttribute('data-crop-at-x');
        if (atX !== null && atX !== '') {
            at = { x: parseFloat(atX), y: parseFloat(button.getAttribute('data-crop-at-y')) };
        }
        // Only an unmarked photo gets a suggestion. Once a human has
        // marked it, their mark is the truth and the modal reopens on it.
        var wantSuggestion = at === null;
        var token = PhotoCropModal.open({
            src: button.getAttribute('data-crop-src'),
            title: button.getAttribute('data-crop-title') || 'Tap the break',
            hint: wantSuggestion ? 'Looking for the break…' : DEFAULT_HINT,
            at: at,
            onConfirm: function (xPct, yPct) {
                button.setAttribute('data-crop-at-x', xPct.toFixed(2));
                button.setAttribute('data-crop-at-y', yPct.toFixed(2));
                send(button, field, xPct, yPct);
            },
            onSkip: function () {
                toast("That photo won't display here, so it can't be marked.", 'warning');
            }
        });
        if (token && wantSuggestion) {
            askForSuggestion(button, field, token);
        }
    }

    function init() {
        var root = document.getElementById('photoCropEndpoint');
        if (!root) return;
        endpoint = root.getAttribute('data-endpoint');
        suggestEndpoint = root.getAttribute('data-suggest-endpoint');
        var csrf = document.querySelector('input[name="csrfmiddlewaretoken"]');
        csrfToken = csrf ? csrf.value : '';
        document.addEventListener('click', onClick);
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
