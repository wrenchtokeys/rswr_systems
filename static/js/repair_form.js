/**
 * Repair Form JavaScript
 * Professional SaaS-grade form interactions with photo previews and autosave
 */

// ================ IMAGE COMPRESSION UTILITY ================
// Compresses images before upload to improve mobile performance
// Settings optimized for AI training: 2048px max, 85% quality
const ImageCompressor = {
    MAX_DIMENSION: 2048,  // Max width or height in pixels
    QUALITY: 0.85,        // JPEG quality (0-1)

    /**
     * Compress an image file
     * @param {File} file - The original image file
     * @returns {Promise<File>} - Compressed image file
     */
    compress: function(file) {
        return new Promise((resolve, reject) => {
            // Skip compression for small files (< 500KB)
            if (file.size < 500 * 1024) {
                console.log('Image already small, skipping compression:', file.size);
                resolve(file);
                return;
            }

            // Skip HEIC files - let server handle conversion
            if (file.name.toLowerCase().endsWith('.heic') || file.name.toLowerCase().endsWith('.heif')) {
                console.log('HEIC file detected, server will handle conversion');
                resolve(file);
                return;
            }

            const img = new Image();
            const canvas = document.createElement('canvas');
            const ctx = canvas.getContext('2d');

            img.onload = () => {
                // Calculate new dimensions
                let { width, height } = img;
                const maxDim = ImageCompressor.MAX_DIMENSION;

                if (width > maxDim || height > maxDim) {
                    if (width > height) {
                        height = Math.round((height * maxDim) / width);
                        width = maxDim;
                    } else {
                        width = Math.round((width * maxDim) / height);
                        height = maxDim;
                    }
                }

                canvas.width = width;
                canvas.height = height;

                // Draw and compress
                ctx.drawImage(img, 0, 0, width, height);

                canvas.toBlob(
                    (blob) => {
                        if (!blob) {
                            console.error('Compression failed, using original');
                            resolve(file);
                            return;
                        }

                        // Create new File object with same name
                        const compressedFile = new File(
                            [blob],
                            file.name.replace(/\.[^.]+$/, '.jpg'),
                            { type: 'image/jpeg' }
                        );

                        console.log(`Compressed: ${(file.size/1024).toFixed(0)}KB → ${(compressedFile.size/1024).toFixed(0)}KB`);
                        resolve(compressedFile);
                    },
                    'image/jpeg',
                    ImageCompressor.QUALITY
                );
            };

            img.onerror = () => {
                console.error('Failed to load image for compression');
                resolve(file);  // Fall back to original
            };

            // Load the image
            img.src = URL.createObjectURL(file);
        });
    },

    /**
     * Replace input file with compressed version
     * @param {HTMLInputElement} input - The file input element
     * @param {File} compressedFile - The compressed file
     */
    replaceInputFile: function(input, compressedFile) {
        const dataTransfer = new DataTransfer();
        dataTransfer.items.add(compressedFile);
        input.files = dataTransfer.files;
    }
};

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
        excludeFields: ['csrfmiddlewaretoken', 'damage_photo_before', 'damage_photo_after', 'customer_submitted_photo', 'repair_date'],
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
            alert(`File size (${formatFileSize(file.size)}) exceeds maximum allowed size of 5MB. Please choose a smaller file.`);
            return false;
        }

        if (!allowedTypes.includes(file.type) && !file.name.toLowerCase().endsWith('.heic')) {
            alert('Invalid file type. Please upload a JPG, PNG, WebP, or HEIC image.');
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
            } catch (error) {
                console.error('Compression error:', error);
                // Fall back to original file
                createPhotoPreview(file, previewContainer, inputElement);
            }
        };
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
                        } catch (error) {
                            console.error('Compression error:', error);
                            // Fall back to original
                            const dataTransfer = new DataTransfer();
                            dataTransfer.items.add(file);
                            inputElement.files = dataTransfer.files;
                            createPhotoPreview(file, previewContainer, inputElement);
                        }
                    }
                } else {
                    alert('Please drop an image file (PNG, JPG, WebP, or HEIC)');
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

    const temperatureInput = document.getElementById('id_windshield_temperature');
    const viscositySuggestionContainer = document.getElementById('viscositySuggestion');
    let viscosityTimeout = null;

    /**
     * Fetch viscosity suggestion from API based on temperature
     */
    function fetchViscositySuggestion(temperature) {
        if (!temperature || temperature === '') {
            // Hide suggestion if no temperature
            if (viscositySuggestionContainer) {
                viscositySuggestionContainer.classList.add('hidden');
            }
            return;
        }

        // Debounce the API call
        clearTimeout(viscosityTimeout);
        viscosityTimeout = setTimeout(() => {
            const url = `/tech/api/viscosity-suggestion/?temperature=${temperature}`;

            fetch(url)
                .then(response => response.json())
                .then(data => {
                    if (data.success && data.recommendation) {
                        displayViscositySuggestion(data);
                    } else {
                        // No recommendation available
                        hideViscositySuggestion();
                    }
                })
                .catch(error => {
                    console.error('Error fetching viscosity suggestion:', error);
                    hideViscositySuggestion();
                });
        }, 500); // Wait 500ms after user stops typing
    }

    /**
     * Display viscosity suggestion badge
     */
    function displayViscositySuggestion(data) {
        if (!viscositySuggestionContainer) return;

        const badgeColor = data.badge_color || 'gray';
        const icon = getIconForViscosity(data.recommendation);

        viscositySuggestionContainer.innerHTML = `
            <div class="viscosity-suggestion-badge badge-${badgeColor}">
                <i class="${icon}"></i>
                <span>${data.suggestion_text}</span>
            </div>
        `;

        viscositySuggestionContainer.classList.remove('hidden');
    }

    /**
     * Hide viscosity suggestion
     */
    function hideViscositySuggestion() {
        if (viscositySuggestionContainer) {
            viscositySuggestionContainer.classList.add('hidden');
        }
    }

    /**
     * Get appropriate icon for viscosity level
     */
    function getIconForViscosity(viscosity) {
        if (!viscosity) return 'fas fa-info-circle';

        const viscosityLower = viscosity.toLowerCase();
        if (viscosityLower.includes('low')) {
            return 'fas fa-tint';
        } else if (viscosityLower.includes('medium')) {
            return 'fas fa-tint';
        } else if (viscosityLower.includes('high')) {
            return 'fas fa-tint';
        }
        return 'fas fa-lightbulb';
    }

    // Attach temperature change listener
    if (temperatureInput && viscositySuggestionContainer) {
        // Check on page load if there's already a value
        const initialTemp = temperatureInput.value;
        if (initialTemp) {
            fetchViscositySuggestion(initialTemp);
        }

        // Listen for temperature changes
        temperatureInput.addEventListener('input', function(e) {
            fetchViscositySuggestion(e.target.value);
        });
    }

    // ================ CONSOLE INFO ================
    console.log('✅ Repair Form Enhanced:');
    console.log('   - Autosave enabled');
    console.log('   - Photo previews active');
    console.log('   - Drag & drop support enabled');
    console.log('   - Duplicate repair check ready');
    console.log('   - Mobile camera capture optimized');
    console.log('   - Smart viscosity suggestions enabled');
});
