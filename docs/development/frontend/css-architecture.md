# RS Systems CSS Architecture Documentation

## Table of Contents
1. [Introduction](#introduction)
2. [Architecture Overview](#architecture-overview)
3. [File Structure](#file-structure)
4. [Design System](#design-system)
   - [Color System](#color-system)
   - [Typography](#typography)
   - [Spacing](#spacing)
   - [Shadows and Effects](#shadows-and-effects)
5. [Component Library](#component-library)
   - [Buttons](#buttons)
   - [Cards](#cards)
   - [Forms](#forms)
   - [Navigation](#navigation)
   - [Tables](#tables)
   - [Alerts and Messages](#alerts-and-messages)
   - [Status Indicators](#status-indicators)
6. [Layout System](#layout-system)
7. [Portal-Specific Elements](#portal-specific-elements)
8. [Responsive Design](#responsive-design)
9. [Accessibility Considerations](#accessibility-considerations)
10. [Best Practices](#best-practices)
11. [Legacy Code and Migration](#legacy-code-and-migration)
12. [Contributing Guidelines](#contributing-guidelines)

## Introduction

This documentation details the CSS architecture for the RS Systems application, which provides a consistent user experience across both the technician and customer portals. The architecture has been designed with maintainability, scalability, and performance in mind, while ensuring visual consistency throughout the application.

## Architecture Overview

The CSS architecture follows a modular, component-based approach that separates concerns and promotes reusability. The system is built on CSS variables (Custom Properties) to ensure consistency in colors, spacing, typography, and other design elements.

Key principles:
- **Separation of Concerns**: Base styles, components, and portal-specific styles are kept separate
- **Consistency**: Design tokens are defined as CSS variables for consistent application
- **Reusability**: Components are designed to be reusable across different contexts
- **Maintainability**: Clear organization makes it easier to update and extend the system
- **Performance**: Minimized duplication and optimized selectors improve loading times

## File Structure

The CSS is organized into the following files:

- **`base.css`**: Contains foundational elements:
  - CSS variables (design tokens)
  - Reset/normalization styles
  - Base typography
  - Root layout classes
  - Utility classes

- **`components.css`**: Defines reusable UI components shared across the application:
  - Buttons and form controls
  - Cards and containers
  - Navigation elements
  - Tables and data displays
  - Alerts and notifications
  - Modal dialogs

- **`customer.css`**: Contains styles specific to the customer portal:
  - Customer dashboard visualizations
  - Customer-specific cards and layouts
  - Customer-specific variations of components

- **`technician.css`**: Contains styles specific to the technician portal:
  - Technician-specific tools and interfaces
  - Repair management UI elements
  - Technician-specific variations of components

- **`style.css`**: Legacy CSS file used only by authentication templates (login, registration, etc.). This file is being phased out as templates are migrated to the new architecture.

## Design System

### Color System

Colors are defined as CSS variables in `base.css` to ensure consistency:

```css
:root {
    /* Brand Colors */
    --primary-color: #0056b3;      /* Primary blue */
    --primary-light: #3380c2;      /* Lighter blue for backgrounds */
    --primary-dark: #004494;       /* Darker blue for hover states */
    
    /* Semantic Colors */
    --success-color: #28a745;      /* Green for success states */
    --danger-color: #dc3545;       /* Red for errors and warnings */
    --warning-color: #ffc107;      /* Yellow for alerts */
    --info-color: #17a2b8;         /* Light blue for information */
    
    /* Neutral Colors */
    --text-color: #333333;         /* Primary text color */
    --text-muted: #6c757d;         /* Secondary text color */
    --border-color: #e3e8f0;       /* Border color */
    --bg-color: #f5f7fa;           /* Background color */
    --bg-light: #ffffff;           /* Light background */
    --bg-dark: #343a40;            /* Dark background */
}
```

Always use these color variables rather than hardcoded values to ensure consistency and make theme changes easier.

### Typography

Typography is standardized using the Inter font family with defined sizes and weights:

```css
:root {
    /* Font Family */
    --font-family: 'Inter', sans-serif;
    
    /* Font Sizes */
    --font-size-xs: 0.75rem;    /* 12px */
    --font-size-sm: 0.875rem;   /* 14px */
    --font-size-md: 1rem;       /* 16px - Base size */
    --font-size-lg: 1.125rem;   /* 18px */
    --font-size-xl: 1.25rem;    /* 20px */
    --font-size-2xl: 1.5rem;    /* 24px */
    --font-size-3xl: 1.875rem;  /* 30px */
    --font-size-4xl: 2.25rem;   /* 36px */
    
    /* Font Weights */
    --font-weight-light: 300;
    --font-weight-regular: 400;
    --font-weight-medium: 500;
    --font-weight-semibold: 600;
    --font-weight-bold: 700;
    
    /* Line Heights */
    --line-height-tight: 1.2;
    --line-height-normal: 1.5;
    --line-height-loose: 1.8;
}
```

### Spacing

A consistent spacing system ensures proper visual rhythm:

```css
:root {
    --spacing-xs: 0.25rem;  /* 4px */
    --spacing-sm: 0.5rem;   /* 8px */
    --spacing-md: 1rem;     /* 16px */
    --spacing-lg: 1.5rem;   /* 24px */
    --spacing-xl: 3rem;     /* 48px */
}
```

This spacing system is used for margins, padding, and layout gaps to maintain consistent spacing throughout the application.

### Shadows and Effects

Consistent shadows and effects enhance the visual hierarchy:

```css
:root {
    --box-shadow: 0 0.125rem 0.25rem rgba(0, 0, 0, 0.075);
    --box-shadow-lg: 0 0.5rem 1rem rgba(0, 0, 0, 0.15);
    --border-radius: 0.25rem;
    --transition: all 0.2s ease-in-out;
}
```

## Component Library

### Buttons

The system includes a comprehensive button system with variants:

- **Button Types**: Primary, secondary, success, danger, warning, info, light, dark
- **Button Sizes**: Small, medium (default), large
- **Button States**: Normal, hover, active, disabled
- **Button Variants**: Solid, outline, text-only
- **Special Buttons**: `.action-button` for primary call-to-action buttons

Example:
```html
<button class="btn btn-primary">Primary Button</button>
<button class="btn btn-sm btn-outline-secondary">Small Outline Button</button>
<a href="#" class="action-button">Primary Action</a>
```

### Cards

Cards are used extensively for content containers:

- **Basic Card**: Container with padding, border, and shadow
- **Card with Header/Footer**: Sections for titles and actions
- **Special Cards**: Stats cards, info cards

Example:
```html
<div class="card">
    <div class="card-header">
        <h5 class="card-title">Card Title</h5>
    </div>
    <div class="card-body">
        <p>Card content</p>
    </div>
    <div class="card-footer">
        <button class="btn btn-primary">Action</button>
    </div>
</div>
```

### Forms

Form elements are styled consistently:

- **Inputs**: Text inputs, textareas, select menus
- **Checkboxes and Radios**: Custom styled for better usability
- **Form Layout**: Form groups, labels, help text
- **Validation States**: Success, error states

### Navigation

Navigation components include:

- **Top Navigation Bar**: Main site navigation
- **Sidebar Navigation**: Section navigation
- **Dropdown Menus**: For nested options
- **Breadcrumbs**: For hierarchical navigation

### Tables

Tables are styled for better readability:

- **Basic Table**: Clean styling with proper spacing
- **Striped Tables**: Alternating row colors
- **Hover Effect**: Visual feedback on row hover
- **Responsive Tables**: Horizontal scrolling on small screens

### Alerts and Messages

Feedback is provided through consistent alert styles:

- **Alert Types**: Success, info, warning, danger
- **Alert Variations**: With/without icons, dismissible
- **Toast Messages**: For temporary notifications

### Status Indicators

Status is communicated through badges and indicators:

- **Badges**: Small indicators for status, counts
- **Status Pills**: For showing statuses like "Completed", "In Progress"
- **Progress Indicators**: For showing completion progress

## Layout System

The layout system is based on a responsive grid:

- **Container**: Centered content with max-width
- **Grid System**: Rows and columns (12-column grid)
- **Flexbox Utilities**: Alignment, distribution, ordering
- **Spacing Utilities**: Margin and padding helpers

## Portal-Specific Elements

### Customer Portal

- **Dashboard Visualizations**: Charts and stats displays
- **Repair Request Flow**: Custom UI for submitting repair requests
- **Approval Interface**: For reviewing and approving repairs

### Technician Portal

- **Repair Management Tools**: Interfaces for managing repair workflow
- **Customer Management**: Interfaces for managing customer data
- **Priority Indicators**: Visual cues for urgent repairs

## Responsive Design

The system is built with a mobile-first approach:

- **Base Styles**: Designed for mobile devices
- **Media Queries**: Enhance layout for larger screens
- **Breakpoints**:
  - `@media (min-width: 576px)`: Small devices
  - `@media (min-width: 768px)`: Medium devices
  - `@media (min-width: 992px)`: Large devices
  - `@media (min-width: 1200px)`: Extra large devices

## Accessibility Considerations

The CSS is designed with accessibility in mind:

- **Color Contrast**: All text meets WCAG 2.1 AA standards
- **Focus States**: Visible focus indicators for keyboard navigation
- **Text Sizing**: Respects user font size preferences
- **Screen Reader Support**: No CSS that could interfere with screen readers

## Best Practices

### Naming Conventions

- Use kebab-case for class names: `.button-primary` not `.buttonPrimary`
- Use descriptive, functional names: `.alert-warning` not `.yellow-box`
- Follow BEM methodology for component variants and states:
  - Block: `.button`
  - Element: `.button__icon`
  - Modifier: `.button--large`

### CSS Organization

- Group related properties
- Use consistent order of properties:
  1. Positioning
  2. Box model
  3. Typography
  4. Visual
  5. Miscellaneous

### Avoiding Common Pitfalls

- Minimize nesting to avoid specificity issues
- Avoid using `!important` except in utility classes
- Use CSS variables instead of duplicating values
- Write mobile-first media queries
- Avoid overly specific selectors

## Legacy Code and Migration

The `style.css` file contains legacy styles that are being phased out. When working on a page that still uses these styles:

1. Identify which components from the new system can replace legacy styles
2. Update HTML to use the new class names
3. Remove legacy CSS once no longer needed

## Contributing Guidelines

When adding or modifying CSS:

1. **Determine the Right Location**:
   - Is it a base style? → `base.css`
   - Is it a shared component? → `components.css`
   - Is it specific to one portal? → `customer.css` or `technician.css`

2. **Use Existing Components**:
   - Before creating new CSS, check if existing components can be used or extended
   - Prioritize composition over creating new styles

3. **Follow the Design System**:
   - Use CSS variables for colors, spacing, etc.
   - Maintain consistent visual styles
   - Document any new components or variations

4. **Test Thoroughly**:
   - Test on multiple browsers
   - Test on different screen sizes
   - Verify accessibility compliance

5. **Document**:
   - Add comments for complex CSS
   - Update this README when adding new patterns

## Style Guide

For a visual representation of all components, visit the [Style Guide Page](/style-guide) in the application.

---

