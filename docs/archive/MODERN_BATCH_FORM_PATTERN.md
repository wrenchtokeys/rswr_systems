# Modern Batch Form Pattern

**Author**: Claude Code
**Date**: November 2025
**Status**: Production-Ready Pattern
**Example**: Customer Portal Repair Request Form

## Overview

This document describes the modern batch form pattern implemented in the customer portal repair request form. This pattern can be replicated across the application for any form that needs to collect multiple related entries in a single session.

The pattern combines modal-based entry, state management, live previews (pricing/validation), photo handling, form autosave, and animated success feedback into a cohesive, professional user experience.

---

## Pattern Components

### 1. Architecture

```
┌─────────────────────────────────────────────────────┐
│                  Main Page Layout                    │
│  ┌──────────────────┐  ┌──────────────────────────┐ │
│  │   Items List     │  │   Summary Sidebar        │ │
│  │   (Cards)        │  │   - Live Totals          │ │
│  │                  │  │   - Pricing Preview      │ │
│  │   [Add Item]     │  │   - Submit Button        │ │
│  └──────────────────┘  └──────────────────────────┘ │
└─────────────────────────────────────────────────────┘
                      │
                      ▼
        ┌─────────────────────────────┐
        │    Modal: Add/Edit Item     │
        │  - Form Fields              │
        │  - Photo Upload             │
        │  - Inline Validation        │
        │  - Photo Preview            │
        └─────────────────────────────┘
                      │
                      ▼ (On Submit)
        ┌─────────────────────────────┐
        │   Confirmation Modal        │
        │  - Review All Items         │
        │  - Final Totals             │
        └─────────────────────────────┘
                      │
                      ▼ (On Confirm)
        ┌─────────────────────────────┐
        │    Success Modal            │
        │  - Animated Checkmark ✓     │
        │  - Summary Stats            │
        │  - Next Action Buttons      │
        └─────────────────────────────┘
```

### 2. File Structure

```
├── templates/
│   └── [app_name]/
│       └── batch_form.html          # Main template with modals
├── static/
│   ├── js/
│   │   └── batch_form.js            # State management & UI logic
│   └── css/
│       └── components/
│           └── batch-form.css       # Component styles & animations
├── apps/
│   └── [app_name]/
│       ├── views.py                 # Batch handling views
│       └── urls.py                  # API routes
```

---

## Implementation Guide

### Step 1: Create JavaScript State Management Module

**File**: `static/js/[feature]_batch.js`

```javascript
/**
 * Batch Form - State Management
 * Pattern: Modal-based multi-item entry with autosave
 */

// State
let items = [];
let editingIndex = null;
let autosaveInterval = null;

// Initialize
document.addEventListener('DOMContentLoaded', function() {
    setupEventListeners();
    restoreFromLocalStorage();
    startAutosave();
});

// ======================
// Event Listeners
// ======================

function setupEventListeners() {
    // Add item button
    document.getElementById('addItemBtn')?.addEventListener('click', openAddModal);

    // Save item button
    document.getElementById('saveItemBtn')?.addEventListener('click', saveItem);

    // Cancel modal
    document.getElementById('cancelModalBtn')?.addEventListener('click', closeModal);

    // Modal background click
    document.getElementById('addItemModal')?.addEventListener('click', (e) => {
        if (e.target.id === 'addItemModal') closeModal();
    });

    // Photo input
    document.getElementById('modalPhotoInput')?.addEventListener('change', handlePhotoSelection);

    // Form submission
    document.getElementById('batchForm')?.addEventListener('submit', handleBatchSubmit);

    // Restore/discard saved data
    document.getElementById('restoreSavedDataBtn')?.addEventListener('click', () => {
        restoreFromLocalStorage(true);
        document.getElementById('restoreDataPrompt').classList.add('hidden');
    });

    document.getElementById('discardSavedDataBtn')?.addEventListener('click', () => {
        localStorage.removeItem('batchFormData');
        document.getElementById('restoreDataPrompt').classList.add('hidden');
    });
}

// ======================
// Modal Management
// ======================

function openAddModal() {
    editingIndex = null;
    clearModalForm();
    document.getElementById('modalTitle').textContent = 'Add Item';
    document.getElementById('addItemModal').classList.remove('hidden');

    // Focus first input
    setTimeout(() => {
        document.getElementById('modalField1').focus();
    }, 100);
}

function openEditModal(index) {
    editingIndex = index;
    const item = items[index];

    // Populate modal with item data
    document.getElementById('modalField1').value = item.field1;
    document.getElementById('modalField2').value = item.field2 || '';

    // Show photo preview if exists
    if (item.photoDataUrl) {
        showPhotoPreview(item.photoDataUrl, item.photoName);
    }

    document.getElementById('modalTitle').textContent = 'Edit Item';
    document.getElementById('addItemModal').classList.remove('hidden');
}

function closeModal() {
    document.getElementById('addItemModal').classList.add('hidden');
    clearModalForm();
    editingIndex = null;
}

function clearModalForm() {
    document.getElementById('modalField1').value = '';
    document.getElementById('modalField2').value = '';
    document.getElementById('modalPhotoInput').value = '';
    document.getElementById('photoPreviewContainer').classList.add('hidden');
    clearFieldError('modalField1');
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

    // Validate
    const validation = validatePhoto(file);
    if (!validation.valid) {
        showFieldError('modalPhotoInput', validation.error);
        event.target.value = '';
        return;
    }

    // Preview
    const reader = new FileReader();
    reader.onload = (e) => showPhotoPreview(e.target.result, file.name);
    reader.readAsDataURL(file);
}

function validatePhoto(file) {
    if (file.size > 5 * 1024 * 1024) {
        return { valid: false, error: 'File size must be less than 5MB' };
    }

    const allowedTypes = ['image/jpeg', 'image/jpg', 'image/png', 'image/webp', 'image/heic'];
    const fileExt = file.name.toLowerCase().split('.').pop();
    const allowedExts = ['jpg', 'jpeg', 'png', 'webp', 'heic'];

    if (!allowedTypes.includes(file.type) && !allowedExts.includes(fileExt)) {
        return { valid: false, error: 'Please upload a valid image file' };
    }

    return { valid: true };
}

function showPhotoPreview(dataUrl, fileName) {
    document.getElementById('photoPreview').src = dataUrl;
    document.getElementById('photoFileName').textContent = fileName;
    document.getElementById('photoPreviewContainer').classList.remove('hidden');
}

function removePhoto() {
    document.getElementById('modalPhotoInput').value = '';
    document.getElementById('photoPreviewContainer').classList.add('hidden');
}

// ======================
// Item Management
// ======================

function saveItem() {
    const field1 = document.getElementById('modalField1').value.trim();

    // Validate required fields
    if (!field1) {
        showFieldError('modalField1', 'This field is required');
        return;
    }

    // Check for duplicates (if needed)
    const duplicateIndex = items.findIndex((item, i) =>
        item.field1.toLowerCase() === field1.toLowerCase() && i !== editingIndex
    );

    if (duplicateIndex !== -1) {
        showFieldError('modalField1', 'This item already exists in the batch');
        return;
    }

    // Create item object
    const item = {
        field1: field1,
        field2: document.getElementById('modalField2').value.trim(),
        photoDataUrl: null,
        photoName: null,
        photoFile: null
    };

    // Handle photo
    const photoInput = document.getElementById('modalPhotoInput');
    if (photoInput.files && photoInput.files[0]) {
        const reader = new FileReader();
        reader.onload = (e) => {
            item.photoDataUrl = e.target.result;
            item.photoName = photoInput.files[0].name;
            item.photoFile = photoInput.files[0];
            finalizeSaveItem(item);
        };
        reader.readAsDataURL(photoInput.files[0]);
    } else if (editingIndex !== null && items[editingIndex].photoDataUrl) {
        // Keep existing photo when editing
        item.photoDataUrl = items[editingIndex].photoDataUrl;
        item.photoName = items[editingIndex].photoName;
        item.photoFile = items[editingIndex].photoFile;
        finalizeSaveItem(item);
    } else {
        finalizeSaveItem(item);
    }
}

function finalizeSaveItem(item) {
    if (editingIndex !== null) {
        items[editingIndex] = item;
    } else {
        items.push(item);
    }

    renderItemCards();
    updateSubmitButton();
    updateLivePreview();  // Update pricing, totals, etc.
    closeModal();
    saveToLocalStorage();
}

function deleteItem(index) {
    if (confirm('Remove this item from the batch?')) {
        items.splice(index, 1);
        renderItemCards();
        updateSubmitButton();
        updateLivePreview();
        saveToLocalStorage();
    }
}

// ======================
// UI Rendering
// ======================

function renderItemCards() {
    const container = document.getElementById('itemsContainer');
    const emptyState = document.getElementById('emptyState');

    if (items.length === 0) {
        container.innerHTML = '';
        emptyState.classList.remove('hidden');
        return;
    }

    emptyState.classList.add('hidden');

    let html = '';
    items.forEach((item, index) => {
        const photoIcon = item.photoDataUrl
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
                            <div class="font-semibold text-lg">${escapeHtml(item.field1)}</div>
                        </div>
                    </div>
                    <div class="flex items-center space-x-2">
                        ${photoIcon}
                        <button type="button" onclick="openEditModal(${index})"
                            class="text-blue-600 hover:text-blue-800 text-sm">
                            <i class="fas fa-edit"></i> Edit
                        </button>
                        <button type="button" onclick="deleteItem(${index})"
                            class="text-red-600 hover:text-red-800 text-sm">
                            <i class="fas fa-trash"></i> Delete
                        </button>
                    </div>
                </div>
                ${item.photoDataUrl ? `
                    <div class="mt-2 mb-2">
                        <img src="${item.photoDataUrl}" alt="Preview"
                            class="h-24 w-auto rounded border border-gray-300 object-cover">
                    </div>
                ` : ''}
                <div id="item-preview-${index}" class="mt-3">
                    <!-- Live preview data here -->
                </div>
            </div>
        `;
    });

    container.innerHTML = html;
}

function updateSubmitButton() {
    const btn = document.getElementById('submitBatchBtn');
    const badge = document.getElementById('itemCountBadge');

    if (items.length === 0) {
        btn.disabled = true;
        btn.classList.add('opacity-50', 'cursor-not-allowed');
        btn.innerHTML = '<i class="fas fa-paper-plane mr-2"></i>Submit';
    } else {
        btn.disabled = false;
        btn.classList.remove('opacity-50', 'cursor-not-allowed');
        btn.innerHTML = `<i class="fas fa-paper-plane mr-2"></i>Submit ${items.length} Item${items.length > 1 ? 's' : ''}`;
    }

    badge.textContent = items.length;
    badge.classList.toggle('hidden', items.length === 0);
}

// ======================
// Live Preview (Pricing, Validation, etc.)
// ======================

function updateLivePreview() {
    const previewContainer = document.getElementById('livePreview');

    if (items.length === 0) {
        previewContainer.classList.add('hidden');
        return;
    }

    // Example: Fetch pricing/validation data
    fetch('/app/api/preview/', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': getCookie('csrftoken')
        },
        body: JSON.stringify({ items: items.map(i => i.field1) })
    })
    .then(response => response.json())
    .then(data => displayLivePreview(data))
    .catch(error => console.error('Preview error:', error));
}

function displayLivePreview(data) {
    // Update UI with live data
    document.getElementById('previewDetails').innerHTML = data.html;
    document.getElementById('livePreview').classList.remove('hidden');
}

// ======================
// Form Submission
// ======================

function handleBatchSubmit(event) {
    event.preventDefault();

    if (items.length === 0) {
        alert('Please add at least one item to submit.');
        return;
    }

    showConfirmationModal();
}

function showConfirmationModal() {
    const modal = document.getElementById('confirmationModal');
    const summaryDiv = document.getElementById('confirmationSummary');

    let html = '<div class="space-y-2">';
    items.forEach((item, index) => {
        html += `
            <div class="flex items-start space-x-2 text-sm bg-gray-50 p-2 rounded">
                <span class="font-semibold">${index + 1}.</span>
                <div class="flex-1">
                    <div><strong>Item:</strong> ${escapeHtml(item.field1)}</div>
                    ${item.photoDataUrl ? '<div class="text-green-600"><i class="fas fa-camera"></i> Photo attached</div>' : ''}
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

    const submitBtn = document.getElementById('submitBatchBtn');
    const originalText = submitBtn.innerHTML;
    submitBtn.disabled = true;
    submitBtn.innerHTML = '<i class="fas fa-spinner fa-spin mr-2"></i>Submitting...';

    try {
        const formData = new FormData();
        formData.append('batch_submission', 'true');
        formData.append('items_data', JSON.stringify(items.map(i => ({
            field1: i.field1,
            field2: i.field2,
            hasPhoto: !!i.photoFile
        }))));

        // Add photos
        items.forEach((item, index) => {
            if (item.photoFile) {
                formData.append(`photo_${index}`, item.photoFile);
            }
        });

        const response = await fetch(window.location.href, {
            method: 'POST',
            headers: { 'X-CSRFToken': getCookie('csrftoken') },
            body: formData
        });

        if (response.ok) {
            localStorage.removeItem('batchFormData');
            clearInterval(autosaveInterval);
            showSuccessModal();
        } else {
            throw new Error('Submission failed');
        }
    } catch (error) {
        console.error('Error:', error);
        alert('There was an error submitting. Please try again.');
        submitBtn.disabled = false;
        submitBtn.innerHTML = originalText;
    }
}

function showSuccessModal() {
    document.getElementById('successItemCount').textContent = items.length;
    document.getElementById('successModal').classList.remove('hidden');
}

function closeSuccessModal() {
    window.location.href = '/app/';  // Redirect to dashboard
}

function createAnotherBatch() {
    items = [];
    renderItemCards();
    updateSubmitButton();
    updateLivePreview();
    document.getElementById('successModal').classList.add('hidden');
    localStorage.removeItem('batchFormData');
}

// ======================
// LocalStorage Autosave
// ======================

function startAutosave() {
    autosaveInterval = setInterval(saveToLocalStorage, 5000);
}

function saveToLocalStorage() {
    if (items.length === 0) {
        localStorage.removeItem('batchFormData');
        return;
    }

    const data = {
        items: items.map(i => ({
            field1: i.field1,
            field2: i.field2,
            photoDataUrl: i.photoDataUrl,
            photoName: i.photoName
            // Note: Cannot save File objects
        })),
        timestamp: new Date().toISOString()
    };

    localStorage.setItem('batchFormData', JSON.stringify(data));
}

function restoreFromLocalStorage(force = false) {
    const saved = localStorage.getItem('batchFormData');
    if (!saved) return;

    const data = JSON.parse(saved);

    // Check age (24 hours)
    const savedTime = new Date(data.timestamp);
    const hoursDiff = (new Date() - savedTime) / (1000 * 60 * 60);

    if (hoursDiff > 24) {
        localStorage.removeItem('batchFormData');
        return;
    }

    if (!force) {
        document.getElementById('restoreDataPrompt')?.classList.remove('hidden');
        return;
    }

    items = data.items.map(i => ({ ...i, photoFile: null }));
    renderItemCards();
    updateSubmitButton();
    updateLivePreview();
}

// ======================
// Utilities
// ======================

function getCookie(name) {
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
```

---

### Step 2: Create Component Styles with Animations

**File**: `static/css/components/batch-form.css`

```css
/**
 * Modern Batch Form Styles
 * Includes animations, transitions, and accessibility features
 */

/* ===========================
   Modal Styles
   =========================== */

.modal-overlay {
    background-color: rgba(0, 0, 0, 0.5);
    backdrop-filter: blur(4px);
}

.modal-container {
    max-height: 90vh;
    overflow-y: auto;
    animation: slideUp 0.3s ease-out;
}

@keyframes slideUp {
    from {
        opacity: 0;
        transform: translateY(20px);
    }
    to {
        opacity: 1;
        transform: translateY(0);
    }
}

.modal-header {
    background: linear-gradient(135deg, #2563eb 0%, #1d4ed8 100%);
}

/* ===========================
   Item Cards
   =========================== */

.item-card {
    transition: all 0.2s ease;
}

.item-card:hover {
    transform: translateY(-2px);
    box-shadow: 0 4px 12px rgba(37, 99, 235, 0.15);
}

/* ===========================
   Photo Preview
   =========================== */

.photo-preview-container {
    position: relative;
    display: inline-block;
}

.photo-preview-image {
    max-height: 200px;
    border-radius: 8px;
    border: 2px solid #e5e7eb;
    object-fit: cover;
}

.photo-remove-btn {
    position: absolute;
    top: -8px;
    right: -8px;
    background: #ef4444;
    color: white;
    border-radius: 50%;
    width: 28px;
    height: 28px;
    display: flex;
    align-items: center;
    justify-content: center;
    cursor: pointer;
    box-shadow: 0 2px 8px rgba(239, 68, 68, 0.4);
    transition: all 0.2s;
}

.photo-remove-btn:hover {
    background: #dc2626;
    transform: scale(1.1);
}

/* ===========================
   Upload Zone
   =========================== */

.upload-zone {
    border: 2px dashed #d1d5db;
    background: #f9fafb;
    transition: all 0.2s;
    cursor: pointer;
}

.upload-zone:hover {
    border-color: #3b82f6;
    background: #eff6ff;
}

.upload-zone.drag-over {
    border-color: #2563eb;
    background: #dbeafe;
    transform: scale(1.02);
}

/* ===========================
   Buttons
   =========================== */

.btn-primary {
    background: linear-gradient(135deg, #3b82f6 0%, #2563eb 100%);
    transition: all 0.2s;
}

.btn-primary:hover:not(:disabled) {
    background: linear-gradient(135deg, #2563eb 0%, #1d4ed8 100%);
    transform: translateY(-1px);
    box-shadow: 0 4px 12px rgba(37, 99, 235, 0.3);
}

.btn-primary:active:not(:disabled) {
    transform: translateY(0);
}

.btn-secondary {
    transition: all 0.2s;
    background-color: #f9fafb;
}

.btn-secondary:hover {
    background-color: #f3f4f6;
    transform: translateY(-1px);
}

/* ===========================
   SUCCESS CHECKMARK ANIMATION
   This is the animated checkmark that appears in the success modal
   =========================== */

.success-checkmark {
    width: 80px;
    height: 80px;
    margin: 0 auto 1rem;
}

.success-checkmark .check-icon {
    width: 80px;
    height: 80px;
    position: relative;
    border-radius: 50%;
    background: #10b981;
    animation: scaleIn 0.5s ease-out;
}

.success-checkmark .check-icon::after {
    content: '✓';
    position: absolute;
    top: 50%;
    left: 50%;
    transform: translate(-50%, -50%);
    color: white;
    font-size: 3rem;
    font-weight: bold;
}

@keyframes scaleIn {
    0% {
        transform: scale(0);
    }
    50% {
        transform: scale(1.1);
    }
    100% {
        transform: scale(1);
    }
}

/* ===========================
   Empty State
   =========================== */

.empty-state {
    padding: 3rem 1rem;
    text-align: center;
    background: #f9fafb;
    border: 2px dashed #d1d5db;
    border-radius: 0.75rem;
}

.empty-state-icon {
    font-size: 4rem;
    color: #d1d5db;
    margin-bottom: 1rem;
}

/* ===========================
   Form Inputs
   =========================== */

.form-input {
    transition: all 0.2s;
}

.form-input:focus {
    border-color: #3b82f6;
    ring: 2px;
    ring-color: rgba(59, 130, 246, 0.3);
    outline: none;
}

.form-input.error {
    border-color: #ef4444;
}

.form-error {
    color: #ef4444;
    font-size: 0.875rem;
    margin-top: 0.25rem;
    display: flex;
    align-items: center;
    gap: 0.25rem;
}

/* ===========================
   Loading States
   =========================== */

.spinner {
    animation: spin 1s linear infinite;
}

@keyframes spin {
    from {
        transform: rotate(0deg);
    }
    to {
        transform: rotate(360deg);
    }
}

/* ===========================
   Restore Prompt
   =========================== */

.restore-prompt {
    background: linear-gradient(135deg, #fef3c7 0%, #fde68a 100%);
    border-left: 4px solid #f59e0b;
    animation: slideDown 0.4s ease-out;
}

@keyframes slideDown {
    from {
        opacity: 0;
        transform: translateY(-20px);
    }
    to {
        opacity: 1;
        transform: translateY(0);
    }
}

/* ===========================
   Responsive Design
   =========================== */

@media (max-width: 640px) {
    .modal-container {
        max-width: 95%;
        margin: 1rem auto;
    }
}

/* ===========================
   Accessibility
   =========================== */

.focus-visible:focus {
    outline: 2px solid #3b82f6;
    outline-offset: 2px;
}

@media (prefers-contrast: high) {
    .item-card {
        border-width: 3px;
    }
}

@media (prefers-reduced-motion: reduce) {
    *,
    *::before,
    *::after {
        animation-duration: 0.01ms !important;
        animation-iteration-count: 1 !important;
        transition-duration: 0.01ms !important;
    }
}
```

---

### Step 3: Create Template Structure

**File**: `templates/[app_name]/batch_form.html`

Key elements to include:

1. **Header** - With title and back button
2. **Restore Data Prompt** - Shows if localStorage has saved data
3. **Main Layout** - Two-column grid (items list + sidebar)
4. **Items Container** - Where item cards render
5. **Empty State** - Shows when no items added
6. **Sidebar** - Live preview, totals, submit button
7. **Add/Edit Modal** - Form fields with photo upload
8. **Confirmation Modal** - Review before submit
9. **Success Modal** - With animated checkmark

See `templates/customer_portal/request_repair.html` for complete example.

---

### Step 4: Backend Implementation

**File**: `apps/[app_name]/views.py`

```python
import json
import uuid
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import render, redirect
from django.contrib import messages

def batch_form_view(request):
    """Main batch form view"""
    if request.method == 'POST':
        is_batch = request.POST.get('batch_submission') == 'true'

        if is_batch:
            return handle_batch_submission(request)
        else:
            return handle_single_submission(request)

    return render(request, 'app/batch_form.html')


def handle_batch_submission(request):
    """Process batch submission with atomic transaction"""
    try:
        items_data_json = request.POST.get('items_data')
        if not items_data_json:
            messages.error(request, "No data provided.")
            return render(request, 'app/batch_form.html')

        items_data = json.loads(items_data_json)

        if not items_data:
            messages.error(request, "Please add at least one item.")
            return render(request, 'app/batch_form.html')

        # Generate batch ID
        batch_id = uuid.uuid4()

        # Create all items atomically
        created_items = []
        with transaction.atomic():
            for index, item_data in enumerate(items_data):
                field1 = item_data.get('field1', '').strip()

                if not field1:
                    continue

                # Get photo if provided
                photo_file = None
                if item_data.get('hasPhoto'):
                    photo_key = f'photo_{index}'
                    photo_file = request.FILES.get(photo_key)

                # Create item
                item = YourModel.objects.create(
                    field1=field1,
                    field2=item_data.get('field2'),
                    photo=photo_file,
                    batch_id=batch_id
                )
                created_items.append(item)

        count = len(created_items)
        messages.success(
            request,
            f"Successfully submitted {count} item{'s' if count != 1 else ''}!"
        )
        return redirect('dashboard')

    except json.JSONDecodeError:
        messages.error(request, "Invalid data format.")
        return render(request, 'app/batch_form.html')
    except Exception as e:
        logging.error(f"Batch submission error: {str(e)}")
        messages.error(request, f"Error: {str(e)}")
        return render(request, 'app/batch_form.html')


def live_preview_api(request):
    """API endpoint for live preview (pricing, validation, etc.)"""
    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=405)

    try:
        data = json.loads(request.body)
        items = data.get('items', [])

        # Calculate preview data
        preview_data = calculate_preview(items)

        return JsonResponse(preview_data)

    except Exception as e:
        logging.error(f"Preview API error: {str(e)}")
        return JsonResponse({'error': 'An error occurred'}, status=500)
```

---

## Key Features Breakdown

### 1. Animated Success Checkmark

The signature feature - a satisfying animated checkmark that appears on successful submission.

**HTML**:
```html
<div class="success-checkmark">
    <div class="check-icon"></div>
</div>
```

**CSS** (already in the pattern above):
- Scales from 0 to 1.1 to 1 (bounce effect)
- Green circle background
- White checkmark character
- 0.5s animation duration

### 2. Photo Preview with FileReader

Immediately shows uploaded photos as thumbnails:

```javascript
function handlePhotoSelection(event) {
    const file = event.target.files[0];
    const reader = new FileReader();
    reader.onload = (e) => {
        document.getElementById('photoPreview').src = e.target.result;
        document.getElementById('photoPreviewContainer').classList.remove('hidden');
    };
    reader.readAsDataURL(file);
}
```

### 3. LocalStorage Autosave

Prevents data loss:

```javascript
// Save every 5 seconds
setInterval(() => {
    if (items.length > 0) {
        localStorage.setItem('batchFormData', JSON.stringify({
            items: items,
            timestamp: new Date().toISOString()
        }));
    }
}, 5000);
```

### 4. Live Preview API

Real-time pricing/validation updates:

```javascript
function updateLivePreview() {
    fetch('/app/api/preview/', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': getCookie('csrftoken')
        },
        body: JSON.stringify({ items: items })
    })
    .then(response => response.json())
    .then(data => displayPreview(data));
}
```

---

## Customization Checklist

When adapting this pattern to a new use case:

- [ ] Replace "item" terminology with your domain (e.g., "unit", "product", "entry")
- [ ] Update field names in modal (field1, field2 → your fields)
- [ ] Customize item card display (what to show in each card)
- [ ] Add/remove photo upload if needed
- [ ] Implement live preview API for your use case
- [ ] Update validation rules for your requirements
- [ ] Customize empty state message and icon
- [ ] Update success modal text
- [ ] Add model fields: `batch_id` (UUIDField, nullable, indexed)
- [ ] Create URL route for live preview API
- [ ] Test autosave restore flow

---

## Complete Example Reference

See the customer portal repair request form for a complete, production-ready implementation:

- **Template**: `templates/customer_portal/request_repair.html`
- **JavaScript**: `static/js/customer_repair_request.js`
- **CSS**: `static/css/components/customer-repair-request.css`
- **Views**: `apps/customer_portal/views.py` (lines 901-1172)
- **URLs**: `apps/customer_portal/urls.py`
- **Live Demo**: http://localhost:8000/app/repairs/request/

---

## Best Practices

1. **Always use `@transaction.atomic()`** for batch submissions
2. **Validate on both client and server** - never trust client-side only
3. **Provide visual feedback** at every step (loading states, animations)
4. **Save to LocalStorage frequently** (every 5s is good)
5. **Show photo previews immediately** - users love instant feedback
6. **Use debouncing** for live preview API calls (500ms recommended)
7. **Make buttons readable** - ensure sufficient contrast
8. **Test on mobile** - modals should work well on small screens
9. **Support keyboard navigation** - modal should close on Esc
10. **Add ARIA labels** for screen reader accessibility

---

## Browser Compatibility

Tested and working on:
- Chrome/Edge 90+
- Firefox 88+
- Safari 14+
- Mobile Safari (iOS 14+)
- Chrome Android

Requires:
- JavaScript enabled
- LocalStorage support
- FileReader API (for photo previews)
- Fetch API (for live previews)

---

## Performance Considerations

- **Photo previews**: Use `readAsDataURL()` - creates data URLs (can be large for big images)
- **LocalStorage limits**: ~5-10MB total, photos stored as base64 (avoid storing many large photos)
- **Autosave frequency**: 5s is good balance between UX and performance
- **API debouncing**: Essential for live preview to avoid hammering server
- **Batch size**: Test with 50+ items to ensure good performance

---

## Troubleshooting

**Modal won't close**:
- Check z-index conflicts
- Ensure event listeners are attached

**Photos not previewing**:
- Check FileReader browser support
- Validate file type before reading
- Check for JavaScript errors in console

**Autosave not working**:
- Check LocalStorage isn't full
- Verify localStorage is enabled in browser
- Check for quota exceeded errors

**Submit button stays disabled**:
- Check `updateSubmitButton()` is being called
- Verify items array has elements
- Check for JavaScript errors

---

## Future Enhancements

Ideas for extending this pattern:

1. **Drag-and-drop reordering** - Let users rearrange items
2. **Bulk operations** - Select multiple items to edit/delete
3. **Templates** - Save common batches as templates
4. **Export/Import** - JSON/CSV import for bulk entry
5. **Offline support** - Service worker for full offline capability
6. **Real-time collaboration** - WebSocket updates for team editing
7. **Undo/Redo** - Command pattern for action history
8. **Keyboard shortcuts** - Power user features

---

## License

This pattern is part of the RS Systems project and follows the same license.

---

**Questions?** See the complete working example in the customer portal or ask the development team.
