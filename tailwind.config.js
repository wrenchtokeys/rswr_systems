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
        // Canonical brand palette (Tailwind default blue). Previously inlined
        // in 14 templates; base_customer.html used #4299E1 for brand-500,
        // now unified to #3b82f6.
        brand: {
          50: '#eff6ff',
          100: '#dbeafe',
          200: '#bfdbfe',
          300: '#93c5fd',
          400: '#60a5fa',
          500: '#3b82f6',
          600: '#2563eb',
          700: '#1d4ed8',
          800: '#1e40af',
          900: '#1e3a8a',
        },
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', 'sans-serif'],
      },
    },
  },
  plugins: [],
};
