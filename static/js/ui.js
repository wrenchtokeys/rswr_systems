/**
 * Shared UI helpers (vanilla JS, no dependencies).
 * Replaces the dead Bootstrap data-bs-* patterns. See docs/development/UI_DESIGN_GUIDE.md.
 *
 * Markup contracts:
 *   Modal:    trigger [data-modal-open="modalId"], modal container is `.hidden` by default;
 *             close via [data-modal-close] inside the modal, Escape, or clicking the overlay
 *             (element with [data-modal-overlay]).
 *   Dropdown: trigger [data-dropdown-toggle="menuId"]; menu starts `.hidden`;
 *             closes on outside click or Escape.
 *   Confirm:  <form data-confirm="Are you sure?"> shows a branded confirm dialog before
 *             submit. Optional: data-confirm-title, data-confirm-label (confirm button
 *             text), data-confirm-danger (red confirm button for destructive actions).
 *   Toasts:   UI.toast(message, type) — type: success | error | warning | info.
 *             UI.flash(message, type) stores the toast and shows it after the next
 *             page load (use right before location.reload() / navigation).
 *             UI.confirm({title, message, confirmLabel, danger}) -> Promise<boolean>.
 *   Tabs:     nav [data-tabs data-tabs-default="name"] with buttons [data-tab="name"]
 *             (.tab-btn); panels [data-tab-panel="name"]. Active button gets
 *             .tab-btn-active, other panels get `.hidden`; ?tab= is kept in the URL
 *             so server-side active_tab deep links keep working.
 */
(function () {
    'use strict';

    // --- Modals -------------------------------------------------------------
    function openModal(id) {
        var modal = document.getElementById(id);
        if (!modal) return;
        modal.classList.remove('hidden');
        document.body.classList.add('overflow-hidden');
        var focusable = modal.querySelector('input, select, textarea, button, [href]');
        if (focusable) focusable.focus();
    }

    function closeModal(modal) {
        if (!modal) return;
        modal.classList.add('hidden');
        document.body.classList.remove('overflow-hidden');
    }

    // --- Event delegation (works for dynamically-inserted markup) -----------
    document.addEventListener('click', function (e) {
        var opener = e.target.closest('[data-modal-open]');
        if (opener) {
            e.preventDefault();
            // Close any open dropdown (e.g. when the opener lives in an overflow menu)
            document.querySelectorAll('[data-dropdown-menu]:not(.hidden)').forEach(function (m) {
                m.classList.add('hidden');
            });
            openModal(opener.getAttribute('data-modal-open'));
            return;
        }

        var closer = e.target.closest('[data-modal-close]');
        if (closer) {
            e.preventDefault();
            closeModal(closer.closest('[data-modal], .modal-overlay') || closer.closest('[id]'));
            return;
        }

        // Click on the overlay backdrop itself closes the modal
        if (e.target.hasAttribute && e.target.hasAttribute('data-modal-overlay')) {
            closeModal(e.target.closest('[data-modal], .modal-overlay') || e.target);
            return;
        }

        var toggle = e.target.closest('[data-dropdown-toggle]');
        if (toggle) {
            e.preventDefault();
            var menu = document.getElementById(toggle.getAttribute('data-dropdown-toggle'));
            if (menu) {
                // Close other open dropdowns first
                document.querySelectorAll('[data-dropdown-menu]:not(.hidden)').forEach(function (m) {
                    if (m !== menu) m.classList.add('hidden');
                });
                menu.classList.toggle('hidden');
            }
            return;
        }

        // Outside click closes open dropdowns
        document.querySelectorAll('[data-dropdown-menu]:not(.hidden)').forEach(function (menu) {
            if (!menu.contains(e.target)) menu.classList.add('hidden');
        });
    });

    document.addEventListener('keydown', function (e) {
        if (e.key !== 'Escape') return;
        document.querySelectorAll('[data-dropdown-menu]:not(.hidden)').forEach(function (menu) {
            menu.classList.add('hidden');
        });
        var openOverlay = document.querySelector('.modal-overlay:not(.hidden), [data-modal]:not(.hidden)');
        if (openOverlay) closeModal(openOverlay);
    });

    // --- Tabs ----------------------------------------------------------------
    function activateTab(name) {
        document.querySelectorAll('[data-tab]').forEach(function (btn) {
            btn.classList.toggle('tab-btn-active', btn.getAttribute('data-tab') === name);
        });
        document.querySelectorAll('[data-tab-panel]').forEach(function (panel) {
            panel.classList.toggle('hidden', panel.getAttribute('data-tab-panel') !== name);
        });
        var url = new URL(window.location);
        url.searchParams.set('tab', name);
        history.replaceState(null, '', url);
    }

    document.addEventListener('click', function (e) {
        var tabBtn = e.target.closest('[data-tab]');
        if (tabBtn) {
            e.preventDefault();
            activateTab(tabBtn.getAttribute('data-tab'));
        }
    });

    document.addEventListener('DOMContentLoaded', function () {
        var tabs = document.querySelector('[data-tabs]');
        if (tabs && tabs.getAttribute('data-tabs-default')) {
            activateTab(tabs.getAttribute('data-tabs-default'));
        }
    });

    // --- Confirm-before-submit ----------------------------------------------
    document.addEventListener('submit', function (e) {
        var form = e.target.closest('form[data-confirm]');
        if (form && !window.confirm(form.getAttribute('data-confirm'))) {
            e.preventDefault();
        }
    });

    // Expose for programmatic use
    window.UI = { openModal: openModal, closeModal: closeModal };
})();
