# CSS Linting Setup for RS Systems

This document provides instructions for setting up CSS linting for the RS Systems project to maintain consistent code quality and styling.

## Prerequisites

- Node.js and npm installed on your system

## Setup Instructions

1. Install the required dependencies:

```bash
npm install --save-dev stylelint stylelint-config-standard
```

2. Create a `.stylelintrc.js` file in the project root with the following content:

```javascript
module.exports = {
  extends: 'stylelint-config-standard',
  rules: {
    'indentation': 4,
    'color-hex-case': 'lower',
    'color-hex-length': 'long',
    'color-named': 'never',
    'color-no-invalid-hex': true,
    'font-family-name-quotes': 'always-where-recommended',
    'font-weight-notation': 'numeric',
    'function-comma-space-after': 'always',
    'function-url-quotes': 'always',
    'string-quotes': 'single',
    'value-keyword-case': 'lower',
    'unit-case': 'lower',
    'property-case': 'lower',
    'declaration-block-trailing-semicolon': 'always',
    'selector-pseudo-class-case': 'lower',
    'selector-pseudo-element-case': 'lower',
    'selector-type-case': 'lower',
    'media-feature-name-case': 'lower',
    'at-rule-name-case': 'lower',
    'no-duplicate-selectors': true,
    'no-descending-specificity': null,
    'declaration-block-no-duplicate-properties': true,
    'declaration-block-no-shorthand-property-overrides': true,
    'selector-class-pattern': '^[a-z][a-z0-9-_]*$',
    'selector-id-pattern': '^[a-z][a-z0-9-_]*$',
    'comment-whitespace-inside': 'always',
    'comment-empty-line-before': 'always',
    'rule-empty-line-before': [
      'always',
      {
        'except': ['first-nested'],
        'ignore': ['after-comment']
      }
    ],
    'declaration-empty-line-before': [
      'always',
      {
        'except': ['first-nested'],
        'ignore': ['after-comment', 'after-declaration']
      }
    ],
    'block-no-empty': true,
    'shorthand-property-no-redundant-values': true,
    'property-no-vendor-prefix': true,
    'value-no-vendor-prefix': true,
    'selector-no-vendor-prefix': true,
    'media-feature-name-no-vendor-prefix': true,
    'at-rule-no-vendor-prefix': true
  }
};
```

3. Add the following scripts to your `package.json` file:

```json
{
  "scripts": {
    "lint:css": "stylelint 'static/css/*.css'",
    "lint:css:fix": "stylelint 'static/css/*.css' --fix"
  }
}
```

## Running the Linter

- To check for CSS linting issues:
  ```bash
  npm run lint:css
  ```

- To automatically fix CSS linting issues where possible:
  ```bash
  npm run lint:css:fix
  ```

## CSS Coding Standards

Follow these guidelines when writing CSS:

1. Use kebab-case for class names (e.g., `.button-primary` not `.buttonPrimary`)
2. Use CSS variables for colors, spacing, and other design tokens
3. Group related properties together
4. Follow a consistent order of properties:
   - Positioning (position, top, right, bottom, left, z-index)
   - Box model (display, width, height, margin, padding)
   - Typography (font, line-height, text-align, etc.)
   - Visual (color, background, border, etc.)
   - Miscellaneous (cursor, overflow, etc.)
5. Avoid using `!important` except in utility classes
6. Write mobile-first media queries
7. Avoid overly specific selectors
8. Use the BEM methodology for component variants and states:
   - Block: `.button`
   - Element: `.button__icon`
   - Modifier: `.button--large`

## Integration with Code Editors

### VS Code

1. Install the stylelint extension:
   ```
   ext install stylelint.vscode-stylelint
   ```

2. Configure VS Code to use stylelint for CSS files by adding to your settings.json:
   ```json
   {
     "editor.codeActionsOnSave": {
       "source.fixAll.stylelint": true
     },
     "stylelint.validate": ["css"]
   }
   ```

### JetBrains IDEs (WebStorm, PhpStorm, etc.)

1. Go to Preferences > Languages & Frameworks > Style Sheets > Stylelint
2. Check "Enable" and make sure the configuration file is set to the project's `.stylelintrc.js`

## Pre-commit Hook (Optional)

To ensure all CSS files are linted before committing, you can set up a pre-commit hook using Husky:

1. Install Husky and lint-staged:
   ```bash
   npm install --save-dev husky lint-staged
   ```

2. Add to your package.json:
   ```json
   {
     "husky": {
       "hooks": {
         "pre-commit": "lint-staged"
       }
     },
     "lint-staged": {
       "*.css": ["stylelint --fix"]
     }
   }
   ```

This will automatically run stylelint on any CSS files that are staged for commit. 