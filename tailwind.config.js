/** @type {import('tailwindcss').Config} */
// Single source of truth for the app's Tailwind theme.
// Compiled to static/css/app.css by scripts/build_css.sh — run it after any
// template or JS class change. Never reintroduce cdn.tailwindcss.com.
module.exports = {
  content: [
    './templates/**/*.html',
    './apps/**/templates/**/*.html',
    './static/js/**/*.js',
  ],
  safelist: [
    // saas/pricing.html composes lg:grid-cols-{{ plans|length }} (1–4 plans)
    { pattern: /^grid-cols-[1-4]$/, variants: ['sm', 'lg'] },
    // viscosity_rules.html composes badge-{{ rule.badge_color }} (BADGE_COLOR_CHOICES)
    { pattern: /^badge-(gray|blue|green|yellow|orange|red|purple)$/ },
  ],
  theme: {
    extend: {
      colors: {
        // Canonical brand palette. Reads CSS variables so a shop's own
        // brand color (Tenant.brand_color) can retheme the customer portal
        // at runtime — defaults in static/css/src/input.css are Tailwind
        // blue (#3b82f6 at 500), so nothing changes for shops without one.
        // Channels are space-separated RGB ("59 130 246") to keep Tailwind's
        // opacity modifiers (e.g. bg-brand-500/50) working.
        brand: {
          50: 'rgb(var(--brand-50) / <alpha-value>)',
          100: 'rgb(var(--brand-100) / <alpha-value>)',
          200: 'rgb(var(--brand-200) / <alpha-value>)',
          300: 'rgb(var(--brand-300) / <alpha-value>)',
          400: 'rgb(var(--brand-400) / <alpha-value>)',
          500: 'rgb(var(--brand-500) / <alpha-value>)',
          600: 'rgb(var(--brand-600) / <alpha-value>)',
          700: 'rgb(var(--brand-700) / <alpha-value>)',
          800: 'rgb(var(--brand-800) / <alpha-value>)',
          900: 'rgb(var(--brand-900) / <alpha-value>)',
        },
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', 'sans-serif'],
      },
    },
  },
  plugins: [],
};
