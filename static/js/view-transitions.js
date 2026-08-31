/*
 * List -> detail continuity (UI_MAGIC_SESSIONS S10, UI_MAGIC_PLAN R4 #3).
 *
 * The animation itself is pure CSS (`@view-transition` in head_assets.html; the
 * rest in assets/css/input.css). The only
 * thing that needs script is WHICH row flies into the detail page's title:
 * `view-transition-name` has to be unique in the document, so the twenty rows
 * on a list page cannot all be named `vt-hero` up front — a duplicate name
 * makes the browser skip the transition entirely. So the name is applied to
 * one row, at the moment you click it, and removed again afterwards.
 *
 * Markup contract:
 *   [data-vt-key="<detail url>"]  the row / card being clicked
 *     [data-vt-hero]              the text inside it that morphs (the title)
 *   .vt-hero                      the detail page's <h1> (static, in CSS)
 *
 * Nothing here changes navigation: without JS, without View Transitions, or
 * with reduced motion, every link still just loads its page.
 */
(function () {
    'use strict';

    var ACTIVE = 'vt-hero-active';
    var STORE_KEY = 'rs:vt-hero';

    if (!('startViewTransition' in document)) { return; }
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) { return; }

    function clearHero() {
        // Live HTMLCollection: removing the class shortens it as we go.
        var marked = document.getElementsByClassName(ACTIVE);
        while (marked.length) {
            marked[0].style.viewTransitionName = '';
            marked[0].classList.remove(ACTIVE);
        }
    }

    function markHero(scope) {
        clearHero();
        if (!scope) { return; }
        var hero = scope.matches('[data-vt-hero]') ? scope : scope.querySelector('[data-vt-hero]');
        if (!hero) { return; }
        hero.style.viewTransitionName = 'vt-hero';
        hero.classList.add(ACTIVE);
    }

    function remember(key) {
        try { sessionStorage.setItem(STORE_KEY, key); } catch (err) { /* private mode */ }
    }

    function recall() {
        try { return sessionStorage.getItem(STORE_KEY); } catch (err) { return null; }
    }

    /*
     * Capture phase, and deliberately not limited to <a> clicks: the invoice
     * and job tables navigate from an inline `onclick="window.location=..."`
     * on the <tr>, which runs on bubble — too late to name anything by then.
     * Marking a row that turns out not to navigate (a checkbox, an open kebab)
     * is harmless: the next mark clears it, and an unmatched name just fades.
     */
    document.addEventListener('click', function (e) {
        var target = e.target;
        if (!target || !target.closest) { return; }
        var scope = target.closest('[data-vt-key]');
        if (!scope) { return; }
        markHero(scope);
        remember(scope.getAttribute('data-vt-key'));
    }, true);

    /*
     * The way back. `pagereveal` fires on the incoming document *before* its
     * snapshot is taken, which is the one moment a returning list page can
     * name the row it is about to receive the title back into.
     *
     * Two ways to know this is a return trip, because neither covers both:
     * "Back to Jobs" is an ordinary forward navigation (referrer is the detail
     * page), while the Back button is a traverse (referrer is whatever led to
     * the list in the first place, so it proves nothing).
     */
    window.addEventListener('pagereveal', function (e) {
        if (!e.viewTransition) { return; }
        var key = recall();
        if (!key) { return; }

        var cameBack = false;
        if (document.referrer) {
            try {
                cameBack = new URL(document.referrer, location.href).pathname === key;
            } catch (err) { /* opaque referrer */ }
        }
        var nav = window.navigation;
        if (!cameBack && nav && nav.activation && nav.activation.navigationType === 'traverse') {
            cameBack = true;
        }
        if (!cameBack) { return; }

        var scope = document.querySelector('[data-vt-key="' + (window.CSS && CSS.escape ? CSS.escape(key) : key) + '"]');
        if (!scope) { return; }
        markHero(scope);
        // Leave no stale name behind: a second one would abort the next
        // transition on this page.
        e.viewTransition.finished.then(clearHero, clearHero);
    });
})();
