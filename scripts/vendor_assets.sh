#!/usr/bin/env bash
# Vendor the third-party front-end assets that used to load from CDNs
# (Google Fonts, Font Awesome via cdnjs, flatpickr via jsDelivr).
#
# Why: render-blocking third-party requests caused a visible font flash, leaked
# visitor IPs to three external hosts, and made a strict CSP impossible for an
# app that takes card payments. Same reasoning as the no-CDN rule for Tailwind.
#
# Idempotent — safe to re-run. Downloaded assets ARE committed (same policy as
# static/css/app.css and static/js/vendor/driver.iife.js) so EB deploys need no
# network access and no node/npm.
set -euo pipefail
cd "$(dirname "$0")/.."

FA_VERSION="6.4.0"
FLATPICKR_VERSION="4.6.13"
UA="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"

mkdir -p static/fonts static/css/vendor static/js/vendor

# ---------------------------------------------------------------------------
# 1. Inter — variable font, latin subset only.
#    One file covers weights 300-800 (the six the templates use) at a fraction
#    of the size of six static cuts. Google serves the variable woff2 when the
#    request uses a weight RANGE and a modern browser UA.
# ---------------------------------------------------------------------------
echo "==> Inter (variable, latin)"
INTER_CSS="$(curl -sL -A "$UA" 'https://fonts.googleapis.com/css2?family=Inter:wght@300..800&display=swap')"
# The last @font-face block in the response is the `latin` subset.
INTER_URL="$(printf '%s' "$INTER_CSS" | grep -Eo 'https://fonts\.gstatic\.com/[^)]*\.woff2' | tail -1)"
if [ -z "$INTER_URL" ]; then echo "Could not resolve Inter woff2 URL" >&2; exit 1; fi
curl -sL -o static/fonts/inter-variable-latin.woff2 "$INTER_URL"
echo "    static/fonts/inter-variable-latin.woff2 ($(wc -c < static/fonts/inter-variable-latin.woff2 | tr -d ' ') bytes)"

# ---------------------------------------------------------------------------
# 2. Font Awesome ${FA_VERSION} — CSS + only the three families actually used
#    (fas 1285 uses, fab 43, far 13). fa-v4compatibility and the duotone/light
#    Pro faces are not downloaded.
# ---------------------------------------------------------------------------
echo "==> Font Awesome ${FA_VERSION}"
FA_BASE="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/${FA_VERSION}"
curl -sL -o static/css/vendor/fontawesome.min.css "${FA_BASE}/css/all.min.css"
# fa-v4compatibility is referenced by all.min.css even though we use no v4 icon
# names; it must exist or ManifestStaticFilesStorage fails collectstatic.
for FACE in fa-solid-900 fa-regular-400 fa-brands-400 fa-v4compatibility; do
  curl -sL -o "static/fonts/${FACE}.woff2" "${FA_BASE}/webfonts/${FACE}.woff2"
done
python3 - <<'PY'
import pathlib, re
p = pathlib.Path("static/css/vendor/fontawesome.min.css")
css = p.read_text()
# Point at our static layout instead of FA's sibling ./webfonts dir.
css = css.replace("../webfonts/", "../../fonts/")
# Drop the .ttf fallbacks: woff2 has had universal support since 2016, and every
# referenced file must exist for manifest storage to hash it. Saves ~645 KB.
css = re.sub(r',\s*url\(\.\./\.\./fonts/[\w.-]+\.ttf\)\s*format\("truetype"\)', "", css)
p.write_text(css)
missing = sorted({u for u in re.findall(r"\.\./\.\./fonts/([\w.-]+)", css)
                  if not pathlib.Path("static/fonts", u).exists()})
assert not missing, f"CSS references unvendored files: {missing}"
print("    rewrote font URLs, dropped .ttf fallbacks, all references resolve")
PY

# ---------------------------------------------------------------------------
# 3. flatpickr ${FLATPICKR_VERSION} — datetime picker used by base_app.html and
#    base_customer.html. Pinned (the old CDN URL was unpinned "latest").
# ---------------------------------------------------------------------------
echo "==> flatpickr ${FLATPICKR_VERSION}"
FP_BASE="https://cdn.jsdelivr.net/npm/flatpickr@${FLATPICKR_VERSION}/dist"
curl -sL -o static/css/vendor/flatpickr.min.css "${FP_BASE}/flatpickr.min.css"
curl -sL -o static/js/vendor/flatpickr.min.js   "${FP_BASE}/flatpickr.min.js"

echo
echo "Done. Vendored:"
find static/fonts static/css/vendor static/js/vendor -type f | sort | while read -r f; do
  printf '  %-46s %8s bytes\n' "$f" "$(wc -c < "$f" | tr -d ' ')"
done
