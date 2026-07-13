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
 *   Confirm:  <form data-confirm="Are you sure?"> shows a native confirm() before submit.
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
