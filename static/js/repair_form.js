/**
 * Repair Form JavaScript
 * Professional SaaS-grade form interactions with photo previews and autosave
 */

// ================ IMAGE COMPRESSION UTILITY ================
// Now static/js/image_compress.js, loaded before this file. It was copied into
// this file and into repair_form.js, which is why the unified job form -- the
// page every "New job" link points at -- ended up posting raw phone photos
// straight into a 413.


document.addEventListener('DOMContentLoaded', function() {
    const form = document.getElementById('repairForm');
    if (!form) return;

    // ================ INITIALIZATION ================
    const elements = {
        customerSelect: document.getElementById('id_customer'),
        unitNumberInput: document.getElementById('id_unit_number'),
        warningDiv: document.getElementById('warningDiv'),
        queueStatusSelect: document.getElementById('id_queue_status'),
        photoRequirementWarning: document.getElementById('photoRequirementWarning'),
        beforePhotoInput: document.getElementById('id_damage_photo_before'),
        afterPhotoInput: document.getElementById('id_damage_photo_after'),
        beforePhotoPreview: document.getElementById('beforePhotoPreview'),
        afterPhotoPreview: document.getElementById('afterPhotoPreview'),
        beforeUploadArea: document.getElementById('beforeUploadArea'),
        afterUploadArea: document.getElementById('afterUploadArea'),
    };

    // Initialize autosave
    const autosave = new FormAutosave('repairForm', {
        saveDelay: 2000,
        excludeFields: ['csrfmiddlewaretoken', 'damage_photo_before', 'damage_photo_after', 'customer_submitted_photo', 'repair_date',
            // Tap-to-crop coords: restoring them would orphan them from a
            // photo the autosave can't restore.
            'crop_x_damage_photo_before', 'crop_y_damage_photo_before',
            'crop_x_damage_photo_after', 'crop_y_damage_photo_after'],
        showIndicator: true,
        confirmRestore: true,
        onRestore: (data) => {
            console.log('Form data restored from autosave');
            // Re-check existing repair after restore
            if (elements.customerSelect && elements.unitNumberInput) {
                checkExistingRepair();
            }
        }
    });

    // ================ REPAIR DATE INITIALIZATION ================
    // Set repair date to current time in user's local timezone
    // This ensures technicians see the correct local time regardless of server timezone
    // Note: We always set the current time for new repairs (no check for existing value)
    // Existing repairs will have their value set by Django backend (forms.py)
    const repairDateInput = document.getElementById('id_repair_date');
    if (repairDateInput) {
        // Only set if field is empty (new repair form)
        // For existing repairs, Django will have already set the value
        if (!repairDateInput.value) {
            const now = new Date();
            const year = now.getFullYear();
            const month = String(now.getMonth() + 1).padStart(2, '0');
            const day = String(now.getDate()).padStart(2, '0');
            const hours = String(now.getHours()).padStart(2, '0');
            const minutes = String(now.getMinutes()).padStart(2, '0');
            const dateTimeString = `${year}-${month}-${day}T${hours}:${minutes}`;
            repairDateInput.value = dateTimeString;
            console.log(`Repair date initialized to user's local time: ${dateTimeString}`);
        }
    }

    // ================ PHOTO REQUIREMENT WARNING ================
    function updatePhotoWarning() {
        if (elements.queueStatusSelect && elements.queueStatusSelect.value === 'COMPLETED') {
            elements.photoRequirementWarning.classList.remove('hidden');
        } else if (elements.photoRequirementWarning) {
            elements.photoRequirementWarning.classList.add('hidden');
        }
    }

    if (elements.queueStatusSelect) {
        updatePhotoWarning();
        elements.queueStatusSelect.addEventListener('change', updatePhotoWarning);
    }

    // ================ DUPLICATE REPAIR CHECK ================
    function checkExistingRepair() {
        const customerId = elements.customerSelect?.value;
        const unitNumber = elements.unitNumberInput?.value;

        if (customerId && unitNumber) {
            const url = `/tech/api/check-existing-repair/?customer=${customerId}&unit_number=${unitNumber}`;

            fetch(url)
                .then(response => response.json())
                .then(data => {
                    if (data.existing_repair) {
                        elements.warningDiv.innerHTML = `
                            <div class="flex">
                                <div class="flex-shrink-0">
                                    <i class="fas fa-exclamation-triangle text-yellow-400 text-lg"></i>
                                </div>
                                <div class="ml-3">
                                    <p class="text-sm text-yellow-700">
                                        ${data.warning_message}
                                        <a href="/tech/repairs/${data.repair_id}/"
                                           class="font-medium underline text-yellow-700 hover:text-yellow-600 ml-2">
                                            <i class="fas fa-external-link-alt mr-1"></i>View existing repair
                                        </a>
                                    </p>
                                </div>
                            </div>
                        `;
                        elements.warningDiv.classList.remove('hidden');
                    } else {
                        elements.warningDiv.classList.add('hidden');
                    }
                })
                .catch(error => console.error('Error checking existing repair:', error));
        } else {
            elements.warningDiv.classList.add('hidden');
        }
    }

    if (elements.unitNumberInput) {
        elements.unitNumberInput.addEventListener('blur', checkExistingRepair);
    }
    if (elements.customerSelect) {
        elements.customerSelect.addEventListener('change', checkExistingRepair);
    }

    // ================ PHOTO UPLOAD & PREVIEW ================

    /**
     * Create photo preview element
     */
    function createPhotoPreview(file, previewContainer, inputElement) {
        // Clear existing preview
        previewContainer.innerHTML = '';

        // Create preview container
        const previewDiv = document.createElement('div');
        previewDiv.className = 'photo-preview-container fade-in';

        // Create image element
        const img = document.createElement('img');
        img.className = 'photo-preview-image';

        // Read file and display
        const reader = new FileReader();
        reader.onload = function(e) {
            img.src = e.target.result;
        };
        reader.readAsDataURL(file);

        // Create info section
        const infoDiv = document.createElement('div');
        infoDiv.className = 'photo-preview-info';

        const nameSpan = document.createElement('span');
        nameSpan.className = 'photo-preview-name';
        nameSpan.innerHTML = `<i class="fas fa-file-image mr-1"></i> ${file.name}`;

        const sizeSpan = document.createElement('span');
        sizeSpan.className = 'photo-preview-size';
        sizeSpan.textContent = formatFileSize(file.size);

        const deleteBtn = document.createElement('button');
        deleteBtn.type = 'button';
        deleteBtn.className = 'photo-preview-delete';
        deleteBtn.innerHTML = '<i class="fas fa-trash-alt mr-1"></i> Remove';
        deleteBtn.addEventListener('click', function() {
            previewContainer.innerHTML = '';
            inputElement.value = '';
            // Dropping the photo also drops any tap-to-crop tap on it.
            if (window.PhotoTapCrop) window.PhotoTapCrop.clear(inputElement);
        });

        infoDiv.appendChild(nameSpan);
        infoDiv.appendChild(sizeSpan);
        infoDiv.appendChild(deleteBtn);

        previewDiv.appendChild(img);
        previewDiv.appendChild(infoDiv);

        previewContainer.appendChild(previewDiv);
    }

    /**
     * Format file size for display
     */
    function formatFileSize(bytes) {
        if (bytes === 0) return '0 Bytes';
        const k = 1024;
        const sizes = ['Bytes', 'KB', 'MB', 'GB'];
        const i = Math.floor(Math.log(bytes) / Math.log(k));
        return Math.round(bytes / Math.pow(k, i) * 100) / 100 + ' ' + sizes[i];
    }

    /**
     * Validate photo file
     */
    function validatePhotoFile(file) {
        const maxSize = 5 * 1024 * 1024; // 5MB
        const allowedTypes = ['image/jpeg', 'image/jpg', 'image/png', 'image/webp', 'image/heic'];

        if (file.size > maxSize) {
            UI.toast(`File size (${formatFileSize(file.size)}) exceeds the 5MB maximum. Please choose a smaller file.`, 'warning');
            return false;
        }

        if (!allowedTypes.includes(file.type) && !file.name.toLowerCase().endsWith('.heic')) {
            UI.toast('Invalid file type. Please upload a JPG, PNG, WebP, or HEIC image.', 'warning');
            return false;
        }

        return true;
    }

    /**
     * Handle photo input change with compression
     */
    function handlePhotoChange(inputElement, previewContainer) {
        return async function(e) {
            const files = e.target.files;
            if (files.length === 0) return;

            const file = files[0];

            if (!validatePhotoFile(file)) {
                inputElement.value = '';
                return;
            }

            // Show compression indicator
            previewContainer.innerHTML = '<div class="text-center p-4"><i class="fas fa-spinner fa-spin text-blue-500 text-2xl"></i><p class="text-sm text-gray-500 mt-2">Optimizing image...</p></div>';

            try {
                // Compress the image
                const compressedFile = await ImageCompressor.compress(file);

                // Replace the input file with compressed version
                ImageCompressor.replaceInputFile(inputElement, compressedFile);

                // Show preview of compressed image
                createPhotoPreview(compressedFile, previewContainer, inputElement);
                offerTapCrop(inputElement, compressedFile);
            } catch (error) {
                console.error('Compression error:', error);
                // Fall back to original file
                createPhotoPreview(file, previewContainer, inputElement);
                offerTapCrop(inputElement, file);
            }
        };
    }

    // Let photo_tap_crop.js (if loaded) offer the "tap the break" modal for
    // the photo that actually ended up in the input. This form bypasses
    // image_compress.js's auto-wiring, so it dispatches the event itself.
    function offerTapCrop(inputElement, file) {
        let evt;
        try {
            evt = new CustomEvent('photocrop:offer', { detail: { file: file }, bubbles: true });
        } catch (e) {
            evt = document.createEvent('CustomEvent');
            evt.initCustomEvent('photocrop:offer', true, false, { file: file });
        }
        inputElement.dispatchEvent(evt);
    }

    // Attach photo change handlers
    if (elements.beforePhotoInput && elements.beforePhotoPreview) {
        elements.beforePhotoInput.addEventListener('change',
            handlePhotoChange(elements.beforePhotoInput, elements.beforePhotoPreview)
        );
    }

    if (elements.afterPhotoInput && elements.afterPhotoPreview) {
        elements.afterPhotoInput.addEventListener('change',
            handlePhotoChange(elements.afterPhotoInput, elements.afterPhotoPreview)
        );
    }

    // ================ DRAG & DROP FUNCTIONALITY ================

    /**
     * Setup drag and drop for photo upload areas
     */
    function setupDragDrop(uploadArea, inputElement, previewContainer) {
        if (!uploadArea) return;

        const events = ['dragenter', 'dragover', 'dragleave', 'drop'];

        // Prevent defaults for all drag events
        events.forEach(eventName => {
            uploadArea.addEventListener(eventName, preventDefaults, false);
            document.body.addEventListener(eventName, preventDefaults, false);
        });

        function preventDefaults(e) {
            e.preventDefault();
            e.stopPropagation();
        }

        // Highlight on drag over
        ['dragenter', 'dragover'].forEach(eventName => {
            uploadArea.addEventListener(eventName, () => {
                uploadArea.classList.add('drag-over');
            });
        });

        ['dragleave', 'drop'].forEach(eventName => {
            uploadArea.addEventListener(eventName, () => {
                uploadArea.classList.remove('drag-over');
            });
        });

        // Handle drop with compression
        uploadArea.addEventListener('drop', async function(e) {
            const dt = e.dataTransfer;
            const files = dt.files;

            if (files.length > 0) {
                const file = files[0];

                if (file.type.startsWith('image/') || file.name.toLowerCase().endsWith('.heic')) {
                    if (validatePhotoFile(file)) {
                        // Show compression indicator
                        previewContainer.innerHTML = '<div class="text-center p-4"><i class="fas fa-spinner fa-spin text-blue-500 text-2xl"></i><p class="text-sm text-gray-500 mt-2">Optimizing image...</p></div>';

                        try {
                            // Compress the image
                            const compressedFile = await ImageCompressor.compress(file);

                            // Replace the input file with compressed version
                            ImageCompressor.replaceInputFile(inputElement, compressedFile);

                            // Create preview
                            createPhotoPreview(compressedFile, previewContainer, inputElement);
                            offerTapCrop(inputElement, compressedFile);
                        } catch (error) {
                            console.error('Compression error:', error);
                            // Fall back to original
                            const dataTransfer = new DataTransfer();
                            dataTransfer.items.add(file);
                            inputElement.files = dataTransfer.files;
                            createPhotoPreview(file, previewContainer, inputElement);
                            offerTapCrop(inputElement, file);
                        }
                    }
                } else {
                    UI.toast('Please drop an image file (PNG, JPG, WebP, or HEIC)', 'warning');
                }
            }
        });
    }

    // Setup drag & drop for both upload areas
    setupDragDrop(elements.beforeUploadArea, elements.beforePhotoInput, elements.beforePhotoPreview);
    setupDragDrop(elements.afterUploadArea, elements.afterPhotoInput, elements.afterPhotoPreview);

    // ================ FORM STYLING ENHANCEMENTS ================

    /**
     * Add proper classes to Django-generated form fields
     */
    function styleFormFields() {
        // Style all select elements
        const selects = form.querySelectorAll('select');
        selects.forEach(select => {
            if (!select.classList.contains('icon-field-input')) {
                select.classList.add('icon-field-input');
            }
        });

        // Style textarea elements
        const textareas = form.querySelectorAll('textarea');
        textareas.forEach(textarea => {
            if (!textarea.classList.contains('icon-field-input')) {
                textarea.classList.add('icon-field-input');
            }
        });

        // Style readonly customer notes
        const customerNotes = document.getElementById('id_customer_notes');
        if (customerNotes) {
            customerNotes.classList.add('bg-gray-50', 'text-gray-600');
            customerNotes.setAttribute('readonly', 'true');
        }
    }

    styleFormFields();

    // ================ FORM SUBMISSION ================

    form.addEventListener('submit', function(e) {
        // Clear autosave on successful submit
        autosave.clearSavedData();

        // Optional: Show loading indicator
        const submitBtn = form.querySelector('button[type="submit"]');
        if (submitBtn) {
            submitBtn.disabled = true;
            submitBtn.innerHTML = '<i class="fas fa-spinner spin mr-2"></i> Saving...';
        }
    });

    // ================ VISCOSITY SUGGESTION BASED ON TEMPERATURE ================
    // Now static/js/viscosity_suggestion.js (loaded just before this file). It
    // wires itself to #viscositySuggestion from that element's data- attributes,
    // so this form, the job form and the multi-break modal cannot drift apart
    // again -- which is exactly how the job form ended up with no suggestion at
    // all and this one kept rendering the shop's text through innerHTML.

    // ================ CONSOLE INFO ================
    console.log('✅ Repair Form Enhanced:');
    console.log('   - Autosave enabled');
    console.log('   - Photo previews active');
    console.log('   - Drag & drop support enabled');
    console.log('   - Duplicate repair check ready');
    console.log('   - Mobile camera capture optimized');
    console.log('   - Smart viscosity suggestions enabled');
});
