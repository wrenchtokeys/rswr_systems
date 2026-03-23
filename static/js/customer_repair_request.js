/**
 * Customer Repair Request - Multi-Unit Batch Submission
 * Handles state management, modal interactions, pricing preview, photo previews, and form autosave
 */

// State management
let units = [];
let editingIndex = null;
let autosaveInterval = null;

// Initialize on page load
document.addEventListener('DOMContentLoaded', function() {
    setupEventListeners();
    restoreFromLocalStorage();
    startAutosave();
});

// ======================
// Event Listeners Setup
// ======================

function setupEventListeners() {
    // Add Unit button
    const addUnitBtn = document.getElementById('addUnitBtn');
    if (addUnitBtn) {
        addUnitBtn.addEventListener('click', openAddUnitModal);
    }

    // Save Unit button in modal
    const saveUnitBtn = document.getElementById('saveUnitBtn');
    if (saveUnitBtn) {
        saveUnitBtn.addEventListener('click', saveUnit);
    }

    // Cancel modal button
    const cancelModalBtn = document.getElementById('cancelModalBtn');
    if (cancelModalBtn) {
        cancelModalBtn.addEventListener('click', closeModal);
    }

    // Close modal on background click
    const modal = document.getElementById('addUnitModal');
    if (modal) {
        modal.addEventListener('click', function(e) {
            if (e.target === modal) {
                closeModal();
            }
        });
    }

    // Photo input change handler
    const photoInput = document.getElementById('modalPhotoInput');
    if (photoInput) {
        photoInput.addEventListener('change', handlePhotoSelection);
    }

    // Multi-break checkbox handler
    const multiBreakCheckbox = document.getElementById('modalHasMultipleBreaks');
    if (multiBreakCheckbox) {
        multiBreakCheckbox.addEventListener('change', toggleBreakCountInput);
    }

    // Break count input handler - triggers modal pricing update
    const breakCountInput = document.getElementById('modalBreakCount');
    if (breakCountInput) {
        let debounceTimer;
        breakCountInput.addEventListener('input', function() {
            // Debounce to prevent excessive API calls while typing
            clearTimeout(debounceTimer);
            debounceTimer = setTimeout(() => {
                updateModalPricingPreview();
            }, 300);
        });
    }

    // Unit number input handler - triggers modal pricing update
    const unitNumberInput = document.getElementById('modalUnitNumber');
    if (unitNumberInput) {
        let debounceTimer;
        unitNumberInput.addEventListener('input', function() {
            // Debounce to prevent excessive API calls while typing
            clearTimeout(debounceTimer);
            debounceTimer = setTimeout(() => {
                updateModalPricingPreview();
            }, 300);
        });
    }

    // Form submission
    const mainForm = document.getElementById('batchRepairForm');
    if (mainForm) {
        mainForm.addEventListener('submit', handleBatchSubmit);
    }

    // Restore saved data prompt
    const restoreBtn = document.getElementById('restoreSavedDataBtn');
    if (restoreBtn) {
        restoreBtn.addEventListener('click', function() {
            restoreFromLocalStorage(true);
            document.getElementById('restoreDataPrompt').classList.add('hidden');
        });
    }

    const discardBtn = document.getElementById('discardSavedDataBtn');
    if (discardBtn) {
        discardBtn.addEventListener('click', function() {
            localStorage.removeItem('customerRepairRequest');
            document.getElementById('restoreDataPrompt').classList.add('hidden');
        });
    }
}

// ======================
// Modal Management
// ======================

function openAddUnitModal() {
    editingIndex = null;
    clearModalForm();
    document.getElementById('modalTitle').textContent = 'Add Unit Repair';
    document.getElementById('addUnitModal').classList.remove('hidden');

    // Focus on unit number input
    setTimeout(() => {
        document.getElementById('modalUnitNumber').focus();
    }, 100);
}

function openEditUnitModal(index) {
    editingIndex = index;
    const unit = units[index];

    // Populate modal with unit data
    document.getElementById('modalUnitNumber').value = unit.unitNumber;
    document.getElementById('modalDamageType').value = unit.damageType || '';
    document.getElementById('modalNotes').value = unit.notes || '';
    document.getElementById('modalHasMultipleBreaks').checked = unit.hasMultipleBreaks || false;
    document.getElementById('modalBreakCount').value = unit.breakCount || '';

    // Show/hide break count input based on checkbox
    if (unit.hasMultipleBreaks) {
        document.getElementById('modalBreakCountContainer').classList.remove('hidden');
    } else {
        document.getElementById('modalBreakCountContainer').classList.add('hidden');
    }

    // Show photo preview if exists
    if (unit.photoDataUrl) {
        showPhotoPreview(unit.photoDataUrl, unit.photoName);
    }

    // Restore damage location if exists
    if (unit.damageLocationX && unit.damageLocationY) {
        placeModalDamageMarker(parseFloat(unit.damageLocationX), parseFloat(unit.damageLocationY));
    }

    document.getElementById('modalTitle').textContent = 'Edit Unit Repair';
    document.getElementById('addUnitModal').classList.remove('hidden');

    // Update modal pricing preview for editing
    updateModalPricingPreview();
}

function closeModal() {
    document.getElementById('addUnitModal').classList.add('hidden');
    clearModalForm();
    editingIndex = null;
}

function clearModalForm() {
    document.getElementById('modalUnitNumber').value = '';
    document.getElementById('modalDamageType').value = '';
    document.getElementById('modalNotes').value = '';
    document.getElementById('modalPhotoInput').value = '';
    document.getElementById('modalHasMultipleBreaks').checked = false;
    document.getElementById('modalBreakCount').value = '';
    document.getElementById('modalBreakCountContainer').classList.add('hidden');
    document.getElementById('photoPreviewContainer').classList.add('hidden');
    clearFieldError('modalUnitNumber');

    // Clear damage location
    clearModalDamageMarker();

    // Clear modal pricing preview
    const previewElement = document.getElementById('modalPricingPreview');
    if (previewElement) {
        previewElement.innerHTML = '<span class="text-gray-400 text-sm"><i class="fas fa-info-circle"></i> Enter unit number to see pricing estimate</span>';
    }
}

// ======================
// Multi-Break Handling
// ======================

function toggleBreakCountInput() {
    const checkbox = document.getElementById('modalHasMultipleBreaks');
    const breakCountContainer = document.getElementById('modalBreakCountContainer');

    if (checkbox.checked) {
        breakCountContainer.classList.remove('hidden');
    } else {
        breakCountContainer.classList.add('hidden');
        document.getElementById('modalBreakCount').value = '';
    }

    // Update modal pricing preview when checkbox state changes
    updateModalPricingPreview();
}

/**
 * Update pricing preview for the current unit being edited in the modal
 * Shows live pricing feedback without affecting the main pricing preview
 */
function updateModalPricingPreview() {
    const modal = document.getElementById('addUnitModal');
    const previewElement = document.getElementById('modalPricingPreview');

    // Only update if modal is open and preview element exists
    if (!modal || modal.classList.contains('hidden') || !previewElement) {
        return;
    }

    const unitNumber = document.getElementById('modalUnitNumber').value.trim();
    const hasMultipleBreaks = document.getElementById('modalHasMultipleBreaks').checked;
    const breakCount = document.getElementById('modalBreakCount').value;

    // Clear preview if no unit number
    if (!unitNumber) {
        previewElement.innerHTML = '<span class="text-gray-400 text-sm"><i class="fas fa-info-circle"></i> Enter unit number to see pricing estimate</span>';
        return;
    }

    // Show loading state
    previewElement.innerHTML = '<span class="text-gray-400 text-sm"><i class="fas fa-spinner fa-spin"></i> Calculating...</span>';

    // Build single unit data for pricing API
    const unitData = [{
        unit_number: unitNumber,
        has_multiple_breaks: hasMultipleBreaks,
        break_count: breakCount ? parseInt(breakCount) : null
    }];

    fetch('/app/api/repair-pricing/', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': getCookie('csrftoken')
        },
        body: JSON.stringify({ units: unitData })
    })
    .then(response => {
        // Always parse JSON, even on error
        return response.json().then(data => {
            if (!response.ok) {
                // Include the error data from backend
                throw new Error(data.error || `HTTP error! status: ${response.status}`);
            }
            return data;
        });
    })
    .then(data => {
        if (data.error) {
            console.error('Pricing API error:', data.error);
            previewElement.innerHTML = `<span class="text-red-500 text-sm"><i class="fas fa-exclamation-triangle"></i> ${data.error}</span>`;
            return;
        }

        // Display pricing for this single unit
        if (data.units && data.units.length > 0) {
            const unitData = data.units[0];
            let priceHtml = '';

            if (unitData.has_multiple_breaks && unitData.break_count) {
                // Multi-break with exact count
                priceHtml = `
                    <div class="text-sm">
                        <i class="fas fa-tag text-blue-600"></i>
                        <span class="font-semibold text-blue-700">${unitData.total_price_formatted}</span>
                        <span class="text-gray-600">(${unitData.break_count} breaks)</span>
                        ${unitData.uses_custom_pricing ? '<span class="ml-1 text-xs bg-purple-100 text-purple-800 px-1.5 py-0.5 rounded">Custom</span>' : ''}
                    </div>
                `;
            } else if (unitData.has_multiple_breaks && unitData.is_estimate) {
                // Multi-break estimate (range)
                priceHtml = `
                    <div class="text-sm">
                        <i class="fas fa-tag text-blue-600"></i>
                        <span class="font-semibold text-blue-700">${unitData.range_formatted}</span>
                        <span class="text-gray-600">(${unitData.min_breaks}-${unitData.max_breaks} breaks estimated)</span>
                        ${unitData.uses_custom_pricing ? '<span class="ml-1 text-xs bg-purple-100 text-purple-800 px-1.5 py-0.5 rounded">Custom</span>' : ''}
                    </div>
                `;
            } else {
                // Single repair
                priceHtml = `
                    <div class="text-sm">
                        <i class="fas fa-tag text-blue-600"></i>
                        <span class="font-semibold text-blue-700">${unitData.price_formatted}</span>
                        <span class="text-gray-600">(Repair #${unitData.next_repair_number})</span>
                        ${unitData.uses_custom_pricing ? '<span class="ml-1 text-xs bg-purple-100 text-purple-800 px-1.5 py-0.5 rounded">Custom</span>' : ''}
                    </div>
                `;
            }

            previewElement.innerHTML = priceHtml;
        }
    })
    .catch(error => {
        console.error('Error fetching modal pricing:', error);
        previewElement.innerHTML = `<span class="text-red-500 text-sm"><i class="fas fa-exclamation-triangle"></i> Pricing unavailable</span>`;
    });
}

// ======================
// Photo Handling
// ======================

function handlePhotoSelection(event) {
    const file = event.target.files[0];
    if (!file) {
        document.getElementById('photoPreviewContainer').classList.add('hidden');
        return;
    }

    // Validate file
    const validation = validatePhoto(file);
    if (!validation.valid) {
        showFieldError('modalPhotoInput', validation.error);
        event.target.value = '';
        return;
    }

    // Read and preview
    const reader = new FileReader();
    reader.onload = function(e) {
        showPhotoPreview(e.target.result, file.name);
    };
    reader.readAsDataURL(file);
}

function validatePhoto(file) {
    // Check size (5MB limit)
    if (file.size > 5 * 1024 * 1024) {
        return { valid: false, error: 'File size must be less than 5MB' };
    }

    // Check type
    const allowedTypes = ['image/jpeg', 'image/jpg', 'image/png', 'image/webp', 'image/heic', 'image/heif'];
    const fileName = file.name.toLowerCase();
    const fileExt = fileName.split('.').pop();
    const allowedExtensions = ['jpg', 'jpeg', 'png', 'webp', 'heic', 'heif'];

    const isValidType = allowedTypes.includes(file.type);
    const isValidExtension = allowedExtensions.includes(fileExt);

    if (!isValidType && !isValidExtension) {
        return { valid: false, error: 'Please upload a valid image file (JPEG, PNG, WebP, or HEIC)' };
    }

    return { valid: true };
}

function showPhotoPreview(dataUrl, fileName) {
    const preview = document.getElementById('photoPreview');
    const container = document.getElementById('photoPreviewContainer');
    const nameSpan = document.getElementById('photoFileName');

    preview.src = dataUrl;
    nameSpan.textContent = fileName;
    container.classList.remove('hidden');
}

function removePhoto() {
    document.getElementById('modalPhotoInput').value = '';
    document.getElementById('photoPreviewContainer').classList.add('hidden');
}

// ======================
// Unit Management
// ======================

function saveUnit() {
    const unitNumber = document.getElementById('modalUnitNumber').value.trim();
    const damageType = document.getElementById('modalDamageType').value;
    const notes = document.getElementById('modalNotes').value.trim();
    const photoInput = document.getElementById('modalPhotoInput');
    const hasMultipleBreaks = document.getElementById('modalHasMultipleBreaks').checked;
    const breakCount = document.getElementById('modalBreakCount').value;

    // Validate unit number
    if (!unitNumber) {
        showFieldError('modalUnitNumber', 'Unit number is required');
        return;
    }

    // Check for duplicate unit numbers (unless editing the same unit)
    const duplicateIndex = units.findIndex((u, i) =>
        u.unitNumber.toLowerCase() === unitNumber.toLowerCase() && i !== editingIndex
    );

    if (duplicateIndex !== -1) {
        showFieldError('modalUnitNumber', 'This unit number is already in the batch');
        return;
    }

    // Get damage location
    const damageLocationX = document.getElementById('modalDamageLocationX').value;
    const damageLocationY = document.getElementById('modalDamageLocationY').value;

    // Create unit object
    const unit = {
        unitNumber: unitNumber,
        damageType: damageType || 'Unknown',
        notes: notes || '',
        hasMultipleBreaks: hasMultipleBreaks,
        breakCount: breakCount ? parseInt(breakCount) : null,
        damageLocationX: damageLocationX || null,
        damageLocationY: damageLocationY || null,
        photoDataUrl: null,
        photoName: null,
        photoFile: null
    };

    // Handle photo
    if (photoInput.files && photoInput.files[0]) {
        const reader = new FileReader();
        reader.onload = function(e) {
            unit.photoDataUrl = e.target.result;
            unit.photoName = photoInput.files[0].name;
            unit.photoFile = photoInput.files[0];
            finalizeSaveUnit(unit);
        };
        reader.readAsDataURL(photoInput.files[0]);
    } else if (editingIndex !== null && units[editingIndex].photoDataUrl) {
        // Keep existing photo when editing
        unit.photoDataUrl = units[editingIndex].photoDataUrl;
        unit.photoName = units[editingIndex].photoName;
        unit.photoFile = units[editingIndex].photoFile;
        finalizeSaveUnit(unit);
    } else {
        finalizeSaveUnit(unit);
    }
}

function finalizeSaveUnit(unit) {
    if (editingIndex !== null) {
        // Update existing unit
        units[editingIndex] = unit;
    } else {
        // Add new unit
        units.push(unit);
    }

    renderUnitCards();
    updateSubmitButton();
    updatePricingPreview();
    closeModal();
    saveToLocalStorage();
}

function deleteUnit(index) {
    if (confirm('Remove this unit from the batch?')) {
        units.splice(index, 1);
        renderUnitCards();
        updateSubmitButton();
        updatePricingPreview();
        saveToLocalStorage();
    }
}

// ======================
// UI Rendering
// ======================

function renderUnitCards() {
    const container = document.getElementById('unitsContainer');
    const emptyState = document.getElementById('emptyState');

    if (units.length === 0) {
        container.innerHTML = '';
        emptyState.classList.remove('hidden');
        return;
    }

    emptyState.classList.add('hidden');

    let html = '';
    units.forEach((unit, index) => {
        const damageTypeBadge = getDamageTypeBadge(unit.damageType);
        const photoIcon = unit.photoDataUrl
            ? '<i class="fas fa-camera text-green-500"></i>'
            : '<i class="fas fa-camera-slash text-gray-400"></i>';

        html += `
            <div class="bg-white rounded-lg border-2 border-gray-200 p-4 hover:border-blue-400 transition-all">
                <div class="flex justify-between items-start mb-3">
                    <div class="flex items-center space-x-2">
                        <div class="bg-blue-100 text-blue-800 font-bold rounded-full w-8 h-8 flex items-center justify-center text-sm">
                            ${index + 1}
                        </div>
                        <div>
                            <div class="font-semibold text-lg">Unit ${escapeHtml(unit.unitNumber)}</div>
                            ${damageTypeBadge}
                        </div>
                    </div>
                    <div class="flex items-center space-x-2">
                        ${photoIcon}
                        <button type="button" onclick="openEditUnitModal(${index})"
                            class="text-blue-600 hover:text-blue-800 text-sm">
                            <i class="fas fa-edit"></i> Edit
                        </button>
                        <button type="button" onclick="deleteUnit(${index})"
                            class="text-red-600 hover:text-red-800 text-sm">
                            <i class="fas fa-trash"></i> Delete
                        </button>
                    </div>
                </div>
                ${unit.photoDataUrl ? `
                    <div class="mt-2 mb-2">
                        <img src="${unit.photoDataUrl}" alt="Damage photo"
                            class="h-24 w-auto rounded border border-gray-300 object-cover">
                    </div>
                ` : ''}
                ${unit.damageLocationX ? `
                    <div class="mt-2 text-xs text-blue-600">
                        <i class="fas fa-crosshairs"></i> Location marked on windshield
                    </div>
                ` : ''}
                ${unit.notes ? `
                    <div class="mt-2 text-sm text-gray-600 border-t pt-2">
                        <i class="fas fa-sticky-note text-gray-400"></i> ${escapeHtml(unit.notes)}
                    </div>
                ` : ''}
                <div id="unit-price-${index}" class="mt-3 text-sm font-semibold text-blue-900">
                    <!-- Pricing will be inserted here -->
                </div>
            </div>
        `;
    });

    container.innerHTML = html;
}

function getDamageTypeBadge(damageType) {
    const colors = {
        'Chip': 'bg-yellow-100 text-yellow-800',
        'Crack': 'bg-red-100 text-red-800',
        'Star Break': 'bg-orange-100 text-orange-800',
        "Bull's Eye": 'bg-purple-100 text-purple-800',
        'Combination Break': 'bg-pink-100 text-pink-800',
        'Half-Moon': 'bg-indigo-100 text-indigo-800',
        'Other': 'bg-gray-100 text-gray-800',
        'Unknown': 'bg-gray-100 text-gray-800'
    };

    const colorClass = colors[damageType] || 'bg-gray-100 text-gray-800';
    return `<span class="text-xs px-2 py-1 rounded ${colorClass}">${escapeHtml(damageType)}</span>`;
}

function updateSubmitButton() {
    const btn = document.getElementById('submitBatchBtn');
    const badge = document.getElementById('unitCountBadge');

    if (units.length === 0) {
        btn.disabled = true;
        btn.classList.add('opacity-50', 'cursor-not-allowed');
        btn.innerHTML = '<i class="fas fa-paper-plane mr-2"></i>Submit Repair Request';
    } else {
        btn.disabled = false;
        btn.classList.remove('opacity-50', 'cursor-not-allowed');
        btn.innerHTML = `<i class="fas fa-paper-plane mr-2"></i>Submit ${units.length} Unit Repair${units.length > 1 ? 's' : ''}`;
    }

    badge.textContent = units.length;
    badge.classList.toggle('hidden', units.length === 0);
}

// ======================
// Pricing Preview
// ======================

function updatePricingPreview() {
    const pricingContainer = document.getElementById('pricingPreview');

    if (units.length === 0) {
        pricingContainer.classList.add('hidden');
        return;
    }

    // Build units data with multi-break information (saved units only)
    const unitsData = units.map(u => ({
        unit_number: u.unitNumber,
        has_multiple_breaks: u.hasMultipleBreaks || false,
        break_count: u.breakCount || null
    }));

    fetch('/app/api/repair-pricing/', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': getCookie('csrftoken')
        },
        body: JSON.stringify({ units: unitsData })
    })
    .then(response => {
        // Always parse JSON, even on error
        return response.json().then(data => {
            if (!response.ok) {
                throw new Error(data.error || `HTTP error! status: ${response.status}`);
            }
            return data;
        });
    })
    .then(data => {
        if (data.error) {
            console.error('Pricing API error:', data.error);
            // Hide pricing preview on error
            const pricingContainer = document.getElementById('pricingPreview');
            pricingContainer.classList.add('hidden');
            return;
        }
        displayPricingPreview(data);
    })
    .catch(error => {
        console.error('Error fetching pricing:', error);
        // Hide pricing preview on error
        const pricingContainer = document.getElementById('pricingPreview');
        pricingContainer.classList.add('hidden');
    });
}

/**
 * Display pricing preview with support for single repairs, multi-break exact counts, and multi-break estimates.
 *
 * For multi-break estimates (unknown break count), the total will display as a range.
 * For exact counts and single repairs, shows a single total amount.
 *
 * @param {Object} pricingData - Pricing data from API containing units array
 */
function displayPricingPreview(pricingData) {
    const container = document.getElementById('pricingPreview');
    const detailsDiv = document.getElementById('pricingDetails');

    // Track min/max totals to support range display when estimates are present
    let minTotalCost = 0;
    let maxTotalCost = 0;
    let hasEstimates = false;  // Flag to determine if we show range or single total
    let html = '<div class="space-y-2">';

    pricingData.units.forEach((unitData, index) => {
        const unit = units[index];
        let unitCost = 0;
        let unitPriceHtml = '';

        if (unitData.has_multiple_breaks && unitData.break_count) {
            // Multi-break with exact count - show breakdown
            // Add same price to both min and max (no range for exact counts)
            unitCost = unitData.total_price;
            minTotalCost += unitCost;
            maxTotalCost += unitCost;

            // Update individual unit card pricing
            const unitPriceEl = document.getElementById(`unit-price-${index}`);
            if (unitPriceEl) {
                unitPriceEl.innerHTML = `
                    Est. Cost: <span class="text-blue-700">${unitData.total_price_formatted}</span> (${unitData.break_count} breaks)
                    ${unitData.uses_custom_pricing ? '<span class="ml-1 text-xs bg-purple-100 text-purple-800 px-1.5 py-0.5 rounded">Custom</span>' : ''}
                `;
            }

            // Pricing preview with breakdown
            html += `
                <div class="bg-white rounded px-3 py-2 border border-blue-200">
                    <div class="flex justify-between items-center text-sm font-semibold mb-1">
                        <span>Unit ${escapeHtml(unitData.unit_number)} (${unitData.break_count} breaks)</span>
                        <span class="text-blue-700">${unitData.total_price_formatted}</span>
                    </div>
                    <div class="pl-3 space-y-0.5">
            `;
            unitData.breakdown.forEach(breakItem => {
                html += `
                    <div class="flex justify-between items-center text-xs text-gray-600">
                        <span>Break ${breakItem.break_number} (Repair #${breakItem.repair_number})</span>
                        <span>${breakItem.price_formatted}</span>
                    </div>
                `;
            });
            html += `
                    </div>
                </div>
            `;
        } else if (unitData.has_multiple_breaks && unitData.is_estimate) {
            // Multi-break estimate (unknown count) - show range and track for total
            // Add min/max separately to support range total display
            minTotalCost += unitData.min_price;
            maxTotalCost += unitData.max_price;
            hasEstimates = true;  // Flag that we have at least one estimate

            // Update individual unit card pricing
            const unitPriceEl = document.getElementById(`unit-price-${index}`);
            if (unitPriceEl) {
                unitPriceEl.innerHTML = `
                    Est. Range: <span class="text-blue-700">${unitData.range_formatted}</span>
                    ${unitData.uses_custom_pricing ? '<span class="ml-1 text-xs bg-purple-100 text-purple-800 px-1.5 py-0.5 rounded">Custom</span>' : ''}
                `;
            }

            html += `
                <div class="bg-white rounded px-3 py-2 border border-blue-200">
                    <div class="flex justify-between items-center text-sm">
                        <span>Unit ${escapeHtml(unitData.unit_number)} (Multiple breaks)</span>
                        <span class="font-semibold text-blue-700">${unitData.range_formatted}</span>
                    </div>
                    <div class="text-xs text-gray-600 mt-1">
                        Estimated ${unitData.min_breaks}-${unitData.max_breaks} breaks
                    </div>
                </div>
            `;
        } else {
            // Single repair - add same price to both min and max
            unitCost = unitData.price;
            minTotalCost += unitCost;
            maxTotalCost += unitCost;

            // Update individual unit card pricing
            const unitPriceEl = document.getElementById(`unit-price-${index}`);
            if (unitPriceEl) {
                unitPriceEl.innerHTML = `
                    Est. Cost: <span class="text-blue-700">${unitData.price_formatted}</span>
                    ${unitData.uses_custom_pricing ? '<span class="ml-1 text-xs bg-purple-100 text-purple-800 px-1.5 py-0.5 rounded">Custom</span>' : ''}
                `;
            }

            html += `
                <div class="flex justify-between items-center text-sm bg-white rounded px-3 py-2 border border-blue-200">
                    <span>Unit ${escapeHtml(unitData.unit_number)} (Repair #${unitData.next_repair_number})</span>
                    <span class="font-semibold">${unitData.price_formatted}</span>
                </div>
            `;
        }
    });

    html += '</div>';

    detailsDiv.innerHTML = html;

    // Update total display based on whether we have estimates
    const totalCostEl = document.getElementById('totalCost');
    if (hasEstimates) {
        // Show range when estimates are present
        totalCostEl.innerHTML = `${formatCurrency(minTotalCost)} - ${formatCurrency(maxTotalCost)} <span class="text-xs text-gray-600 font-normal">(Estimated range)</span>`;
    } else {
        // Show single total when all pricing is exact
        totalCostEl.textContent = formatCurrency(maxTotalCost);
    }

    container.classList.remove('hidden');
}

function formatCurrency(amount) {
    return '$' + amount.toFixed(2);
}

// ======================
// Form Submission
// ======================

function handleBatchSubmit(event) {
    event.preventDefault();

    if (units.length === 0) {
        alert('Please add at least one unit to submit.');
        return;
    }

    // Show confirmation modal
    showConfirmationModal();
}

function showConfirmationModal() {
    const modal = document.getElementById('confirmationModal');
    const summaryDiv = document.getElementById('confirmationSummary');

    let html = '<div class="space-y-2">';
    units.forEach((unit, index) => {
        let multiBreakInfo = '';
        if (unit.hasMultipleBreaks) {
            if (unit.breakCount) {
                multiBreakInfo = `<div class="text-blue-600"><i class="fas fa-layer-group"></i> ${unit.breakCount} breaks</div>`;
            } else {
                multiBreakInfo = '<div class="text-blue-600"><i class="fas fa-layer-group"></i> Multiple breaks (count unknown)</div>';
            }
        }

        html += `
            <div class="flex items-start space-x-2 text-sm bg-gray-50 p-2 rounded">
                <span class="font-semibold">${index + 1}.</span>
                <div class="flex-1">
                    <div><strong>Unit:</strong> ${escapeHtml(unit.unitNumber)}</div>
                    <div><strong>Damage:</strong> ${escapeHtml(unit.damageType)}</div>
                    ${multiBreakInfo}
                    ${unit.notes ? `<div class="text-gray-600">${escapeHtml(unit.notes)}</div>` : ''}
                    ${unit.photoDataUrl ? '<div class="text-green-600"><i class="fas fa-camera"></i> Photo attached</div>' : ''}
                </div>
            </div>
        `;
    });
    html += '</div>';

    summaryDiv.innerHTML = html;
    modal.classList.remove('hidden');
}

function closeConfirmationModal() {
    document.getElementById('confirmationModal').classList.add('hidden');
}

async function confirmAndSubmit() {
    closeConfirmationModal();

    // Show loading state
    const submitBtn = document.getElementById('submitBatchBtn');
    const originalText = submitBtn.innerHTML;
    submitBtn.disabled = true;
    submitBtn.innerHTML = '<i class="fas fa-spinner fa-spin mr-2"></i>Submitting...';

    try {
        // Create FormData with batch information
        const formData = new FormData();
        formData.append('batch_submission', 'true');
        formData.append('units_data', JSON.stringify(units.map(u => ({
            unitNumber: u.unitNumber,
            damageType: u.damageType,
            notes: u.notes,
            hasPhoto: !!u.photoFile,
            hasMultipleBreaks: u.hasMultipleBreaks || false,
            breakCount: u.breakCount || null,
            damageLocationX: u.damageLocationX || null,
            damageLocationY: u.damageLocationY || null
        }))));

        // Add photo files
        units.forEach((unit, index) => {
            if (unit.photoFile) {
                formData.append(`photo_${index}`, unit.photoFile);
            }
        });

        // Submit via fetch
        const response = await fetch(window.location.href, {
            method: 'POST',
            headers: {
                'X-CSRFToken': getCookie('csrftoken')
            },
            body: formData
        });

        if (response.ok) {
            // Parse JSON response
            const data = await response.json();

            // Clear localStorage on success
            localStorage.removeItem('customerRepairRequest');
            clearInterval(autosaveInterval);

            // Show success modal
            showSuccessModal();
        } else {
            // Try to parse error response
            let errorMessage = 'There was an error submitting your request. Please try again.';
            try {
                const errorData = await response.json();
                if (errorData.error) {
                    errorMessage = errorData.error;
                }
            } catch (e) {
                // If JSON parsing fails, use default error message
            }
            throw new Error(errorMessage);
        }
    } catch (error) {
        console.error('Error submitting batch:', error);
        alert(error.message || 'There was an error submitting your request. Please try again.');
        submitBtn.disabled = false;
        submitBtn.innerHTML = originalText;
    }
}

function showSuccessModal() {
    const modal = document.getElementById('successModal');
    const countSpan = document.getElementById('successUnitCount');
    countSpan.textContent = units.length;
    modal.classList.remove('hidden');
}

function closeSuccessModal() {
    window.location.href = '/app/';  // Redirect to dashboard
}

function createAnotherBatch() {
    units = [];
    renderUnitCards();
    updateSubmitButton();
    updatePricingPreview();
    document.getElementById('successModal').classList.add('hidden');
    localStorage.removeItem('customerRepairRequest');
}

// ======================
// LocalStorage Autosave
// ======================

function startAutosave() {
    // Save every 5 seconds
    autosaveInterval = setInterval(saveToLocalStorage, 5000);
}

function saveToLocalStorage() {
    if (units.length === 0) {
        localStorage.removeItem('customerRepairRequest');
        return;
    }

    const data = {
        units: units.map(u => ({
            unitNumber: u.unitNumber,
            damageType: u.damageType,
            notes: u.notes,
            photoDataUrl: u.photoDataUrl,
            photoName: u.photoName
            // Note: Cannot save File objects to localStorage
        })),
        timestamp: new Date().toISOString()
    };

    localStorage.setItem('customerRepairRequest', JSON.stringify(data));
}

function restoreFromLocalStorage(force = false) {
    const saved = localStorage.getItem('customerRepairRequest');

    if (!saved) return;

    const data = JSON.parse(saved);

    // Check if data is recent (within 24 hours)
    const savedTime = new Date(data.timestamp);
    const now = new Date();
    const hoursDiff = (now - savedTime) / (1000 * 60 * 60);

    if (hoursDiff > 24) {
        localStorage.removeItem('customerRepairRequest');
        return;
    }

    if (!force) {
        // Show restore prompt
        const prompt = document.getElementById('restoreDataPrompt');
        if (prompt) {
            prompt.classList.remove('hidden');
        }
        return;
    }

    // Restore data
    units = data.units.map(u => ({
        ...u,
        photoFile: null  // Cannot restore File objects
    }));

    renderUnitCards();
    updateSubmitButton();
    updatePricingPreview();
}

// ======================
// Utility Functions
// ======================

function getCookie(name) {
    // For CSRF token, try to get from DOM first (works with CSRF_COOKIE_HTTPONLY = True)
    if (name === 'csrftoken') {
        // Try to get from hidden input in form
        const csrfInput = document.querySelector('input[name="csrfmiddlewaretoken"]');
        if (csrfInput) {
            return csrfInput.value;
        }
        // Try to get from meta tag
        const csrfMeta = document.querySelector('meta[name="csrf-token"]');
        if (csrfMeta) {
            return csrfMeta.content;
        }
    }

    // Fallback to cookie reading (for non-httponly cookies)
    let cookieValue = null;
    if (document.cookie && document.cookie !== '') {
        const cookies = document.cookie.split(';');
        for (let i = 0; i < cookies.length; i++) {
            const cookie = cookies[i].trim();
            if (cookie.substring(0, name.length + 1) === (name + '=')) {
                cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
                break;
            }
        }
    }
    return cookieValue;
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function showFieldError(fieldId, message) {
    const field = document.getElementById(fieldId);
    const errorDiv = document.getElementById(fieldId + 'Error');

    if (errorDiv) {
        errorDiv.textContent = message;
        errorDiv.classList.remove('hidden');
    }

    if (field) {
        field.classList.add('border-red-500');
    }
}

function clearFieldError(fieldId) {
    const field = document.getElementById(fieldId);
    const errorDiv = document.getElementById(fieldId + 'Error');

    if (errorDiv) {
        errorDiv.classList.add('hidden');
    }

    if (field) {
        field.classList.remove('border-red-500');
    }
}

// ================ DAMAGE LOCATION DIAGRAM ================
function placeModalDamageMarker(xPercent, yPercent) {
    const marker = document.getElementById('modalDamageMarker');
    const xInput = document.getElementById('modalDamageLocationX');
    const yInput = document.getElementById('modalDamageLocationY');
    const locationText = document.getElementById('modalLocationText');
    const clearBtn = document.getElementById('modalClearLocationBtn');
    if (!marker) return;

    marker.style.left = xPercent + '%';
    marker.style.top = yPercent + '%';
    marker.style.display = 'block';
    xInput.value = xPercent.toFixed(1);
    yInput.value = yPercent.toFixed(1);

    const side = xPercent < 50 ? 'driver' : 'passenger';
    const vertical = yPercent < 33 ? 'upper' : (yPercent > 66 ? 'lower' : 'middle');
    locationText.textContent = 'Marked: ' + vertical + ' ' + side + ' side';
    clearBtn.style.display = 'inline';
}

function clearModalDamageMarker() {
    const marker = document.getElementById('modalDamageMarker');
    const xInput = document.getElementById('modalDamageLocationX');
    const yInput = document.getElementById('modalDamageLocationY');
    const locationText = document.getElementById('modalLocationText');
    const clearBtn = document.getElementById('modalClearLocationBtn');
    if (!marker) return;

    marker.style.display = 'none';
    xInput.value = '';
    yInput.value = '';
    locationText.textContent = 'Tap where the damage is on the windshield';
    clearBtn.style.display = 'none';
}

(function() {
    const diagram = document.getElementById('modalWindshieldDiagram');
    const clearBtn = document.getElementById('modalClearLocationBtn');
    if (!diagram) return;

    function handleInteraction(e) {
        e.preventDefault();
        const rect = diagram.getBoundingClientRect();
        const clientX = e.touches ? e.touches[0].clientX : e.clientX;
        const clientY = e.touches ? e.touches[0].clientY : e.clientY;
        const x = ((clientX - rect.left) / rect.width) * 100;
        const y = ((clientY - rect.top) / rect.height) * 100;
        placeModalDamageMarker(
            Math.max(2, Math.min(98, x)),
            Math.max(2, Math.min(98, y))
        );
    }

    diagram.addEventListener('click', handleInteraction);
    diagram.addEventListener('touchstart', handleInteraction, { passive: false });
    if (clearBtn) clearBtn.addEventListener('click', clearModalDamageMarker);
})();
