"""
Regression tests for UX-010 and UX-011 billing settings fixes.

UX-010 — Overdue Reminders: Email Subject field truncated (owner_settings.html)
  Root cause: The Email Subject was rendered as a single-line <input type="text">.
  Long template strings like "Reminder: Invoice #{invoice_number} is overdue"
  are wider than the visible input, making them hard to read/edit.
  Fix: Changed to <textarea rows="2" class="... resize-none"> so the full
  template string is visible without truncation.

UX-011 — Batch Invoicing: "Day" field visible/editable when Frequency=Disabled
  Root cause: The Day <input> and its label were always rendered with no
  conditional visibility. When Frequency = "Disabled" the Day field is
  meaningless but still editable, confusing owners.
  Fix: Added id="batch-frequency-select", id="batch-day-field", and
  id="batch-day-input" so JavaScript can hide/disable the Day field when
  Frequency is "Disabled" and update its placeholder/hint text dynamically
  for weekly vs monthly mode. Server-side template unchanged — JS handles UX.
"""
import os
from django.test import TestCase

TEMPLATE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    'templates',
)


def _read_template(*path_parts):
    path = os.path.join(TEMPLATE_DIR, *path_parts)
    with open(path, 'r') as f:
        return f.read()


class UX010EmailSubjectTextareaTest(TestCase):
    """UX-010: Email Subject should use <textarea>, not <input type=text>."""

    def setUp(self):
        self.html = _read_template('saas', 'owner_settings.html')

    def test_overdue_subject_uses_textarea(self):
        """Email Subject must be a <textarea> so long template strings are visible."""
        # Should use textarea, not a plain text input for the subject
        self.assertIn('<textarea name="overdue_reminder_subject"', self.html,
                      "Email Subject must use <textarea> to prevent truncation of long template strings.")

    def test_overdue_subject_no_text_input(self):
        """The old single-line input for subject should be gone."""
        self.assertNotIn('<input type="text" name="overdue_reminder_subject"', self.html,
                         "Old <input type=text> for overdue_reminder_subject must be replaced by <textarea>.")

    def test_subject_textarea_has_resize_none(self):
        """Textarea should not be freely resizable (keeps layout tidy)."""
        self.assertIn('resize-none', self.html,
                      "Subject textarea should have resize-none class to keep layout stable.")

    def test_subject_helper_text_present(self):
        """Template variable hint must still be shown below the subject field."""
        self.assertIn('{invoice_number}', self.html,
                      "Helper text with {invoice_number} must still be present for owners.")
        self.assertIn('{customer_name}', self.html)
        self.assertIn('{amount_due}', self.html)
        self.assertIn('{days_overdue}', self.html)


class UX011BatchDayFieldVisibilityTest(TestCase):
    """UX-011: Batch Invoicing Day field must have JS hooks to hide when Disabled."""

    def setUp(self):
        self.html = _read_template('saas', 'owner_settings.html')

    def test_frequency_select_has_id(self):
        """Frequency <select> must have id='batch-frequency-select' for JS targeting."""
        self.assertIn('id="batch-frequency-select"', self.html,
                      "Frequency select must have id='batch-frequency-select' so JS can listen for changes.")

    def test_day_field_wrapper_has_id(self):
        """Day field wrapper div must have id='batch-day-field' for hide/show."""
        self.assertIn('id="batch-day-field"', self.html,
                      "Day field wrapper div must have id='batch-day-field' for JS show/hide.")

    def test_day_input_has_id(self):
        """Day input must have id='batch-day-input' for JS disable/enable."""
        self.assertIn('id="batch-day-input"', self.html,
                      "Day input must have id='batch-day-input' so JS can disable it when Frequency=Disabled.")

    def test_day_hint_has_id(self):
        """Day hint paragraph must have id='batch-day-hint' for dynamic text."""
        self.assertIn('id="batch-day-hint"', self.html,
                      "Day hint <p> must have id='batch-day-hint' so JS can update text for weekly vs monthly.")

    def test_js_update_function_defined(self):
        """updateBatchDayField JS function must be defined in the template."""
        self.assertIn('function updateBatchDayField()', self.html,
                      "updateBatchDayField() JS function must be defined to handle Day field visibility.")

    def test_js_disables_on_disabled_frequency(self):
        """JS must handle the 'disabled' frequency case."""
        self.assertIn("freq === 'disabled'", self.html,
                      "JS must check for freq === 'disabled' to hide/disable the Day field.")

    def test_js_monthly_hint(self):
        """JS must show monthly-specific hint when monthly is selected."""
        self.assertIn("freq === 'monthly'", self.html,
                      "JS must show different hint text for monthly vs weekly frequency.")

    def test_js_listens_to_frequency_change(self):
        """JS must attach change listener to frequency select on DOMContentLoaded."""
        self.assertIn("addEventListener('change', updateBatchDayField)", self.html,
                      "JS must attach change event listener to frequency select.")

    def test_js_init_on_dom_ready(self):
        """updateBatchDayField must be called on DOMContentLoaded for initial state."""
        self.assertIn('updateBatchDayField();', self.html,
                      "updateBatchDayField() must be called on page load to set initial state.")

    def test_frequency_options_intact(self):
        """All four frequency options must still be present after edits."""
        for val in ('disabled', 'weekly', 'biweekly', 'monthly'):
            self.assertIn(f'value="{val}"', self.html,
                          f"Frequency option '{val}' must still be present in the select.")
