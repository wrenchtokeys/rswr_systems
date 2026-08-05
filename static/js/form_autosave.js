/**
 * Form Autosave Module
 * Professional SaaS-grade localStorage-based form state preservation
 * Prevents data loss during browser crashes, accidental navigation, etc.
 */

class FormAutosave {
    constructor(formId, options = {}) {
        this.formId = formId;
        this.form = document.getElementById(formId);

        if (!this.form) {
            console.warn(`FormAutosave: Form with ID "${formId}" not found`);
            return;
        }

        // Configuration
        this.options = {
            saveDelay: options.saveDelay || 1000, // ms to wait after typing stops
            storageKey: options.storageKey || `autosave_${formId}`,
            excludeFields: options.excludeFields || ['csrfmiddlewaretoken'], // Fields to skip
            onSave: options.onSave || null, // Callback when save occurs
            beforeRestore: options.beforeRestore || null, // Runs before fields are written — use to
                                                          // build dynamic fields that must exist first
            onRestore: options.onRestore || null, // Callback when data is restored
            showIndicator: options.showIndicator !== false, // Show save indicator
            confirmRestore: options.confirmRestore !== false, // Ask before restoring
            maxAgeHours: options.maxAgeHours || 24, // Drafts older than this are discarded, not offered
        };

        this.saveTimeout = null;
        this.indicator = null;

        this.init();
    }

    /**
     * Initialize autosave functionality
     */
    init() {
        // Create save indicator if enabled
        if (this.options.showIndicator) {
            this.createIndicator();
        }

        // Check for saved data on load
        this.checkForSavedData();

        // Attach event listeners
        this.attachListeners();

        // Clear data on successful submit
        this.form.addEventListener('submit', () => {
            this.clearSavedData();
        });
    }

    /**
     * Create visual save indicator
     */
    createIndicator() {
        this.indicator = document.createElement('div');
        this.indicator.className = 'autosave-indicator';
        this.indicator.innerHTML = '<i class="fas fa-spinner spin"></i> <span>Saving...</span>';
        document.body.appendChild(this.indicator);
    }

    /**
     * Show indicator with status
     */
    showIndicator(status = 'saving') {
        if (!this.indicator) return;

        this.indicator.className = 'autosave-indicator show ' + status;

        const icons = {
            saving: '<i class="fas fa-spinner spin"></i> <span>Saving draft...</span>',
            saved: '<i class="fas fa-check-circle"></i> <span>Draft saved</span>',
            error: '<i class="fas fa-exclamation-circle"></i> <span>Save failed</span>'
        };

        this.indicator.innerHTML = icons[status] || icons.saving;

        // Auto-hide after 2 seconds (except for errors)
        if (status !== 'error') {
            setTimeout(() => {
                this.indicator.classList.remove('show');
            }, 2000);
        }
    }

    /**
     * Attach input listeners for autosave
     */
    attachListeners() {
        const inputs = this.form.querySelectorAll('input, textarea, select');

        inputs.forEach(input => {
            // Skip excluded fields
            if (this.options.excludeFields.includes(input.name)) {
                return;
            }

            // Different events for different input types
            if (input.type === 'checkbox' || input.type === 'radio' || input.tagName === 'SELECT') {
                input.addEventListener('change', () => this.scheduleSave());
            } else if (input.type !== 'file') {
                // File inputs can't be saved to localStorage
                input.addEventListener('input', () => this.scheduleSave());
            }
        });
    }

    /**
     * Schedule a save operation (debounced)
     */
    scheduleSave() {
        clearTimeout(this.saveTimeout);

        if (this.options.showIndicator) {
            this.showIndicator('saving');
        }

        this.saveTimeout = setTimeout(() => {
            this.saveFormData();
        }, this.options.saveDelay);
    }

    /**
     * Save form data to localStorage
     */
    saveFormData() {
        try {
            const formData = {};
            const inputs = this.form.querySelectorAll('input, textarea, select');

            inputs.forEach(input => {
                // Skip excluded fields and file inputs
                if (this.options.excludeFields.includes(input.name) || input.type === 'file') {
                    return;
                }

                // Handle different input types
                if (input.type === 'checkbox') {
                    formData[input.name] = input.checked;
                } else if (input.type === 'radio') {
                    if (input.checked) {
                        formData[input.name] = input.value;
                    }
                } else {
                    formData[input.name] = input.value;
                }
            });

            // Add timestamp
            formData._timestamp = new Date().toISOString();

            // Save to localStorage
            localStorage.setItem(this.options.storageKey, JSON.stringify(formData));

            if (this.options.showIndicator) {
                this.showIndicator('saved');
            }

            // Callback
            if (this.options.onSave) {
                this.options.onSave(formData);
            }

        } catch (error) {
            console.error('FormAutosave: Error saving data', error);
            if (this.options.showIndicator) {
                this.showIndicator('error');
            }
        }
    }

    /**
     * Check for saved data and offer to restore
     */
    checkForSavedData() {
        try {
            const savedData = localStorage.getItem(this.options.storageKey);

            if (!savedData) {
                return;
            }

            const data = JSON.parse(savedData);

            // Calculate time since save
            const timestamp = new Date(data._timestamp);
            const hoursSince = (new Date() - timestamp) / (1000 * 60 * 60);

            // A stale draft is more likely to be wrong than useful — a tech who
            // starts a job days later is on a different vehicle. Drop it silently
            // rather than prompting to restore data they'd have to clear by hand.
            if (hoursSince > this.options.maxAgeHours) {
                this.clearSavedData();
                return;
            }

            // Show restore prompt
            if (this.options.confirmRestore) {
                const timeAgo = this.formatTimeAgo(timestamp);
                UI.confirm({
                    title: 'Restore draft?',
                    message: `Found a draft saved ${timeAgo}. Would you like to restore it?`,
                    confirmLabel: 'Restore',
                    cancelLabel: 'Discard',
                }).then((ok) => {
                    if (ok) {
                        this.restoreFormData(data);
                    } else {
                        this.clearSavedData();
                    }
                });
            } else {
                this.restoreFormData(data);
            }

        } catch (error) {
            console.error('FormAutosave: Error checking saved data', error);
        }
    }

    /**
     * Restore form data from saved state
     */
    restoreFormData(data) {
        try {
            // Give the form a chance to create any fields that only exist after
            // user interaction — otherwise the lookup below silently skips them.
            if (this.options.beforeRestore) {
                this.options.beforeRestore(data);
            }

            Object.keys(data).forEach(name => {
                if (name === '_timestamp') return;

                const input = this.form.querySelector(`[name="${name}"]`);
                if (!input) return;

                // Handle different input types
                if (input.type === 'checkbox') {
                    input.checked = data[name];
                } else if (input.type === 'radio') {
                    const radio = this.form.querySelector(`[name="${name}"][value="${data[name]}"]`);
                    if (radio) radio.checked = true;
                } else if (input.type !== 'file') {
                    input.value = data[name];
                    // Trigger change event for any dependent logic
                    input.dispatchEvent(new Event('change', { bubbles: true }));
                }
            });

            // Callback
            if (this.options.onRestore) {
                this.options.onRestore(data);
            }

            console.log('FormAutosave: Data restored successfully');

        } catch (error) {
            console.error('FormAutosave: Error restoring data', error);
        }
    }

    /**
     * Clear saved data from localStorage
     */
    clearSavedData() {
        try {
            localStorage.removeItem(this.options.storageKey);
        } catch (error) {
            console.error('FormAutosave: Error clearing data', error);
        }
    }

    /**
     * Format timestamp as "X minutes/hours/days ago"
     */
    formatTimeAgo(timestamp) {
        const seconds = Math.floor((new Date() - timestamp) / 1000);

        if (seconds < 60) return 'just now';

        const minutes = Math.floor(seconds / 60);
        if (minutes < 60) return `${minutes} minute${minutes > 1 ? 's' : ''} ago`;

        const hours = Math.floor(minutes / 60);
        if (hours < 24) return `${hours} hour${hours > 1 ? 's' : ''} ago`;

        const days = Math.floor(hours / 24);
        return `${days} day${days > 1 ? 's' : ''} ago`;
    }

    /**
     * Manually trigger a save
     */
    save() {
        this.saveFormData();
    }

    /**
     * Destroy autosave instance
     */
    destroy() {
        clearTimeout(this.saveTimeout);
        if (this.indicator) {
            this.indicator.remove();
        }
    }
}

// Export for use in other scripts
if (typeof module !== 'undefined' && module.exports) {
    module.exports = FormAutosave;
}
