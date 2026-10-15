/** @type {import('tailwindcss').Config} */
// Single source of truth for the app's Tailwind theme.
// Compiled to static/css/app.css by scripts/build_css.sh — run it after any
// template or JS class change. Never reintroduce cdn.tailwindcss.com.
// Dark mode flips the PALETTE, not the templates (scripts/dark_palette.py).
// Every colour family the app uses reads a CSS variable: backgrounds, borders
// and rings read --c-<family>-<n>; text reads --tx-<family>-<n>, falling back
// to the --c- value. :root (assets/css/input.css) holds Tailwind's own light
// values, so light mode paints exactly what it did; assets/css/theme-dark.css
// re-points them under <html data-theme="dark">. Never add `dark:` utilities.
const SHADES = [50, 100, 200, 300, 400, 500, 600, 700, 800, 900, 950];
const FAMILIES = ['gray', 'red', 'orange', 'amber', 'yellow', 'green', 'emerald',
  'teal', 'cyan', 'sky', 'blue', 'indigo', 'purple', 'pink'];
const BRAND_SHADES = [50, 100, 200, 300, 400, 500, 600, 700, 800, 900];

const scale = (shades, varFor) =>
  Object.fromEntries(shades.map((n) => [n, `rgb(${varFor(n)} / <alpha-value>)`]));
const surfaceColors = Object.fromEntries(
  FAMILIES.map((f) => [f, scale(SHADES, (n) => `var(--c-${f}-${n})`)]));
const textColors = Object.fromEntries(
  FAMILIES.map((f) => [f, scale(SHADES, (n) => `var(--tx-${f}-${n}, var(--c-${f}-${n}))`)]));

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
        // at runtime — defaults in assets/css/input.css are Tailwind
        // blue (#3b82f6 at 500), so nothing changes for shops without one.
        // Channels are space-separated RGB ("59 130 246") to keep Tailwind's
        // opacity modifiers (e.g. bg-brand-500/50) working.
        brand: scale(BRAND_SHADES, (n) => `var(--brand-${n})`),
        ...surfaceColors,
      },
      // Text gets its own variables so `text-gray-900` can go light while
      // `bg-gray-900` stays a dark chip, and `text-brand-600` can lift for a
      // dark card while `bg-brand-600 text-white` stays the shop's button.
      textColor: {
        brand: scale(BRAND_SHADES, (n) => `var(--brand-tx-${n}, var(--brand-${n}))`),
        ...textColors,
      },
      placeholderColor: {
        brand: scale(BRAND_SHADES, (n) => `var(--brand-tx-${n}, var(--brand-${n}))`),
        ...textColors,
      },
      // `bg-white` is the card surface; it reads a variable so it can become
      // the dark card. `text-white` / `border-white` stay literal white — they
      // sit on saturated fills that do not move.
      backgroundColor: {
        white: 'rgb(var(--surface-white, 255 255 255) / <alpha-value>)',
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', 'sans-serif'],
      },
    },
  },
  plugins: [],
};
