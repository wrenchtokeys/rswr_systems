/**
 * Shrink damage photos in the browser before they are uploaded.
 *
 * Not a nicety. nginx and Django both cap a request at 10MB
 * (.platform/nginx/conf.d/client_max_body_size.conf,
 * DATA_UPLOAD_MAX_MEMORY_SIZE), and a job form posts a before AND an after
 * photo in the same request. Straight off a phone that is routinely over the
 * cap, and the tech gets a bare nginx 413 -- no form, no error message, the
 * whole job gone. The old repair form dodged this by compressing first; the
 * unified job form inherited the file inputs but not the compression, so
 * "New job" became the one path that could lose a job to a big photo.
 *
 * 2048px / 85% JPEG keeps damage detail readable while landing well under the
 * cap. HEIC is passed through untouched -- canvas cannot decode it, so the
 * server does that conversion.
 *
 * Two ways in:
 *   ImageCompressor.compress(file) -> Promise<File>   (used by the older forms)
 *   <input type="file" data-compress> auto-wires itself: validate, compress,
 *   and render a thumbnail into #<input id>_preview when that element exists.
 */
(function () {
    'use strict';

    var MAX_BYTES = 10 * 1024 * 1024;   // matches the nginx/Django request cap
    var SKIP_BELOW = 500 * 1024;        // already small enough to leave alone
    var ALLOWED = ['image/jpeg', 'image/jpg', 'image/png', 'image/webp', 'image/heic'];

    var ImageCompressor = {
        MAX_DIMENSION: 2048,   // max width or height, in pixels
        QUALITY: 0.85,         // JPEG quality (0-1)

        /**
         * @param {File} file
         * @returns {Promise<File>} the compressed file, or the original if it
         *   is already small, is HEIC, or anything at all goes wrong.
         */
        compress: function (file) {
            return new Promise(function (resolve) {
                if (file.size < SKIP_BELOW) {
                    resolve(file);
                    return;
                }
                var name = (file.name || '').toLowerCase();
                if (name.endsWith('.heic') || name.endsWith('.heif')) {
                    // canvas can't decode HEIC; the server converts it.
                    resolve(file);
                    return;
                }

                var img = new Image();
                var canvas = document.createElement('canvas');
                var ctx = canvas.getContext('2d');

                img.onload = function () {
                    var width = img.width;
                    var height = img.height;
                    var maxDim = ImageCompressor.MAX_DIMENSION;

                    if (width > maxDim || height > maxDim) {
                        if (width > height) {
                            height = Math.round((height * maxDim) / width);
                            width = maxDim;
                        } else {
                            width = Math.round((width * maxDim) / height);
                            height = maxDim;
                        }
                    }

                    canvas.width = width;
                    canvas.height = height;
                    ctx.drawImage(img, 0, 0, width, height);

                    canvas.toBlob(
                        function (blob) {
                            if (!blob) {
                                resolve(file);   // fall back to the original
                                return;
                            }
                            resolve(new File(
                                [blob],
                                file.name.replace(/\.[^.]+$/, '.jpg'),
                                { type: 'image/jpeg' }
                            ));
                        },
                        'image/jpeg',
                        ImageCompressor.QUALITY
                    );
                };
                img.onerror = function () { resolve(file); };
                img.src = URL.createObjectURL(file);
            });
        },

        /** Put the compressed file back on the input so the form posts it. */
        replaceInputFile: function (input, compressedFile) {
            var dataTransfer = new DataTransfer();
            dataTransfer.items.add(compressedFile);
            input.files = dataTransfer.files;
        },

        formatSize: function (bytes) {
            if (!bytes) return '0 KB';
            var units = ['bytes', 'KB', 'MB', 'GB'];
            var i = Math.floor(Math.log(bytes) / Math.log(1024));
            return Math.round((bytes / Math.pow(1024, i)) * 10) / 10 + ' ' + units[i];
        },

        /** Reject what the server would reject anyway, while it's still fixable. */
        validate: function (file) {
            var name = (file.name || '').toLowerCase();
            var typeOk = ALLOWED.indexOf(file.type) !== -1 ||
                         name.endsWith('.heic') || name.endsWith('.heif');
            if (!typeOk) {
                return 'That file is not an image. Use a JPG, PNG, WebP or HEIC photo.';
            }
            // Only reachable for HEIC and other pass-through files, since
            // everything else has already been resized by here.
            if (file.size > MAX_BYTES) {
                return 'That photo is ' + ImageCompressor.formatSize(file.size) +
                       ' — too big to upload. Retake it at a lower resolution.';
            }
            return null;
        }
    };

    function notify(message) {
        if (window.UI && typeof window.UI.toast === 'function') {
            window.UI.toast(message, 'warning');
        } else {
            console.warn(message);
        }
    }

    function renderPreview(box, file, input) {
        box.textContent = '';
        box.classList.remove('hidden');

        var img = document.createElement('img');
        img.className = 'h-16 w-16 rounded-lg object-cover border border-gray-200 shrink-0';
        img.alt = '';
        var reader = new FileReader();
        reader.onload = function (e) { img.src = e.target.result; };
        reader.readAsDataURL(file);

        var meta = document.createElement('div');
        meta.className = 'min-w-0 flex-1';
        var size = document.createElement('p');
        size.className = 'text-xs text-gray-500';
        size.textContent = 'Ready to upload — ' + ImageCompressor.formatSize(file.size);
        meta.appendChild(size);

        var remove = document.createElement('button');
        remove.type = 'button';
        remove.className = 'text-xs font-medium text-red-600 hover:text-red-700 min-h-11 px-1';
        remove.textContent = 'Remove';
        remove.addEventListener('click', function () {
            input.value = '';
            box.textContent = '';
            box.classList.add('hidden');
            // Dropping the photo also drops any tap-to-crop tap on it.
            if (window.PhotoTapCrop) window.PhotoTapCrop.clear(input);
        });

        box.appendChild(img);
        box.appendChild(meta);
        box.appendChild(remove);
    }

    function busy(box) {
        if (!box) return;
        box.classList.remove('hidden');
        box.textContent = '';
        var p = document.createElement('p');
        p.className = 'text-xs text-gray-500';
        p.textContent = 'Preparing photo…';
        box.appendChild(p);
    }

    function wire(input) {
        if (input.dataset.compressWired === '1') return;
        input.dataset.compressWired = '1';

        var box = input.id ? document.getElementById(input.id + '_preview') : null;

        input.addEventListener('change', function () {
            if (!input.files || !input.files.length) {
                if (box) { box.textContent = ''; box.classList.add('hidden'); }
                return;
            }
            var original = input.files[0];

            var earlyError = ImageCompressor.validate(original);
            // A big JPEG/PNG is fine here -- compression below is what brings
            // it under the cap. Only a wrong file type is fatal up front.
            if (earlyError && !/too big/.test(earlyError)) {
                notify(earlyError);
                input.value = '';
                if (box) { box.textContent = ''; box.classList.add('hidden'); }
                return;
            }

            busy(box);
            ImageCompressor.compress(original).then(function (file) {
                var error = ImageCompressor.validate(file);
                if (error) {
                    notify(error);
                    input.value = '';
                    if (box) { box.textContent = ''; box.classList.add('hidden'); }
                    return;
                }
                if (file !== original) ImageCompressor.replaceInputFile(input, file);
                if (box) renderPreview(box, file, input);
                // Offer the photo to photo_tap_crop.js (if loaded) so the
                // tech can tap the break for a saved close-up.
                var offer;
                try {
                    offer = new CustomEvent('photocrop:offer', { detail: { file: file }, bubbles: true });
                } catch (e) {
                    offer = document.createEvent('CustomEvent');
                    offer.initCustomEvent('photocrop:offer', true, false, { file: file });
                }
                input.dispatchEvent(offer);
            });
        });
    }

    function wireAll(root) {
        var inputs = (root || document).querySelectorAll('input[type="file"][data-compress]');
        for (var i = 0; i < inputs.length; i++) wire(inputs[i]);
    }

    window.ImageCompressor = ImageCompressor;
    window.ImageCompressor.wireAll = wireAll;

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', function () { wireAll(); });
    } else {
        wireAll();
    }
})();
