/**
 * Manager Settings JavaScript
 * Handles modal interactions and AJAX operations for viscosity rules management
 */

// Get CSRF token from DOM (works with CSRF_COOKIE_HTTPONLY = True)
function getCSRFToken() {
    // Try to get from DOM element first (works with HttpOnly cookies)
    const tokenElement = document.querySelector('[name=csrfmiddlewaretoken]');
    if (tokenElement) {
        return tokenElement.value;
    }

    // Fallback to cookie method (for backwards compatibility)
    let cookieValue = null;
    if (document.cookie && document.cookie !== '') {
        const cookies = document.cookie.split(';');
        for (let i = 0; i < cookies.length; i++) {
            const cookie = cookies[i].trim();
            if (cookie.substring(0, 10) === 'csrftoken=') {
                cookieValue = decodeURIComponent(cookie.substring(10));
                break;
            }
        }
    }
    return cookieValue;
}

const csrftoken = getCSRFToken();

// Global variables
let currentRuleId = null;
let isEditMode = false;

// ============================================================================
// MODAL FUNCTIONS
// ============================================================================

function openModal(ruleId = null) {
    const modal = document.getElementById('ruleModal');
    const modalTitle = document.getElementById('modalTitle');
    const form = document.getElementById('ruleForm');

    // Reset form
    form.reset();
    document.getElementById('ruleId').value = '';
    currentRuleId = null;
    isEditMode = false;

    if (ruleId) {
        // Edit mode - fetch rule data
        isEditMode = true;
        currentRuleId = ruleId;
        modalTitle.textContent = 'Edit Rule';
        loadRuleData(ruleId);
    } else {
        // Add mode - priority is auto-assigned by backend
        modalTitle.textContent = 'Add New Rule';
        document.getElementById('isActive').checked = true;
    }

    window.UI.openModal('ruleModal');
}

function closeModal() {
    window.UI.closeModal(document.getElementById('ruleModal'));
    currentRuleId = null;
    isEditMode = false;
}

async function loadRuleData(ruleId) {
    try {
        const response = await fetch(`/tech/settings/api/viscosity/${ruleId}/`, {
            method: 'GET',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': csrftoken
            }
        });

        const result = await response.json();

        if (result.success && result.rule) {
            const rule = result.rule;

            // Populate all form fields (priority is auto-managed, not editable)
            document.getElementById('ruleId').value = rule.id;
            document.getElementById('ruleName').value = rule.name;
            document.getElementById('minTemp').value = rule.min_temperature;
            document.getElementById('maxTemp').value = rule.max_temperature;
            document.getElementById('viscosity').value = rule.recommended_viscosity;
            document.getElementById('suggestionText').value = rule.suggestion_text;
            document.getElementById('badgeColor').value = rule.badge_color;
            document.getElementById('isActive').checked = rule.is_active;
        } else {
            showMessage('Failed to load rule data', 'error');
            closeModal();
        }
    } catch (error) {
        console.error('Error loading rule data:', error);
        showMessage('An error occurred while loading the rule', 'error');
        closeModal();
    }
}

// ============================================================================
// CRUD OPERATIONS
// ============================================================================

async function saveRule(event) {
    event.preventDefault();

    const form = document.getElementById('ruleForm');
    const formData = new FormData(form);

    // Build JSON payload (priority is auto-assigned by backend)
    const data = {
        name: formData.get('name'),
        min_temperature: formData.get('min_temperature') || null,
        max_temperature: formData.get('max_temperature') || null,
        recommended_viscosity: formData.get('recommended_viscosity'),
        suggestion_text: formData.get('suggestion_text'),
        badge_color: formData.get('badge_color'),
        is_active: formData.get('is_active') === 'on'
    };

    // Client-side validation for temperature range
    if (data.min_temperature !== null && data.max_temperature !== null) {
        const minTemp = parseFloat(data.min_temperature);
        const maxTemp = parseFloat(data.max_temperature);

        if (minTemp >= maxTemp) {
            showMessage('Minimum temperature must be less than maximum temperature', 'error');
            return;
        }
    }

    let url, method;
    if (isEditMode && currentRuleId) {
        url = `/tech/settings/api/viscosity/${currentRuleId}/update/`;
        method = 'POST';  // Using POST for compatibility
    } else {
        url = '/tech/settings/api/viscosity/create/';
        method = 'POST';
    }

    try {
        const response = await fetch(url, {
            method: method,
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': csrftoken
            },
            body: JSON.stringify(data)
        });

        const result = await response.json();

        if (result.success) {
            showMessage(result.message, 'success');
            closeModal();
            // Reload page to show changes
            setTimeout(() => {
                window.location.reload();
            }, 1000);
        } else {
            // Show specific error message from backend
            const errorMsg = result.error || 'Failed to save rule';
            showMessage(errorMsg, 'error');
            console.error('Save failed:', errorMsg);
        }
    } catch (error) {
        console.error('Error saving rule:', error);
        // Show user-friendly error with technical details in console
        showMessage('Unable to save rule. Please check all required fields and try again.', 'error');
    }
}

async function deleteRule(ruleId, ruleName) {
    if (!confirm(`Are you sure you want to delete the rule "${ruleName}"?\n\nThis action cannot be undone.`)) {
        return;
    }

    try {
        const response = await fetch(`/tech/settings/api/viscosity/${ruleId}/delete/`, {
            method: 'POST',  // Using POST for compatibility
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': csrftoken
            }
        });

        const result = await response.json();

        if (result.success) {
            showMessage(result.message, 'success');
            // Remove card from DOM
            const card = document.querySelector(`[data-rule-id="${ruleId}"]`);
            if (card) {
                card.style.opacity = '0';
                card.style.transform = 'scale(0.9)';
                setTimeout(() => {
                    card.remove();
                    // Check if grid is empty
                    const grid = document.getElementById('rulesGrid');
                    if (grid.children.length === 0) {
                        location.reload();
                    }
                }, 300);
            }
        } else {
            showMessage(result.error || 'Failed to delete rule', 'error');
        }
    } catch (error) {
        console.error('Error deleting rule:', error);
        showMessage('An error occurred while deleting the rule', 'error');
    }
}

async function toggleRule(ruleId, isActive) {
    try {
        const response = await fetch(`/tech/settings/api/viscosity/${ruleId}/toggle/`, {
            method: 'POST',  // Using POST for compatibility
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': csrftoken
            }
        });

        const result = await response.json();

        if (result.success) {
            showMessage(result.message, 'success');
            // Update card appearance
            const card = document.querySelector(`[data-rule-id="${ruleId}"]`);
            if (card) {
                card.classList.toggle('opacity-60', !result.is_active);
            }
        } else {
            showMessage(result.error || 'Failed to toggle rule', 'error');
            // Revert checkbox
            const checkbox = document.querySelector(`[data-rule-id="${ruleId}"] input[type="checkbox"]`);
            if (checkbox) {
                checkbox.checked = !isActive;
            }
        }
    } catch (error) {
        console.error('Error toggling rule:', error);
        showMessage('An error occurred while toggling the rule', 'error');
        // Revert checkbox
        const checkbox = document.querySelector(`[data-rule-id="${ruleId}"] input[type="checkbox"]`);
        if (checkbox) {
            checkbox.checked = !isActive;
        }
    }
}

function editRule(ruleId) {
    openModal(ruleId);
}

// ============================================================================
// UI FUNCTIONS
// ============================================================================

function showMessage(message, type = 'success') {
    const toast = document.getElementById('messageToast');
    const messageText = document.getElementById('messageText');
    const icon = toast.querySelector('i');

    messageText.textContent = message;

    // Update icon and style based on type
    toast.classList.remove('bg-green-600', 'bg-red-600');
    if (type === 'error') {
        toast.classList.add('bg-red-600');
        icon.className = 'fas fa-exclamation-circle';
    } else {
        toast.classList.add('bg-green-600');
        icon.className = 'fas fa-check-circle';
    }

    toast.classList.remove('hidden');

    // Auto-hide after 3 seconds
    setTimeout(() => {
        toast.classList.add('hidden');
    }, 3000);
}

// ============================================================================
// EVENT LISTENERS
// ============================================================================

document.addEventListener('DOMContentLoaded', function() {
    // Add rule button
    const addRuleBtn = document.getElementById('addRuleBtn');
    if (addRuleBtn) {
        addRuleBtn.addEventListener('click', () => openModal());
    }

    // Form submission
    const ruleForm = document.getElementById('ruleForm');
    if (ruleForm) {
        ruleForm.addEventListener('submit', saveRule);
    }

    // Close modal on escape key
    document.addEventListener('keydown', function(e) {
        if (e.key === 'Escape') {
            closeModal();
        }
    });

    console.log('✅ Manager Settings JavaScript loaded');
});
