/**
 * Interactive first-run tours (driver.js, vendored — static/js/vendor/driver.iife.js).
 *
 * A page opts in by putting data-tour="<slug>" on any element; the server only
 * renders that attribute while the tour is uncompleted for the tenant. When the
 * tour ends — finished OR closed early — we POST /owner/tours/<slug>/complete/
 * so it never re-nags (skip counts as done).
 *
 * Adding a tour: add a definition here AND add the slug to TOUR_SLUGS in
 * apps/saas/views.py (unknown slugs 404 on the completion endpoint).
 */
(function () {
    'use strict';

    var TOURS = {
        'owner-dashboard': {
            steps: [
                {
                    popover: {
                        title: 'Welcome to your shop 👋',
                        description: 'This dashboard is your home base. A quick tour takes about 30 seconds — skip any time and we won’t show it again.'
                    }
                },
                {
                    element: '[data-tour-step="revenue"]',
                    popover: {
                        title: 'Your money, front and center',
                        description: 'Revenue this month lives up top. Every completed job adds to it automatically.'
                    }
                },
                {
                    element: '[data-tour-step="stats"]',
                    popover: {
                        title: 'Jobs, team, and customers',
                        description: 'A live count of this month’s work. If you get close to a plan limit, a bar appears here before anything blocks.'
                    }
                },
                {
                    element: '[data-tour-step="quick-actions"]',
                    popover: {
                        title: 'Start anything in one click',
                        description: 'New repair, new replacement, new customer — the things you do every day are always one click from here.'
                    }
                },
                {
                    element: '[data-tour-step="checklist"]',
                    popover: {
                        title: 'Finish setting up',
                        description: 'Each item links straight to the right setting. Knock these out once and invoices, taxes, and pricing take care of themselves.'
                    }
                },
                {
                    element: '[data-tour-step="recent-activity"]',
                    popover: {
                        title: 'Everything shows up here',
                        description: 'Every job your shop touches lands in this feed, newest first.',
                        side: 'top'
                    }
                },
                {
                    popover: {
                        title: 'You’re ready',
                        description: 'Stuck on anything? Open Help from your profile menu (top right) — short plain-language guides for every task.'
                    }
                }
            ]
        },
        'job-form': {
            steps: [
                {
                    popover: {
                        title: 'Log a job in under a minute',
                        description: 'This one form handles the whole job — who, what, and the price. Here’s the 20-second version.'
                    }
                },
                {
                    element: '#type-toggle',
                    popover: {
                        title: 'Repair or replacement?',
                        description: 'Pick the kind of work. The form adjusts to match.'
                    }
                },
                {
                    element: '#customer-block',
                    popover: {
                        title: 'Who’s it for?',
                        description: 'Pick a fleet account or an individual. New walk-in? Add them right here — no separate customer screen first.'
                    }
                },
                {
                    element: '#id_price',
                    popover: {
                        title: 'Pricing is automatic',
                        description: 'Leave the price blank on a repair and your price book fills it in. Type a number any time to override.'
                    }
                },
                {
                    element: '#save-send-btn',
                    popover: {
                        title: 'Save & Send Invoice',
                        description: 'One tap completes the job AND emails the invoice. Or just save and invoice later — your call.',
                        side: 'top'
                    }
                },
                {
                    element: '#multi-break-link',
                    popover: {
                        title: 'More than one chip?',
                        description: 'Use Multi-break for several breaks on the same windshield — each one is priced progressively, automatically.',
                        side: 'top'
                    }
                }
            ]
        }
    };

    function visible(el) {
        return !!(el && (el.offsetWidth || el.offsetHeight || el.getClientRects().length));
    }

    document.addEventListener('DOMContentLoaded', function () {
        var host = document.querySelector('[data-tour]');
        if (!host) return;
        var slug = host.getAttribute('data-tour');
        var def = TOURS[slug];
        if (!def || typeof window.driver === 'undefined' || !window.driver.js) return;

        // Drop steps whose target is missing or hidden (mobile hides some
        // desktop-only sections) — a popover pointing at nothing is worse
        // than a shorter tour.
        var steps = def.steps.filter(function (s) {
            if (!s.element) return true;
            return visible(document.querySelector(s.element));
        });
        if (!steps.length) return;

        var reported = false;
        function markComplete() {
            if (reported) return;
            reported = true;
            fetch('/owner/tours/' + encodeURIComponent(slug) + '/complete/', {
                method: 'POST',
                headers: { 'X-CSRFToken': window.UI ? window.UI.csrfToken() : '' },
                credentials: 'same-origin'
            }).catch(function () { /* tour may re-offer next visit — harmless */ });
        }

        var tour = window.driver.js.driver({
            showProgress: steps.length > 2,
            animate: true,
            overlayOpacity: 0.55,
            stagePadding: 6,
            stageRadius: 12,
            nextBtnText: 'Next',
            prevBtnText: 'Back',
            doneBtnText: 'Done',
            steps: steps,
            onDestroyed: markComplete
        });

        // Small delay so layout/fonts settle before the first highlight.
        window.setTimeout(function () { tour.drive(); }, 500);
    });
})();
