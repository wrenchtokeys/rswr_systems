/*
 * The one-time "put RS Systems on your home screen" card.
 *
 * Markup: templates/includes/install_hint.html (ships hidden). This script
 * decides whether there is anything to offer:
 *
 *   iOS       never prompts, and the option is buried in the Share sheet, so
 *             the card says where it is.
 *   Chromium  fires `beforeinstallprompt`; the card gets a real Install button.
 *   Others    nothing to offer — the card stays hidden.
 *
 * It never shows inside the installed app, and never again on this device once
 * it has been dismissed or the app installed. That memory is localStorage: a
 * per-device convenience, so if storage is blocked the card simply comes back.
 */
(function () {
    'use strict';

    var hint = document.getElementById('install-hint');
    if (!hint) { return; }

    var KEY = 'rs:install-hint-done';

    function done() {
        try { return window.localStorage.getItem(KEY) === '1'; } catch (e) { return false; }
    }
    function finish() {
        hint.classList.add('hidden');
        try { window.localStorage.setItem(KEY, '1'); } catch (e) { /* comes back next time */ }
    }
    function show(selector) {
        hint.querySelector(selector).classList.remove('hidden');
        hint.classList.remove('hidden');
    }

    var installed = window.matchMedia('(display-mode: standalone)').matches ||
        window.navigator.standalone === true;
    if (installed || done()) { return; }

    hint.querySelector('[data-install-dismiss]').addEventListener('click', finish);
    window.addEventListener('appinstalled', finish);

    // iPadOS reports itself as a Mac; the touch points give it away.
    var ua = window.navigator.userAgent;
    var ios = /iPhone|iPad|iPod/.test(ua) ||
        (window.navigator.platform === 'MacIntel' && window.navigator.maxTouchPoints > 1);
    if (ios) {
        show('[data-install-ios]');
        return;
    }

    var deferred = null;
    var accept = hint.querySelector('[data-install-accept]');

    window.addEventListener('beforeinstallprompt', function (event) {
        // Keep the event: prompt() may only be called from a user gesture.
        event.preventDefault();
        deferred = event;
        accept.classList.remove('hidden');
        show('[data-install-prompt]');
    });

    accept.addEventListener('click', function () {
        if (!deferred) { return; }
        deferred.prompt();
        deferred.userChoice.then(finish);
        deferred = null;
    });
})();
