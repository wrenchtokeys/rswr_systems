/**
 * Tap-to-crop for repair damage photos.
 *
 * After a photo lands in an input[data-tap-crop] (image_compress.js and
 * repair_form.js dispatch `photocrop:offer` once compression finishes),
 * this opens #photoCropModal with the full image and asks the tech to tap
 * the break. The tap is written as percent coordinates into hidden
 * crop_x_<field>/crop_y_<field> inputs and the server crops around it on
 * save. Entirely optional — Skip, Escape or the overlay just close the
 * modal and the photo uploads exactly as before.
 *
 * ES5 on purpose, same as image_compress.js — old field phones.
 */
(function () {
    'use strict';

    var modal, img, marker, title, hint, confirmBtn;
    var activeField = null;   // e.g. 'damage_photo_before'
    var pending = null;       // {x, y} percent, set by a tap
    var objectUrl = null;

    var PROMPTS = {
        damage_photo_before: 'Tap the break',
        damage_photo_after: 'Tap the repaired spot',
        customer_submitted_photo: 'Tap the break'
    };

    function coordInput(axis, field) {
        return document.getElementById('crop_' + axis + '_' + field);
    }

    function clearCoords(field) {
        if (!field) return;
        var x = coordInput('x', field);
        var y = coordInput('y', field);
        if (x) x.value = '';
        if (y) y.value = '';
    }

    function releaseUrl() {
        if (objectUrl) {
            URL.revokeObjectURL(objectUrl);
            objectUrl = null;
        }
    }

    function resetMarker() {
        pending = null;
        if (marker) marker.classList.add('hidden');
        if (confirmBtn) confirmBtn.disabled = true;
    }

    function serviceTypeAllows() {
        // Job form: only repairs get a crop. The old repair form has no
        // service_type input, so absence means proceed.
        var checked = document.querySelector('input[name="service_type"]:checked');
        if (checked) return checked.value === 'repair';
        var single = document.querySelector('select[name="service_type"], input[name="service_type"]');
        if (single && single.value) return single.value === 'repair';
        return true;
    }

    function offer(input, file) {
        var field = input.getAttribute('data-tap-crop');
        if (!field || !file) return;
        // A new photo invalidates any previous tap for this field; coords
        // are only ever written back on an explicit Confirm.
        clearCoords(field);
        if (!serviceTypeAllows()) return;

        releaseUrl();
        resetMarker();
        activeField = field;
        title.textContent = PROMPTS[field] || PROMPTS.damage_photo_before;

        objectUrl = URL.createObjectURL(file);
        img.onload = function () {
            if (window.UI && UI.openModal) UI.openModal('photoCropModal');
        };
        img.onerror = function () {
            // HEIC on a browser that can't render it (anything but Safari):
            // no tap, photo still uploads untouched.
            releaseUrl();
            activeField = null;
        };
        img.src = objectUrl;
    }

    function placeMarker(e) {
        var rect = img.getBoundingClientRect();
        if (!rect.width || !rect.height) return;
        var clientX = e.clientX;
        var clientY = e.clientY;
        var xPct = Math.min(Math.max((clientX - rect.left) / rect.width * 100, 0), 100);
        var yPct = Math.min(Math.max((clientY - rect.top) / rect.height * 100, 0), 100);
        pending = { x: xPct, y: yPct };

        // The image is centered in its container; position the marker
        // relative to the image's box inside that container.
        marker.style.left = (img.offsetLeft + xPct / 100 * img.offsetWidth) + 'px';
        marker.style.top = (img.offsetTop + yPct / 100 * img.offsetHeight) + 'px';
        marker.classList.remove('hidden');
        confirmBtn.disabled = false;
    }

    function confirmTap() {
        if (!pending || !activeField) return;
        var x = coordInput('x', activeField);
        var y = coordInput('y', activeField);
        if (x) x.value = pending.x.toFixed(2);
        if (y) y.value = pending.y.toFixed(2);
        releaseUrl();
        activeField = null;
        if (window.UI && UI.closeModal) UI.closeModal(modal);
    }

    function init() {
        modal = document.getElementById('photoCropModal');
        if (!modal) return;
        if (!document.querySelector('input[data-tap-crop]')) return;

        img = document.getElementById('photoCropImage');
        marker = document.getElementById('photoCropMarker');
        title = document.getElementById('photoCropTitle');
        hint = document.getElementById('photoCropHint');
        confirmBtn = document.getElementById('photoCropConfirm');
        if (!img || !marker || !title || !confirmBtn) return;

        document.addEventListener('photocrop:offer', function (e) {
            var input = e.target;
            if (!input || !input.getAttribute || !input.getAttribute('data-tap-crop')) return;
            offer(input, e.detail && e.detail.file);
        });

        // One pointer path covers mouse and touch alike (see schedule_swap.js);
        // click is the fallback for WebViews without pointer events.
        if (window.PointerEvent) {
            img.addEventListener('pointerdown', placeMarker);
        } else {
            img.addEventListener('click', placeMarker);
        }

        confirmBtn.addEventListener('click', confirmTap);
    }

    // The photo "Remove" buttons clear their input programmatically (no
    // change event fires), so image_compress.js / repair_form.js call this
    // to drop the tap along with the photo.
    window.PhotoTapCrop = {
        clear: function (input) {
            var field = input && input.getAttribute && input.getAttribute('data-tap-crop');
            if (field) clearCoords(field);
        }
    };

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
