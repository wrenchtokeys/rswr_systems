"""Guard against multi-line `{# ... #}` template comments.

Django's `{# #}` comment is SINGLE-LINE ONLY. A comment that opens on one line
and closes on another is not a comment at all — the engine emits it verbatim, so
the explanatory note renders as visible text at the top of the page for every
user. It has slipped through twice during the UI overhaul (base_app.html and
owner_dashboard.html), both times reaching a browser before anyone noticed,
because nothing about it fails loudly: no exception, no 500, no test failure.

Multi-line commentary must use `{% comment %}...{% endcomment %}`.
"""

from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase


def _template_files():
    root = Path(settings.BASE_DIR)
    seen = set()
    for path in list(root.glob("templates/**/*.html")) + list(
        root.glob("apps/**/templates/**/*.html")
    ):
        if ".claude" in path.parts or "venv" in path.parts:
            continue
        if path not in seen:
            seen.add(path)
            yield path


class MultiLineTemplateCommentTests(SimpleTestCase):
    def test_no_unterminated_single_line_comments(self):
        """Every `{#` must be closed by a `#}` on the same line."""
        offenders = []
        for path in _template_files():
            try:
                lines = path.read_text().splitlines()
            except UnicodeDecodeError:  # pragma: no cover - binary stragglers
                continue
            for lineno, line in enumerate(lines, start=1):
                # Only the text AFTER the opener matters; a `#}` earlier in the
                # line belongs to a previous, already-closed comment.
                head, sep, tail = line.partition("{#")
                if sep and "#}" not in tail:
                    offenders.append(
                        f"{path.relative_to(settings.BASE_DIR)}:{lineno}: {line.strip()[:90]}"
                    )

        self.assertEqual(
            offenders,
            [],
            "Django `{# #}` comments are single-line only — these would render as "
            "visible text on the page. Use {% comment %}...{% endcomment %} "
            "instead:\n  " + "\n  ".join(offenders),
        )
