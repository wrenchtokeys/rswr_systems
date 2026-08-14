"""
Regression test: a four-figure invoice total printed vertically.

Root cause:
    The invoice PDF's totals table gave the amount column 1.0 inch
    (60pt of usable width after ReportLab's default 6pt cell padding) and
    set the TOTAL in 16pt Helvetica-Bold. "$999.99" measures 57.8pt and
    fit; "$1000.00" measures 66.7pt and did not. ParagraphStyle defaults to
    splitLongWords=1, and a number has no spaces to break at, so ReportLab
    broke the "word" character by character — the digits of every total
    over $1,000 stacked down the page instead of running across it.

Fix:
    - Amount column widened to 1.6in and the label column to 2.0in, still
      summing to the 7.0in the line-items table uses so the block stays
      right-aligned to the same edge.
    - Amounts carry thousands separators.
    - InvoiceService._fitted_style() shrinks the type just enough to keep
      any amount on one line, so an unexpectedly large total can only come
      out small, never stacked.

These assertions measure ReportLab's own line breaking, so they fail if
the column is narrowed, the font grown, or the fit guard removed.
"""

from decimal import Decimal

from django.test import SimpleTestCase

from reportlab.lib.units import inch
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.platypus import Paragraph

from apps.billing.services.invoice_service import InvoiceService


class LargeInvoiceTotalLayoutTests(SimpleTestCase):
    """The TOTAL must render on exactly one line at every realistic amount."""

    def setUp(self):
        self.service = InvoiceService()

    def _total_line_count(self, amount):
        """Lines ReportLab breaks the TOTAL cell into. 1 == correct."""
        text = self.service.money(amount)
        style = self.service._fitted_style(
            text,
            self.service.styles['TotalAmount'],
            self.service.TOTALS_AMOUNT_WIDTH - 2 * self.service.TABLE_CELL_PADDING,
        )
        para = Paragraph(f"<b>{text}</b>", style)
        para.wrap(
            self.service.TOTALS_AMOUNT_WIDTH - 2 * self.service.TABLE_CELL_PADDING,
            10000,
        )
        return len(para.blPara.lines)

    def test_totals_over_a_thousand_stay_on_one_line(self):
        # $1,000.00 is the exact threshold the old 1.0in column crossed.
        for amount in ['999.99', '1000.00', '1533.00', '9999.99',
                       '12345.67', '127450.00', '1234567.89']:
            with self.subTest(amount=amount):
                self.assertEqual(
                    self._total_line_count(Decimal(amount)), 1,
                    f"${amount} wrapped — a total must never print vertically",
                )

    def test_money_uses_thousands_separators(self):
        self.assertEqual(self.service.money(Decimal('1533.00')), '$1,533.00')
        self.assertEqual(self.service.money(Decimal('999.99')), '$999.99')
        self.assertEqual(self.service.money(Decimal('127450.00')), '$127,450.00')

    def test_totals_block_still_spans_the_line_items_table(self):
        """The three columns must sum to 7.0in or the block stops lining up
        with the line-items table above it."""
        total_width = (
            self.service.TOTALS_SPACER_WIDTH
            + self.service.TOTALS_LABEL_WIDTH
            + self.service.TOTALS_AMOUNT_WIDTH
        )
        self.assertAlmostEqual(total_width, 7.0 * inch, places=3)

    def test_longest_tax_label_fits_its_column(self):
        """'Special Tax (10.125%):' overflowed the old 1.5in label column."""
        avail = self.service.TOTALS_LABEL_WIDTH - 2 * self.service.TABLE_CELL_PADDING
        for label in ['Special Tax (10.125%):', 'County Tax (2.625%):',
                      'Subtotal:', 'Discounts:', 'TOTAL:']:
            with self.subTest(label=label):
                self.assertLessEqual(
                    stringWidth(label, 'Helvetica-Bold', 10), avail,
                    f"{label!r} does not fit the totals label column",
                )

    def test_fit_guard_shrinks_rather_than_wrapping(self):
        """An amount too wide for the column comes out smaller, not stacked."""
        style = self.service.styles['TotalAmount']
        narrow = 40  # deliberately too narrow for any real amount
        fitted = self.service._fitted_style('$1,234,567.89', style, narrow)
        self.assertLess(fitted.fontSize, style.fontSize)
        self.assertGreaterEqual(fitted.leading, fitted.fontSize)
