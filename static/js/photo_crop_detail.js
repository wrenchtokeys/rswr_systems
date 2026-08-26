/**
 * Crop / re-crop a repair photo from the detail page.
 *
 * The upload forms capture the tap alongside the photo; this covers
 * everything they can't — a prompt that got skipped, a customer-submitted
 * photo, a photo from before tap-to-crop existed, or a mark that landed off
 * the break. The tap POSTs on its own to save_photo_crop and the thumbnail
 * updates in place; nothing else on the page is touched.
 *
 * Markup comes from partials/photo_crop_control.html; the modal from
 * photo_crop_modal.js, which must load first.
 *
 * ES5 on purpose, same as the rest of the tap-to-crop code.
 */
(function () {
    'use strict';

    var endpoint = null;
    var csrfToken = null;

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

    function send(button, field, xPct, yPct) {
        var body = new FormData();
        body.append('source_field', field);
        body.append('center_x_pct', xPct.toFixed(2));
        body.append('center_y_pct', yPct.toFixed(2));

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
        PhotoCropModal.open({
            src: button.getAttribute('data-crop-src'),
            title: button.getAttribute('data-crop-title') || 'Tap the break',
            hint: 'Tap the damage to save a close-up alongside this photo.',
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
    }

    function init() {
        var root = document.getElementById('photoCropEndpoint');
        if (!root) return;
        endpoint = root.getAttribute('data-endpoint');
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
