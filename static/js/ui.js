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

    // --- Toasts ---------------------------------------------------------------
    var TOAST_ICONS = {
        success: 'fas fa-check-circle toast-icon-success',
        error: 'fas fa-exclamation-circle toast-icon-error',
        warning: 'fas fa-exclamation-triangle toast-icon-warning',
        info: 'fas fa-info-circle toast-icon-info'
    };
    var TOAST_TIMEOUTS = { success: 4000, info: 4000, warning: 6000, error: 8000 };

    function getToastStack() {
        var stack = document.getElementById('toast-stack');
        if (!stack) {
            stack = document.createElement('div');
            stack.id = 'toast-stack';
            stack.className = 'toast-stack';
            stack.setAttribute('aria-live', 'polite');
            document.body.appendChild(stack);
        }
        return stack;
    }

    function toast(message, type) {
        type = TOAST_ICONS[type] ? type : 'info';

        var el = document.createElement('div');
        el.className = 'toast';
        el.setAttribute('role', type === 'error' ? 'alert' : 'status');

        var icon = document.createElement('i');
        icon.className = TOAST_ICONS[type] + ' mt-0.5';
        el.appendChild(icon);

        var text = document.createElement('div');
        text.className = 'flex-1 whitespace-pre-line';
        text.textContent = String(message);
        el.appendChild(text);

        var close = document.createElement('button');
        close.type = 'button';
        close.className = 'text-gray-400 hover:text-gray-600 transition-colors';
        close.setAttribute('aria-label', 'Dismiss');
        close.innerHTML = '<i class="fas fa-times"></i>';
        el.appendChild(close);

        getToastStack().appendChild(el);
        // Force a style flush so the enter transition animates. (Not rAF: Chrome
        // throttles rAF in occluded windows, which would leave the toast at
        // opacity 0 forever.)
        void el.offsetWidth;
        el.classList.add('toast-show');

        function dismiss() {
            el.classList.remove('toast-show');
            setTimeout(function () { el.remove(); }, 300);
        }
        var timer = setTimeout(dismiss, TOAST_TIMEOUTS[type]);
        close.addEventListener('click', function () {
            clearTimeout(timer);
            dismiss();
        });
        return el;
    }

    // Toast that survives a reload/navigation — call right before location.reload().
    function flash(message, type) {
        try {
            sessionStorage.setItem('ui-flash', JSON.stringify({ m: String(message), t: type }));
        } catch (e) {
            /* storage unavailable — the reload just won't show a toast */
        }
    }

    document.addEventListener('DOMContentLoaded', function () {
        var raw = null;
        try {
            raw = sessionStorage.getItem('ui-flash');
            if (raw) sessionStorage.removeItem('ui-flash');
        } catch (e) { /* ignore */ }
        if (!raw) return;
        try {
            var f = JSON.parse(raw);
            toast(f.m, f.t);
        } catch (e) { /* ignore malformed payload */ }
    });

    // --- Confirm dialog -------------------------------------------------------
    function confirmDialog(options) {
        if (typeof options === 'string') options = { message: options };
        options = options || {};
        return new Promise(function (resolve) {
            var overlay = document.createElement('div');
            overlay.className = 'modal-overlay';
            overlay.setAttribute('role', 'dialog');
            overlay.setAttribute('aria-modal', 'true');

            var panel = document.createElement('div');
            panel.className = 'modal-panel max-w-md p-6';

            var title = document.createElement('h3');
            title.className = 'text-lg font-semibold text-gray-900 mb-2';
            title.textContent = options.title || 'Please confirm';
            panel.appendChild(title);

            var body = document.createElement('p');
            body.className = 'text-sm text-gray-600 whitespace-pre-line mb-6';
            body.textContent = options.message || 'Are you sure?';
            panel.appendChild(body);

            var actions = document.createElement('div');
            actions.className = 'flex justify-end gap-3';

            var cancelBtn = document.createElement('button');
            cancelBtn.type = 'button';
            cancelBtn.className = 'btn-secondary';
            cancelBtn.textContent = options.cancelLabel || 'Cancel';
            actions.appendChild(cancelBtn);

            var confirmBtn = document.createElement('button');
            confirmBtn.type = 'button';
            confirmBtn.className = options.danger ? 'btn-danger' : 'btn-primary';
            confirmBtn.textContent = options.confirmLabel || 'Confirm';
            actions.appendChild(confirmBtn);

            panel.appendChild(actions);
            overlay.appendChild(panel);
            document.body.appendChild(overlay);
            document.body.classList.add('overflow-hidden');

            function done(result) {
                document.removeEventListener('keydown', onKey, true);
                overlay.remove();
                document.body.classList.remove('overflow-hidden');
                resolve(result);
            }
            // Capture phase so the global Escape handler (which force-hides
            // .modal-overlay without resolving) never sees this keypress.
            function onKey(e) {
                if (e.key === 'Escape') {
                    e.stopPropagation();
                    done(false);
                }
            }
            document.addEventListener('keydown', onKey, true);
            cancelBtn.addEventListener('click', function () { done(false); });
            confirmBtn.addEventListener('click', function () { done(true); });
            overlay.addEventListener('click', function (e) {
                if (e.target === overlay) done(false);
            });

            confirmBtn.focus();
        });
    }

    // --- Confirm-before-submit ----------------------------------------------
    document.addEventListener('submit', function (e) {
        var form = e.target.closest('form[data-confirm]');
        if (!form || form.dataset.confirmAccepted === 'true') {
            if (form) delete form.dataset.confirmAccepted;
            return;
        }
        e.preventDefault();
        var submitter = e.submitter || null;
        confirmDialog({
            title: form.getAttribute('data-confirm-title') || undefined,
            message: form.getAttribute('data-confirm'),
            confirmLabel: form.getAttribute('data-confirm-label') || undefined,
            danger: form.hasAttribute('data-confirm-danger')
        }).then(function (ok) {
            if (!ok) return;
            form.dataset.confirmAccepted = 'true';
            if (form.requestSubmit) {
                form.requestSubmit(submitter && form.contains(submitter) ? submitter : undefined);
            } else {
                form.submit();
            }
        });
    });

    // Expose for programmatic use
    window.UI = {
        openModal: openModal,
        closeModal: closeModal,
        toast: toast,
        flash: flash,
        confirm: confirmDialog
    };
})();
