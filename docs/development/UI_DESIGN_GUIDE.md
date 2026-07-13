# RS Systems UI/UX Design Guide

## Overview

This guide documents the design system, UI components, and patterns used across RS Systems. Following these guidelines ensures a consistent, professional user experience throughout the application.

**Last Updated**: July 2026
**Base Framework**: Tailwind CSS (compiled — see build section below)
**Icon Library**: Font Awesome 6.4.0
**Typography**: Inter font family

---

## CSS Build & Component System (July 2026)

Tailwind is **compiled**, not CDN-loaded. Run `./scripts/build_css.sh` after any
template or `static/js` class change and commit the output `static/css/app.css`.
Theme lives in `tailwind.config.js`; component classes and tokens in
`static/css/src/input.css`. Never add `cdn.tailwindcss.com` or inline
`tailwind.config` blocks to templates.

### Semantic Button Hierarchy

Use these classes (defined in `input.css` `@layer components`) instead of ad-hoc
color utilities. **The old 7-color button chaos is deprecated.**

| Class | Role | Rule |
|---|---|---|
| `.btn-primary` | The main action | **Max ONE per view** (brand blue) |
| `.btn-secondary` | Supporting actions | Outlined; at most 2 visible |
| `.btn-danger` | Destructive actions only | Delete/deny/void — never for emphasis |
| `.btn-ghost` | Tertiary/overflow/inline | Kebab menus, cancel links |

Sizes: add `.btn-sm` or `.btn-lg`.

### Cards, Badges, Modals

- `.card` / `.card-header` / `.card-body` — standard container.
- `{% load ui %}` then `{% status_badge repair.queue_status %}` or
  `{% status_badge invoice.status kind='invoice' %}` — the single source of
  truth for status colors (defined in `core/templatetags/ui.py`).
- `{% service_type_chip 'REPAIR' %}` — repair/replacement type chip.
- Modals/dropdowns/confirms use `static/js/ui.js` data attributes:
  `data-modal-open="id"`, `data-modal-close`, `data-dropdown-toggle="id"` +
  `data-dropdown-menu`, `<form data-confirm="...">`. Bootstrap `data-bs-*`
  markup is dead — never add it.

### Reusable Partials (`templates/components/`)

- `page_header.html` — title/subtitle/back link (`title`, `subtitle`, `back_url`, `back_label`)
- `empty_state.html` — icon/title/message/CTAs (`icon`, `title`, `message`, `cta_url`, `cta_label`, `cta2_*`)
- `stat_card.html` — dashboard stat (`label`, `value`, `icon`, `tone`, `href`)
- `pagination.html` — Django `page_obj` pager, preserves querystring via `{% querystring %}`

Shared shells: `base_app.html` (tech+owner), `customer_portal/base_customer.html`,
`saas/base_public.html`, `base_auth.html` — all include `includes/head_assets.html`.

---

## Table of Contents

1. [Design System](#design-system)
2. [Layout Patterns](#layout-patterns)
3. [UI Components](#ui-components)
4. [Form Patterns](#form-patterns)
5. [Interactive Elements](#interactive-elements)
6. [Code Examples](#code-examples)
7. [Best Practices](#best-practices)

---

## Design System

### Color Palette

#### Primary Colors
```css
--primary-color: #2563eb;      /* Blue-600 - Main brand color */
--primary-dark: #1d4ed8;       /* Blue-700 - Hover/active states */
--primary-light: #eff6ff;      /* Blue-50 - Backgrounds */
```

#### Semantic Colors
```css
--success-color: #10b981;      /* Green-500 - Success states */
--warning-color: #f59e0b;      /* Amber-500 - Warnings/pending */
--danger-color: #ef4444;       /* Red-500 - Errors/security */
--info-color: #3b82f6;         /* Blue-500 - Information */
```

#### Neutral Colors
```css
--text-color: #334155;         /* Slate-700 - Primary text */
--text-secondary: #6b7280;     /* Gray-500 - Secondary text */
--text-muted: #9ca3af;         /* Gray-400 - Muted text */
--border-color: #e5e7eb;       /* Gray-200 - Borders */
--background-color: #f8f9fa;   /* Gray-50 - Page background */
--surface-color: #ffffff;      /* White - Card/surface background */
```

#### Color-Coded Sections
Use consistent color coding for different functional areas:

- **Blue** (`bg-blue-100`, `text-blue-600`): Personal information, user-related
- **Green** (`bg-green-100`, `text-green-600`): Scheduling, operations
- **Yellow** (`bg-yellow-100`, `text-yellow-600`): Approvals, pending actions
- **Red** (`bg-red-100`, `text-red-600`): Security, critical actions
- **Purple** (`bg-purple-100`, `text-purple-600`): Rewards, referrals

### Typography

#### Font Family
```html
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap" rel="stylesheet">
```

#### Font Sizes
```css
/* Headings */
h1: text-3xl (30px)      /* Page titles */
h2: text-2xl (24px)      /* Section titles */
h3: text-lg (18px)       /* Card titles */
h4: text-base (16px)     /* Subsection titles */

/* Body Text */
Base: text-sm (14px)     /* Forms, labels */
Small: text-xs (12px)    /* Help text, captions */
```

#### Font Weights
```css
font-light: 300          /* Rarely used */
font-normal: 400         /* Body text */
font-medium: 500         /* Labels, nav items */
font-semibold: 600       /* Headings, emphasis */
font-bold: 700           /* Page titles */
```

### Spacing

Use Tailwind's spacing scale for consistency:

```css
/* Common Spacing Values */
gap-2: 0.5rem (8px)      /* Tight spacing */
gap-3: 0.75rem (12px)    /* Default icon-to-text */
gap-4: 1rem (16px)       /* Form fields */
gap-6: 1.5rem (24px)     /* Section spacing */

/* Padding */
p-4: 1rem (16px)         /* Tight cards */
p-6: 1.5rem (24px)       /* Standard cards */
p-8: 2rem (32px)         /* Large sections */

/* Margins */
mb-4: 1rem (16px)        /* Form groups */
mb-6: 1.5rem (24px)      /* Card spacing */
mb-8: 2rem (32px)        /* Section spacing */
```

### Shadows and Borders

```css
/* Shadows */
shadow-sm: 0 1px 2px 0 rgb(0 0 0 / 0.05)           /* Subtle cards */
shadow: 0 1px 3px 0 rgb(0 0 0 / 0.1)               /* Standard cards */
shadow-lg: 0 10px 15px -3px rgb(0 0 0 / 0.1)       /* Elevated cards */

/* Border Radius */
rounded-lg: 0.5rem (8px)    /* Cards, buttons */
rounded-md: 0.375rem (6px)  /* Form inputs */
rounded-full: 9999px        /* Pills, badges */

/* Borders */
border: 1px solid           /* Standard borders */
border-2: 2px solid         /* Emphasized borders */
```

---

## Layout Patterns

### Page Structure

Every page should follow this hierarchy:

```html
<div class="min-h-screen bg-gray-50">
    <div class="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        <!-- Page Header -->
        <div class="mb-6">
            <div class="flex items-center justify-between">
                <div>
                    <h1 class="text-3xl font-bold text-gray-900">Page Title</h1>
                    <p class="text-gray-600 mt-1">Page description</p>
                </div>
                <a href="#" class="inline-flex items-center px-4 py-2 border border-gray-300 text-gray-700 text-sm font-medium rounded-lg hover:bg-gray-50 transition-colors">
                    <i class="fas fa-arrow-left mr-2"></i> Back
                </a>
            </div>
        </div>

        <!-- Page Content (Cards, Forms, etc.) -->

    </div>
</div>
```

### Container Widths

```css
max-w-5xl: 64rem (1024px)   /* Forms, settings pages */
max-w-7xl: 80rem (1280px)   /* Dashboards, data tables */
max-w-3xl: 48rem (768px)    /* Content pages, articles */
```

### Grid Layouts

```html
<!-- Two Column -->
<div class="grid grid-cols-1 md:grid-cols-2 gap-4">
    <div>Column 1</div>
    <div>Column 2</div>
</div>

<!-- Three Column Stats -->
<div class="grid grid-cols-1 md:grid-cols-3 gap-6">
    <div>Stat Card 1</div>
    <div>Stat Card 2</div>
    <div>Stat Card 3</div>
</div>

<!-- Responsive Four Column -->
<div class="grid grid-cols-2 md:grid-cols-4 gap-3">
    <div>Item 1</div>
    <div>Item 2</div>
    <div>Item 3</div>
    <div>Item 4</div>
</div>
```

---

## UI Components

### Card Component

**Purpose**: Container for related content with visual separation

```html
<div class="bg-white border border-gray-200 rounded-lg p-6">
    <!-- Card Header (Optional) -->
    <div class="flex items-center justify-between mb-6">
        <div class="flex items-center gap-3">
            <div class="bg-blue-100 text-blue-600 p-2 rounded-lg">
                <i class="fas fa-icon text-xl"></i>
            </div>
            <div>
                <h3 class="text-lg font-semibold text-gray-900">Card Title</h3>
                <p class="text-sm text-gray-600">Card description</p>
            </div>
        </div>
    </div>

    <!-- Card Content -->
    <div class="space-y-4">
        <!-- Your content here -->
    </div>
</div>
```

**Variations**:
- Standard Card: `bg-white border border-gray-200`
- Highlighted Card: `bg-blue-50 border border-blue-200`
- Warning Card: `bg-yellow-50 border border-yellow-200`
- Success Card: `bg-green-50 border border-green-200`

### Icon Badge Component

**Purpose**: Visual anchor for card headers and sections

```html
<div class="bg-blue-100 text-blue-600 p-2 rounded-lg">
    <i class="fas fa-user text-xl"></i>
</div>
```

**Color Variations**:
```html
<!-- Blue (Personal/User) -->
<div class="bg-blue-100 text-blue-600 p-2 rounded-lg">
    <i class="fas fa-user text-xl"></i>
</div>

<!-- Green (Scheduling/Operations) -->
<div class="bg-green-100 text-green-600 p-2 rounded-lg">
    <i class="fas fa-calendar-alt text-xl"></i>
</div>

<!-- Yellow (Approvals/Pending) -->
<div class="bg-yellow-100 text-yellow-600 p-2 rounded-lg">
    <i class="fas fa-clipboard-check text-xl"></i>
</div>

<!-- Red (Security/Critical) -->
<div class="bg-red-100 text-red-600 p-2 rounded-lg">
    <i class="fas fa-shield-alt text-xl"></i>
</div>
```

### Tooltip Component

**Purpose**: Display help text on hover without cluttering the interface

```html
<!-- In <style> block -->
<style>
.tooltip-trigger {
    position: relative;
    display: inline-flex;
    align-items: center;
    cursor: help;
    color: #6b7280;
    transition: color 0.2s;
}

.tooltip-trigger:hover {
    color: #2563eb;
}

.tooltip-content {
    position: absolute;
    bottom: 100%;
    left: 50%;
    transform: translateX(-50%) translateY(-8px);
    background-color: #1f2937;
    color: white;
    padding: 0.5rem 0.75rem;
    border-radius: 0.375rem;
    font-size: 0.875rem;
    line-height: 1.4;
    white-space: normal;
    width: max-content;
    max-width: 280px;
    opacity: 0;
    visibility: hidden;
    transition: opacity 0.2s, visibility 0.2s;
    z-index: 50;
    pointer-events: none;
}

.tooltip-content::after {
    content: '';
    position: absolute;
    top: 100%;
    left: 50%;
    transform: translateX(-50%);
    border: 6px solid transparent;
    border-top-color: #1f2937;
}

.tooltip-trigger:hover .tooltip-content {
    opacity: 1;
    visibility: visible;
}
</style>

<!-- Usage -->
<span class="tooltip-trigger">
    <i class="fas fa-circle-question text-sm"></i>
    <span class="tooltip-content">
        Your helpful tooltip text here
    </span>
</span>
```

### Badge Component

**Purpose**: Status indicators and labels

```html
<!-- Info Badge -->
<span class="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-blue-100 text-blue-800">
    Optional
</span>

<!-- Warning Badge -->
<span class="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-yellow-100 text-yellow-800">
    Pending
</span>

<!-- Success Badge -->
<span class="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-green-100 text-green-800">
    Active
</span>

<!-- Danger Badge -->
<span class="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-red-100 text-red-800">
    Required
</span>
```

### Info Callout Component

**Purpose**: Important information boxes

```html
<div class="bg-blue-50 border border-blue-200 rounded-lg p-4">
    <div class="flex gap-3">
        <i class="fas fa-info-circle text-blue-600 mt-0.5"></i>
        <div class="text-sm text-blue-900">
            <p class="font-medium">Important Information Title</p>
            <p class="mt-1 text-blue-800">Additional details and context.</p>
        </div>
    </div>
</div>
```

**Variations**:
```html
<!-- Warning Callout -->
<div class="bg-yellow-50 border border-yellow-200 rounded-lg p-4">
    <div class="flex gap-3">
        <i class="fas fa-exclamation-triangle text-yellow-600 mt-0.5"></i>
        <div class="text-sm text-yellow-900">...</div>
    </div>
</div>

<!-- Success Callout -->
<div class="bg-green-50 border border-green-200 rounded-lg p-4">
    <div class="flex gap-3">
        <i class="fas fa-check-circle text-green-600 mt-0.5"></i>
        <div class="text-sm text-green-900">...</div>
    </div>
</div>

<!-- Error Callout -->
<div class="bg-red-50 border border-red-200 rounded-lg p-4">
    <div class="flex gap-3">
        <i class="fas fa-times-circle text-red-600 mt-0.5"></i>
        <div class="text-sm text-red-900">...</div>
    </div>
</div>
```

---

## Form Patterns

### Form Layout

```html
<form method="post">
    {% csrf_token %}

    <!-- Form Section in Card -->
    <div class="bg-white border border-gray-200 rounded-lg p-6 mb-6">
        <!-- Section Header -->
        <div class="flex items-center gap-3 mb-6">
            <div class="bg-blue-100 text-blue-600 p-2 rounded-lg">
                <i class="fas fa-user text-xl"></i>
            </div>
            <div>
                <h3 class="text-lg font-semibold text-gray-900">Section Title</h3>
                <p class="text-sm text-gray-600">Section description</p>
            </div>
        </div>

        <!-- Form Fields -->
        <div class="space-y-4">
            <!-- Form groups here -->
        </div>
    </div>
</form>
```

### Form Input Component

```html
<div class="form-group mb-4">
    <label for="field_name" class="flex items-center gap-2 text-sm font-medium text-gray-700 mb-2">
        <i class="fas fa-icon text-gray-400"></i>
        Field Label
        <!-- Optional Tooltip -->
        <span class="tooltip-trigger">
            <i class="fas fa-circle-question text-sm"></i>
            <span class="tooltip-content">Help text here</span>
        </span>
    </label>
    <input
        type="text"
        class="w-full px-3.5 py-2.5 border border-gray-300 rounded-lg text-sm focus:outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100"
        id="field_name"
        name="field_name"
        placeholder="Enter value">
</div>
```

**Standard Form Input Classes**:
```css
.form-input {
    width: 100%;
    padding: 0.625rem 0.875rem;
    border: 1px solid #e5e7eb;
    border-radius: 0.375rem;
    font-size: 0.875rem;
    transition: all 0.2s;
    background-color: white;
}

.form-input:focus {
    outline: none;
    border-color: #2563eb;
    box-shadow: 0 0 0 3px rgba(37, 99, 235, 0.1);
}
```

### Radio Button Group

```html
<div class="radio-group space-y-3">
    <label class="radio-option flex items-start gap-3 p-4 border border-gray-200 rounded-lg cursor-pointer hover:border-blue-500 hover:bg-blue-50 transition-all">
        <input type="radio" name="option_name" value="value1" class="mt-1">
        <div class="flex-1">
            <div class="font-medium text-gray-900">Option Title</div>
            <div class="text-sm text-gray-600 mt-1">Option description</div>
        </div>
    </label>

    <label class="radio-option flex items-start gap-3 p-4 border border-gray-200 rounded-lg cursor-pointer hover:border-blue-500 hover:bg-blue-50 transition-all">
        <input type="radio" name="option_name" value="value2" class="mt-1">
        <div class="flex-1">
            <div class="font-medium text-gray-900">Option Title</div>
            <div class="text-sm text-gray-600 mt-1">Option description</div>
        </div>
    </label>
</div>
```

**Radio Group Styles**:
```css
.radio-option, .checkbox-option {
    display: flex;
    align-items: flex-start;
    gap: 0.75rem;
    padding: 1rem;
    border: 1px solid #e5e7eb;
    border-radius: 0.375rem;
    cursor: pointer;
    transition: all 0.2s;
}

.radio-option:hover, .checkbox-option:hover {
    border-color: #2563eb;
    background-color: #eff6ff;
}
```

### Checkbox Component

```html
<!-- Simple Checkbox -->
<div class="flex items-start gap-3 p-4 bg-gray-50 rounded-lg">
    <input type="checkbox" class="mt-1 h-4 w-4 text-blue-600 focus:ring-blue-500 border-gray-300 rounded" id="checkbox_name" name="checkbox_name">
    <div class="flex-1">
        <label for="checkbox_name" class="text-sm font-medium text-gray-900 cursor-pointer">
            Checkbox Label
        </label>
        <p class="text-xs text-gray-600 mt-1">Additional context or description</p>
    </div>
</div>

<!-- Checkbox Group (Multiple Days, etc.) -->
<div class="grid grid-cols-2 md:grid-cols-4 gap-3">
    <label class="flex items-center gap-2 p-3 bg-white border border-gray-200 rounded-lg cursor-pointer hover:bg-blue-50 hover:border-blue-300 transition-colors">
        <input type="checkbox" name="days[]" value="monday" class="h-4 w-4 text-blue-600">
        <span class="text-sm text-gray-700">Monday</span>
    </label>
    <!-- Repeat for other options -->
</div>
```

### Select Dropdown

```html
<div class="form-group mb-4">
    <label for="select_name" class="flex items-center gap-2 text-sm font-medium text-gray-700 mb-2">
        <i class="fas fa-icon text-gray-400"></i>
        Select Label
    </label>
    <select class="w-full px-3.5 py-2.5 border border-gray-300 rounded-lg text-sm focus:outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100" id="select_name" name="select_name">
        <option value="">Select an option...</option>
        <option value="option1">Option 1</option>
        <option value="option2">Option 2</option>
    </select>
</div>
```

---

## Interactive Elements

### Tab Navigation

```html
<!-- Tab Buttons -->
<div class="bg-white rounded-lg shadow-sm border border-gray-200 mb-6">
    <div class="border-b border-gray-200">
        <div class="flex">
            <button type="button" class="tab-button active" data-tab="tab1">
                <i class="fas fa-icon"></i>
                <span>Tab 1</span>
            </button>
            <button type="button" class="tab-button" data-tab="tab2">
                <i class="fas fa-icon"></i>
                <span>Tab 2</span>
            </button>
        </div>
    </div>

    <!-- Tab Content -->
    <div class="tab-content p-6" id="tab1-tab" style="display: block;">
        Tab 1 content
    </div>

    <div class="tab-content p-6" id="tab2-tab" style="display: none;">
        Tab 2 content
    </div>
</div>
```

**Tab Button Styles**:
```css
.tab-button {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    padding: 0.75rem 1.5rem;
    border-bottom: 2px solid transparent;
    color: #6b7280;
    font-weight: 500;
    transition: all 0.2s;
    cursor: pointer;
    background: none;
    border-top: none;
    border-left: none;
    border-right: none;
}

.tab-button:hover {
    color: #2563eb;
    background-color: #eff6ff;
}

.tab-button.active {
    color: #2563eb;
    border-bottom-color: #2563eb;
    background-color: #eff6ff;
}
```

**Tab JavaScript**:
```javascript
document.addEventListener('DOMContentLoaded', function() {
    const tabButtons = document.querySelectorAll('.tab-button');
    const tabContents = document.querySelectorAll('.tab-content');

    tabButtons.forEach(button => {
        button.addEventListener('click', function() {
            const targetTab = this.getAttribute('data-tab');

            // Remove active class from all buttons
            tabButtons.forEach(btn => btn.classList.remove('active'));

            // Add active class to clicked button
            this.classList.add('active');

            // Hide all tab contents
            tabContents.forEach(content => {
                content.style.display = 'none';
            });

            // Show target tab content
            const targetContent = document.getElementById(targetTab + '-tab');
            if (targetContent) {
                targetContent.style.display = 'block';
            }
        });
    });
});
```

### Conditional Section (Show/Hide)

```html
<!-- Conditional Section -->
<div id="conditional-section" class="conditional-section hidden mt-4">
    <div class="bg-blue-50 border border-blue-200 rounded-lg p-4">
        <!-- Content that appears conditionally -->
    </div>
</div>
```

**Conditional Section Styles**:
```css
.conditional-section {
    transition: all 0.3s ease;
    overflow: hidden;
}

.conditional-section.hidden {
    max-height: 0;
    opacity: 0;
    margin: 0;
    padding: 0;
}

.conditional-section.visible {
    max-height: 1000px;
    opacity: 1;
}
```

**Conditional Section JavaScript**:
```javascript
// Toggle visibility based on checkbox/radio
const trigger = document.getElementById('trigger_id');
const section = document.getElementById('conditional-section');

trigger.addEventListener('change', function() {
    if (this.checked) {
        section.classList.remove('hidden');
        section.classList.add('visible');
    } else {
        section.classList.add('hidden');
        section.classList.remove('visible');
    }
});
```

### Button Components

```html
<!-- Primary Button -->
<button type="submit" class="inline-flex items-center px-6 py-2.5 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-blue-500 transition-colors shadow-sm">
    <i class="fas fa-check mr-2"></i>
    Primary Action
</button>

<!-- Secondary Button -->
<button type="button" class="inline-flex items-center px-5 py-2.5 border border-gray-300 text-gray-700 text-sm font-medium rounded-lg hover:bg-gray-50 transition-colors">
    Secondary Action
</button>

<!-- Danger Button -->
<button type="button" class="inline-flex items-center px-5 py-2.5 bg-red-600 text-white text-sm font-medium rounded-lg hover:bg-red-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-red-500 transition-colors">
    <i class="fas fa-trash mr-2"></i>
    Delete
</button>

<!-- Link Button -->
<a href="#" class="inline-flex items-center px-4 py-2 border border-gray-300 text-gray-700 text-sm font-medium rounded-lg hover:bg-gray-50 transition-colors">
    <i class="fas fa-arrow-left mr-2"></i>
    Back
</a>
```

---

## Code Examples

### Complete Settings Page Pattern

Reference: `templates/customer_portal/account_settings.html`

```html
{% extends "base.html" %}
{% load static %}

{% block title %}Settings - RS Systems{% endblock %}

{% block extra_css %}
<script src="https://cdn.tailwindcss.com"></script>
<style>
/* Tooltip, tab, and form styles here */
</style>
{% endblock %}

{% block content %}
<div class="min-h-screen bg-gray-50">
    <div class="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        <!-- Page Header -->
        <div class="mb-6">
            <div class="flex items-center justify-between">
                <div>
                    <h1 class="text-3xl font-bold text-gray-900">Page Title</h1>
                    <p class="text-gray-600 mt-1">Page description</p>
                </div>
                <a href="{% url 'dashboard' %}" class="inline-flex items-center px-4 py-2 border border-gray-300 text-gray-700 text-sm font-medium rounded-lg hover:bg-gray-50 transition-colors">
                    <i class="fas fa-arrow-left mr-2"></i> Back
                </a>
            </div>
        </div>

        <!-- Card with Tabs -->
        <div class="bg-white rounded-lg shadow-sm border border-gray-200 mb-6">
            <!-- Tab Navigation -->
            <div class="border-b border-gray-200">
                <div class="flex">
                    <button type="button" class="tab-button active" data-tab="tab1">
                        <i class="fas fa-icon"></i>
                        <span>Tab 1</span>
                    </button>
                </div>
            </div>

            <form method="post">
                {% csrf_token %}

                <!-- Tab Content -->
                <div class="tab-content p-6" id="tab1-tab" style="display: block;">
                    <!-- Section Card -->
                    <div class="bg-white border border-gray-200 rounded-lg p-6 mb-6">
                        <!-- Card Header -->
                        <div class="flex items-center gap-3 mb-6">
                            <div class="bg-blue-100 text-blue-600 p-2 rounded-lg">
                                <i class="fas fa-icon text-xl"></i>
                            </div>
                            <div>
                                <h3 class="text-lg font-semibold text-gray-900">Section Title</h3>
                                <p class="text-sm text-gray-600">Section description</p>
                            </div>
                        </div>

                        <!-- Form Fields -->
                        <div class="space-y-4">
                            <!-- Form groups here -->
                        </div>
                    </div>
                </div>

                <!-- Save Button -->
                <div class="p-6 bg-gray-50 border-t border-gray-200 flex items-center justify-between">
                    <p class="text-sm text-gray-600">
                        <i class="fas fa-save text-gray-400 mr-1"></i>
                        Changes will be saved
                    </p>
                    <div class="flex gap-3">
                        <a href="#" class="inline-flex items-center px-5 py-2.5 border border-gray-300 text-gray-700 text-sm font-medium rounded-lg hover:bg-gray-50 transition-colors">
                            Cancel
                        </a>
                        <button type="submit" class="inline-flex items-center px-6 py-2.5 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-blue-500 transition-colors shadow-sm">
                            <i class="fas fa-check mr-2"></i>
                            Save Changes
                        </button>
                    </div>
                </div>
            </form>
        </div>
    </div>
</div>

<script>
// Tab switching, conditional sections, etc.
</script>
{% endblock %}
```

---

## Best Practices

### 1. Consistency

- **Always use the same color for the same purpose** (e.g., blue for primary actions, red for destructive actions)
- **Use consistent spacing** throughout the application (stick to Tailwind's spacing scale)
- **Icons should be consistent** (e.g., always use `fa-user` for user-related items)

### 2. Accessibility

- **Always include labels** for form inputs
- **Use semantic HTML** (buttons for actions, links for navigation)
- **Ensure sufficient color contrast** (minimum 4.5:1 for normal text)
- **Make interactive elements keyboard-accessible**

### 3. Responsive Design

- **Mobile-first approach**: Design for mobile, then enhance for desktop
- **Use responsive classes**: `grid-cols-1 md:grid-cols-2`
- **Test on multiple screen sizes**: 320px (mobile), 768px (tablet), 1024px (desktop)
- **Stack elements on mobile**: Use `flex-col` on small screens

### 4. Performance

- **Minimize custom CSS**: Use Tailwind utility classes when possible
- **Optimize images**: Use appropriate formats and sizes
- **Lazy load non-critical content**: Defer loading of below-the-fold content
- **Use CDN for libraries**: Font Awesome, Tailwind CSS

### 5. User Experience

- **Provide visual feedback**: Hover states, loading states, success/error messages
- **Use tooltips for complex features**: Don't clutter UI with excessive help text
- **Group related fields**: Use cards and sections to organize content
- **Clear call-to-action**: Primary buttons should stand out

### 6. Code Organization

```
templates/
├── base.html                 # Base template with navbar/footer
├── customer_portal/
│   ├── dashboard.html        # Dashboard page
│   ├── account_settings.html # Settings with tabs
│   └── ...
└── technician_portal/
    └── ...

static/
├── css/
│   ├── style.css            # Global styles
│   └── customer.css         # Portal-specific styles
└── images/
    └── ...
```

### 7. Common Icon Usage

**Consistent icon mapping across the application:**

```
User/Personal: fa-user
Settings: fa-cog, fa-sliders
Security: fa-shield-alt, fa-lock
Calendar/Schedule: fa-calendar-alt
Approval: fa-clipboard-check
Information: fa-info-circle
Warning: fa-exclamation-triangle
Success: fa-check-circle
Error: fa-times-circle
Help: fa-circle-question
Building/Company: fa-building
Email: fa-envelope
Phone: fa-phone
Save: fa-save, fa-check
Back/Return: fa-arrow-left
Edit: fa-edit
Delete: fa-trash
```

---

## Migration Guide

### Updating Existing Pages

To bring an existing page up to the new design standard:

1. **Add Tailwind CDN** if not already present:
```html
{% block extra_css %}
<script src="https://cdn.tailwindcss.com"></script>
{% endblock %}
```

2. **Replace Bootstrap classes** with Tailwind equivalents:
```
Bootstrap → Tailwind
.container → max-w-7xl mx-auto px-4
.row → grid or flex
.col-md-6 → grid-cols-1 md:grid-cols-2
.btn-primary → bg-blue-600 text-white px-4 py-2 rounded-lg
.card → bg-white border border-gray-200 rounded-lg
.text-muted → text-gray-600
```

3. **Add icon badges** to section headers:
```html
<div class="flex items-center gap-3">
    <div class="bg-blue-100 text-blue-600 p-2 rounded-lg">
        <i class="fas fa-icon text-xl"></i>
    </div>
    <div>
        <h3 class="text-lg font-semibold text-gray-900">Title</h3>
        <p class="text-sm text-gray-600">Description</p>
    </div>
</div>
```

4. **Convert help text to tooltips**:
```html
<!-- Before -->
<label>Field Label</label>
<small class="text-muted">Help text here</small>

<!-- After -->
<label class="flex items-center gap-2">
    Field Label
    <span class="tooltip-trigger">
        <i class="fas fa-circle-question text-sm"></i>
        <span class="tooltip-content">Help text here</span>
    </span>
</label>
```

5. **Add smooth transitions** to interactive elements:
- Add `transition-colors` to buttons and links
- Use `conditional-section` class for show/hide content
- Add hover states with `hover:` classes

---

## Support and Questions

For questions or clarifications about the design system:

1. **Reference**: Check `templates/customer_portal/account_settings.html` for a complete example
2. **Documentation**: This guide and CLAUDE.md
3. **Consistency**: When in doubt, follow patterns from existing pages
4. **Updates**: Document new patterns in this guide when creating them

---

**Document Version**: 1.0
**Last Updated**: October 25, 2025
**Reference Implementation**: Customer Portal Account Settings
