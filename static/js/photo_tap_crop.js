/**
 * Tap-to-crop on the upload forms (job form, old repair form).
 *
 * After a photo lands in an input[data-tap-crop] (image_compress.js and
 * repair_form.js dispatch `photocrop:offer` once compression finishes),
 * this asks PhotoCropModal for the tap and writes it as percent
 * coordinates into hidden crop_x_<field>/crop_y_<field> inputs. The server
 * crops around them when the form saves. Entirely optional — Skip, Escape
 * or the overlay just close the modal and the photo uploads as before.
 *
 * The modal mechanics live in photo_crop_modal.js, which must load first.
 *
 * ES5 on purpose, same as image_compress.js — old field phones.
 */
(function () {
    'use strict';

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
        if (!window.PhotoCropModal || !PhotoCropModal.available()) return;

        releaseUrl();
        objectUrl = URL.createObjectURL(file);
        PhotoCropModal.open({
            src: objectUrl,
            title: PROMPTS[field] || PROMPTS.damage_photo_before,
            onConfirm: function (xPct, yPct) {
                var x = coordInput('x', field);
                var y = coordInput('y', field);
                if (x) x.value = xPct.toFixed(2);
                if (y) y.value = yPct.toFixed(2);
                releaseUrl();
            },
            onSkip: function () {
                // HEIC on a browser that can't render it (anything but
                // Safari): no tap, photo still uploads untouched.
                releaseUrl();
            }
        });
    }

    function init() {
        if (!document.querySelector('input[data-tap-crop]')) return;

        document.addEventListener('photocrop:offer', function (e) {
            var input = e.target;
            if (!input || !input.getAttribute || !input.getAttribute('data-tap-crop')) return;
            offer(input, e.detail && e.detail.file);
        });
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
