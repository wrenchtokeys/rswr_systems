/** @type {import('tailwindcss').Config} */
// Single source of truth for the app's Tailwind theme.
// Compiled to static/css/app.css by scripts/build_css.sh — run it after any
// template or JS class change. Never reintroduce cdn.tailwindcss.com.
module.exports = {
  content: [
    './templates/**/*.html',
    './apps/**/templates/**/*.html',
    './static/js/**/*.js',
    // The tone tables in ui.py / email_ui.py / notifications_ui.py hold Tailwind
    // classes as Python strings — the single source of truth for status and
    // category colour. Nothing in a template spells them out, so without this
    // glob the purge takes them and a status pill renders shape-only. Tailwind's
    // extractor is a plain-text regex; the .py extension is not a problem.
    './core/templatetags/*.py',
  ],
  safelist: [
    // saas/pricing.html composes lg:grid-cols-{{ plans|length }} (1–4 plans)
    { pattern: /^grid-cols-[1-4]$/, variants: ['sm', 'lg'] },
    // viscosity_rules.html composes badge-{{ rule.badge_color }} (BADGE_COLOR_CHOICES)
    { pattern: /^badge-(gray|blue|green|yellow|orange|red|purple)$/ },
    // Type scale + material rungs (UI_MAGIC_PLAN R2/R3). Kept alive while pages
    // are migrated to them one at a time, so a template can adopt `.t-h1` and
    // have it work immediately instead of silently rendering unstyled.
    { pattern: /^t-(display|h1|h2|h3|body|sub|caption)$/ },
    'surface-float',
    // Safe-area helpers. `.safe-area-bottom` is used today; the other two are
    // shared component classes kept alive for the shells that need them next
    // — an @layer components class no template references yet is purged.
    { pattern: /^safe-area-(top|bottom|x)$/ },
    // Schedule drag-to-swap state (S7). These are toggled by name from
    // static/js/schedule_swap.js and never appear in a template, so the
    // purge has nothing to anchor them to.
    { pattern: /^swap-(row-dragging|row-target|row-selected|dragging|busy)$/ },
    // Skeleton + optimistic row state (S11). Built by static/js/list-loading.js
    // and static/js/optimistic.js, which the content glob does scan — but these
    // are the vocabulary those two files hand to the rest of the app, and a
    // page that starts using `.sk-bar` in its own markup should not have to
    // discover that the purge already took it.
    { pattern: /^sk-(bar|lines|list)$/ },
    // {% icon %} (S13). The class is emitted from core/templatetags/ui.py as
    // `class="icon{extra}"` — the extractor is a plain-text regex and does not
    // see a bare `icon` token in that string, so the one rule the whole icon
    // vocabulary depends on would be purged. Pinned by tests/test_icon_tag.py.
    'icon',
    { pattern: /^row-(pending|rollback)$/ },
    'paid-check',
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
