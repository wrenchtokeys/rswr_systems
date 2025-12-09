/**
 * Color Picker Enhancement for Email Branding Config Admin
 *
 * Adds HTML5 color input next to hex color fields with two-way sync.
 * Provides live color preview and better UX for choosing brand colors.
 */

(function() {
    'use strict';

    // Wait for DOM to be ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }

    function init() {
        // Only run on EmailBrandingConfig admin pages
        const emailBrandingForm = document.querySelector('form[action*="emailbrandingconfig"]');
        if (!emailBrandingForm) {
            return;
        }

        // Color fields to enhance
        const colorFields = [
            'primary_color',
            'secondary_color',
            'success_color',
            'danger_color',
            'text_color',
            'background_color'
        ];

        colorFields.forEach(fieldName => {
            const textInput = document.getElementById('id_' + fieldName);
            if (textInput) {
                enhanceColorField(textInput, fieldName);
            }
        });
    }

    function enhanceColorField(textInput, fieldName) {
        // Create color picker input
        const colorPicker = document.createElement('input');
        colorPicker.type = 'color';
        colorPicker.value = textInput.value || '#000000';
        colorPicker.className = 'color-picker-widget';
        colorPicker.title = 'Click to choose color';

        // Create wrapper for better layout
        const wrapper = document.createElement('div');
        wrapper.className = 'color-field-wrapper';
        wrapper.style.display = 'flex';
        wrapper.style.alignItems = 'center';
        wrapper.style.gap = '10px';

        // Create live preview swatch
        const previewSwatch = document.createElement('div');
        previewSwatch.className = 'color-preview-swatch';
        previewSwatch.style.width = '40px';
        previewSwatch.style.height = '40px';
        previewSwatch.style.border = '2px solid #ccc';
        previewSwatch.style.borderRadius = '4px';
        previewSwatch.style.backgroundColor = textInput.value || '#000000';
        previewSwatch.style.cursor = 'pointer';
        previewSwatch.style.transition = 'all 0.2s ease';
        previewSwatch.title = 'Click to choose color';

        // Create helper text
        const helperText = document.createElement('span');
        helperText.className = 'color-helper-text';
        helperText.style.fontSize = '11px';
        helperText.style.color = '#666';
        helperText.textContent = 'or enter hex code';

        // Insert color picker and preview before text input
        textInput.parentNode.insertBefore(wrapper, textInput);
        wrapper.appendChild(previewSwatch);
        wrapper.appendChild(colorPicker);
        wrapper.appendChild(textInput);
        wrapper.appendChild(helperText);

        // Style the text input
        textInput.style.width = '100px';
        textInput.style.fontFamily = 'monospace';
        textInput.style.textTransform = 'uppercase';

        // Two-way sync: Color picker -> Text input
        colorPicker.addEventListener('input', function() {
            const newColor = this.value.toUpperCase();
            textInput.value = newColor;
            previewSwatch.style.backgroundColor = newColor;
            validateHexColor(textInput);
        });

        // Two-way sync: Text input -> Color picker
        textInput.addEventListener('input', function() {
            const value = this.value.trim();
            if (isValidHexColor(value)) {
                colorPicker.value = value;
                previewSwatch.style.backgroundColor = value;
                textInput.style.borderColor = '#ccc';
                textInput.style.backgroundColor = 'white';
            } else {
                textInput.style.borderColor = '#e53e3e';
                textInput.style.backgroundColor = '#fff5f5';
            }
        });

        // Make preview swatch clickable
        previewSwatch.addEventListener('click', function() {
            colorPicker.click();
        });

        // Hover effect on swatch
        previewSwatch.addEventListener('mouseenter', function() {
            this.style.borderColor = '#999';
            this.style.transform = 'scale(1.05)';
        });

        previewSwatch.addEventListener('mouseleave', function() {
            this.style.borderColor = '#ccc';
            this.style.transform = 'scale(1)';
        });

        // Auto-format hex codes (add # if missing)
        textInput.addEventListener('blur', function() {
            let value = this.value.trim();
            if (value && !value.startsWith('#')) {
                value = '#' + value;
            }
            if (value.length === 4) {
                // Convert short hex (#RGB) to full hex (#RRGGBB)
                value = '#' + value[1] + value[1] + value[2] + value[2] + value[3] + value[3];
            }
            this.value = value.toUpperCase();

            if (isValidHexColor(value)) {
                colorPicker.value = value;
                previewSwatch.style.backgroundColor = value;
                this.style.borderColor = '#ccc';
                this.style.backgroundColor = 'white';
            }
        });
    }

    function isValidHexColor(color) {
        return /^#[0-9A-Fa-f]{6}$/.test(color);
    }

    function validateHexColor(input) {
        const isValid = isValidHexColor(input.value);
        if (isValid) {
            input.style.borderColor = '#ccc';
            input.style.backgroundColor = 'white';
        } else {
            input.style.borderColor = '#e53e3e';
            input.style.backgroundColor = '#fff5f5';
        }
        return isValid;
    }

})();
