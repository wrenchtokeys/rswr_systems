# Frontend Guide

Consolidated guide covering CSS architecture, JavaScript/D3.js visualizations, and CSS linting.

---

## CSS Architecture

### Architecture Overview

The CSS follows a modular, component-based approach with CSS variables (Custom Properties) for consistency.

**Key principles**: Separation of concerns, consistency via design tokens, reusability, maintainability, performance.

### File Structure

| File | Purpose |
|------|---------|
| `base.css` | CSS variables, reset, base typography, utilities |
| `components.css` | Shared UI components (buttons, cards, forms, tables, alerts) |
| `customer.css` | Customer portal styles (dashboard visualizations, cards) |
| `technician.css` | Technician portal styles (repair management, priority indicators) |
| `style.css` | Legacy auth templates only (being phased out) |

### Design System

#### Colors
```css
:root {
    --primary-color: #0056b3;
    --primary-light: #3380c2;
    --primary-dark: #004494;
    --success-color: #28a745;
    --danger-color: #dc3545;
    --warning-color: #ffc107;
    --info-color: #17a2b8;
    --text-color: #333333;
    --text-muted: #6c757d;
    --border-color: #e3e8f0;
    --bg-color: #f5f7fa;
    --bg-light: #ffffff;
    --bg-dark: #343a40;
}
```

#### Typography
```css
:root {
    --font-family: 'Inter', sans-serif;
    --font-size-xs: 0.75rem;    /* 12px */
    --font-size-sm: 0.875rem;   /* 14px */
    --font-size-md: 1rem;       /* 16px */
    --font-size-lg: 1.125rem;   /* 18px */
    --font-size-xl: 1.25rem;    /* 20px */
    --font-size-2xl: 1.5rem;    /* 24px */
    --font-size-3xl: 1.875rem;  /* 30px */
    --font-size-4xl: 2.25rem;   /* 36px */
}
```

#### Spacing
```css
:root {
    --spacing-xs: 0.25rem;  /* 4px */
    --spacing-sm: 0.5rem;   /* 8px */
    --spacing-md: 1rem;     /* 16px */
    --spacing-lg: 1.5rem;   /* 24px */
    --spacing-xl: 3rem;     /* 48px */
    --box-shadow: 0 0.125rem 0.25rem rgba(0, 0, 0, 0.075);
    --box-shadow-lg: 0 0.5rem 1rem rgba(0, 0, 0, 0.15);
    --border-radius: 0.25rem;
    --transition: all 0.2s ease-in-out;
}
```

### Component Library

**Buttons**: Primary/secondary/success/danger/warning/info, small/medium/large, solid/outline/text-only. `.action-button` for primary CTAs.

**Cards**: Basic card, card with header/footer, stats cards, info cards.

**Forms**: Text inputs, textareas, selects, custom checkboxes/radios, validation states.

**Navigation**: Top nav bar, sidebar, dropdowns, breadcrumbs.

**Tables**: Basic, striped, hover effect, responsive horizontal scrolling.

**Alerts**: Success/info/warning/danger, with/without icons, dismissible, toast messages.

**Status indicators**: Badges, status pills, progress indicators.

### Layout System

12-column grid with flexbox utilities. Responsive breakpoints:
- `576px` (small), `768px` (medium), `992px` (large), `1200px` (extra large)

### Best Practices

- Use kebab-case for class names
- Use CSS variables, never hardcoded values
- Follow BEM methodology (`.button`, `.button__icon`, `.button--large`)
- Mobile-first media queries
- Minimize nesting, avoid `!important`
- Group properties: positioning, box model, typography, visual, misc

### Legacy Migration

`style.css` is being phased out. When updating auth pages: replace legacy classes with the new component system, then remove unused legacy CSS.

---

## JavaScript & D3.js Visualizations

### Overview

D3.js visualizations in the customer portal provide interactive repair data charts.

### Visualization Components

#### 1. Repair Status Distribution (Pie Chart)
**File**: `repair_status_chart.js`

Displays repair distribution across statuses. Uses `d3.pie()` layout, `d3.arc()` generator, and `d3.scaleOrdinal()` color scale.

**Data**: Array of `{status, count}` objects.

#### 2. Repairs by Unit (Bar Chart)
**File**: `unit_repair_chart.js`

Top 10 units by repair count, sorted descending. Uses `d3.scaleBand()` (x-axis) and `d3.scaleLinear()` (y-axis).

**Data**: Array of `{unit_number, repair_count}` objects. Fetches from `/customer/api/unit-repair-data/`.

#### 3. Repair Frequency Over Time (Line Chart)
**File**: `repair_frequency_chart.js`

Monthly repair trends. Uses `d3.timeParse('%Y-%m')`, `d3.scaleTime()`, and `d3.line()`.

**Data**: Array of `{date, count}` objects (YYYY-MM format). Fetches from `/customer/api/repair-cost-data/`.

### DOM Dependencies

```html
<div id="status-chart-container"></div>
<div id="unit-chart-container"></div>
<div id="frequency-chart-container"></div>
```

### Common Pattern

```javascript
document.addEventListener('DOMContentLoaded', function() {
    const svg = d3.select('#chart-container')
        .append('svg')
        .attr('viewBox', `0 0 ${width} ${height}`)
        .attr('preserveAspectRatio', 'xMidYMid meet');

    fetch('/api/endpoint/')
        .then(response => response.json())
        .then(data => { /* create scales, render elements */ })
        .catch(error => { /* show error message */ });
});
```

### Adding a New Visualization

1. Create new JS file
2. Include in `dashboard.html`
3. Add HTML container element
4. Create API endpoint in `views.py` if needed
5. Update CSS in `dashboard_visualizations.css`

### Best Practices

- Use `DOMContentLoaded` event
- Use `viewBox` for responsive SVGs
- Include loading indicators and error messages
- Add tooltips for hover details
- Handle empty data gracefully
- Debounce resize events

---

## CSS Linting

### Setup

```bash
npm install --save-dev stylelint stylelint-config-standard
```

### Configuration (`.stylelintrc.js`)

```javascript
module.exports = {
  extends: 'stylelint-config-standard',
  rules: {
    'indentation': 4,
    'color-hex-case': 'lower',
    'color-hex-length': 'long',
    'color-named': 'never',
    'string-quotes': 'single',
    'declaration-block-trailing-semicolon': 'always',
    'no-duplicate-selectors': true,
    'declaration-block-no-duplicate-properties': true,
    'selector-class-pattern': '^[a-z][a-z0-9-_]*$',
    'block-no-empty': true,
    'property-no-vendor-prefix': true,
    'value-no-vendor-prefix': true
  }
};
```

### Usage

```bash
npm run lint:css          # Check for issues
npm run lint:css:fix      # Auto-fix issues
```

Add to `package.json`:
```json
{
  "scripts": {
    "lint:css": "stylelint 'static/css/*.css'",
    "lint:css:fix": "stylelint 'static/css/*.css' --fix"
  }
}
```

### VS Code Integration

Install `stylelint.vscode-stylelint` extension and add to settings:
```json
{
  "editor.codeActionsOnSave": { "source.fixAll.stylelint": true },
  "stylelint.validate": ["css"]
}
```
