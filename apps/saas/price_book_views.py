"""
Shop-owned price book (B6), owner side.

Split out of apps/saas/views.py the way claim_views and quote_views are.
The book fills itself from completed replacements (services/price_book);
this is where the owner sees it, pins a price, adds one the shop has not
done yet, or rebuilds the learned rows from history. Owner/manager only —
it is the shop's price list.
"""

import logging

from django import forms
from django.contrib import messages
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.technician_portal.models import Replacement
from apps.technician_portal.price_book_models import ANY_YEAR, PriceBookEntry
from apps.technician_portal.services import price_book
from common.decorators import owner_or_manager_required

logger = logging.getLogger(__name__)

_INPUT = (
    'w-full px-3 py-2 border border-gray-300 rounded-lg text-sm '
    'focus:ring-2 focus:ring-brand-500 focus:border-brand-500 outline-none transition'
)


class PriceBookEntryForm(forms.ModelForm):
    vehicle_year = forms.IntegerField(
        required=False, min_value=1900, max_value=2100,
        widget=forms.NumberInput(attrs={'class': _INPUT, 'placeholder': 'any year'}),
        help_text='Leave blank to cover every year of this model.',
    )
    glass_position = forms.ChoiceField(
        required=False,
        choices=[('', 'Not specified')] + Replacement.GLASS_POSITION_CHOICES,
        widget=forms.Select(attrs={'class': _INPUT + ' bg-white'}),
    )
    price = forms.DecimalField(
        required=False, min_value=0, max_digits=10, decimal_places=2,
        widget=forms.NumberInput(attrs={'class': _INPUT, 'step': '0.01', 'placeholder': 'parts + labor + ADAS'}),
        help_text='Blank means parts + labor + ADAS. What the customer pays before any account discount.',
    )

    class Meta:
        model = PriceBookEntry
        fields = [
            'vehicle_year', 'vehicle_make', 'vehicle_model', 'glass_position',
            'parts_cost', 'labor_cost', 'adas_calibration_cost', 'price',
        ]
        widgets = {
            'vehicle_make': forms.TextInput(attrs={'class': _INPUT, 'placeholder': 'Ford'}),
            'vehicle_model': forms.TextInput(attrs={'class': _INPUT, 'placeholder': 'F-150'}),
            'parts_cost': forms.NumberInput(attrs={'class': _INPUT, 'step': '0.01', 'placeholder': '0.00'}),
            'labor_cost': forms.NumberInput(attrs={'class': _INPUT, 'step': '0.01', 'placeholder': '0.00'}),
            'adas_calibration_cost': forms.NumberInput(attrs={'class': _INPUT, 'step': '0.01', 'placeholder': '0.00'}),
        }

    def __init__(self, *args, tenant, **kwargs):
        super().__init__(*args, **kwargs)
        self.tenant = tenant
        if self.instance.pk and self.instance.is_any_year:
            self.initial['vehicle_year'] = None

    def clean(self):
        cleaned = super().clean()
        if cleaned.get('vehicle_year') in (None, ''):
            cleaned['vehicle_year'] = ANY_YEAR
        parts, labor, adas = (
            cleaned.get('parts_cost'), cleaned.get('labor_cost'), cleaned.get('adas_calibration_cost'),
        )
        if cleaned.get('price') in (None, ''):
            total = PriceBookEntry.total_of(parts, labor, adas)
            if total <= 0:
                self.add_error('price', 'Enter a price, or parts and labor.')
            cleaned['price'] = total
        elif cleaned['price'] <= 0:
            self.add_error('price', 'The price has to be more than $0.')
        make, model = cleaned.get('vehicle_make'), cleaned.get('vehicle_model')
        if make and model:
            from apps.technician_portal.price_book_models import normalize_key
            clash = PriceBookEntry.objects.filter(
                tenant=self.tenant, make_key=normalize_key(make), model_key=normalize_key(model),
                vehicle_year=cleaned['vehicle_year'], glass_position=cleaned.get('glass_position') or '',
            ).exclude(pk=self.instance.pk)
            if clash.exists():
                self.add_error(None, 'Your book already has a price for that vehicle and glass — edit that row instead.')
        return cleaned


def _tenant(request):
    tenant = getattr(request, 'tenant', None)
    if tenant is None:
        messages.error(request, 'Could not determine your shop. Please log in again.')
    return tenant


@owner_or_manager_required
def price_book_list(request):
    tenant = _tenant(request)
    if tenant is None:
        return redirect('owner_dashboard')
    q = (request.GET.get('q') or '').strip()
    rows = PriceBookEntry.objects.filter(tenant=tenant).select_related('last_job')
    if q:
        rows = rows.filter(Q(vehicle_make__icontains=q) | Q(vehicle_model__icontains=q))
    rows = list(rows)
    total = PriceBookEntry.objects.filter(tenant=tenant).count()
    return render(request, 'saas/price_book_list.html', {
        'tenant': tenant,
        'rows': rows,
        'q': q,
        'total': total,
        'pinned_count': sum(1 for r in rows if r.is_pinned),
        'completed_replacements': Replacement.objects.filter(
            tenant=tenant, queue_status='COMPLETED',
        ).count(),
    })


def _edit(request, entry):
    tenant = _tenant(request)
    if tenant is None:
        return redirect('owner_dashboard')
    if request.method == 'POST':
        form = PriceBookEntryForm(request.POST, instance=entry, tenant=tenant)
        if form.is_valid():
            row = form.save(commit=False)
            row.tenant = tenant
            row.source = PriceBookEntry.SOURCE_PINNED   # the shop's word beats history
            row.save()
            messages.success(
                request,
                f'{row.vehicle_label} {row.glass_label.lower()} pinned at ${row.price:,.2f}. '
                'Completed jobs will not change it.',
            )
            return redirect('price_book_list')
    else:
        form = PriceBookEntryForm(instance=entry, tenant=tenant)
    return render(request, 'saas/price_book_form.html', {
        'tenant': tenant, 'form': form, 'entry': entry if entry.pk else None,
    })


@owner_or_manager_required
def price_book_new(request):
    return _edit(request, PriceBookEntry())


@owner_or_manager_required
def price_book_edit(request, entry_id):
    tenant = _tenant(request)
    if tenant is None:
        return redirect('owner_dashboard')
    entry = get_object_or_404(PriceBookEntry, pk=entry_id, tenant=tenant)
    return _edit(request, entry)


@owner_or_manager_required
@require_POST
def price_book_delete(request, entry_id):
    tenant = _tenant(request)
    if tenant is None:
        return redirect('owner_dashboard')
    entry = get_object_or_404(PriceBookEntry, pk=entry_id, tenant=tenant)
    label = f'{entry.vehicle_label} {entry.glass_label.lower()}'
    entry.delete()
    messages.success(request, f'Removed {label} from your price book. The next completed job on it will add it back.')
    return redirect('price_book_list')


@owner_or_manager_required
@require_POST
def price_book_rebuild(request):
    tenant = _tenant(request)
    if tenant is None:
        return redirect('owner_dashboard')
    read, rows = price_book.rebuild_for_tenant(tenant)
    messages.success(
        request,
        f'Rebuilt from {read} completed replacement{"s" if read != 1 else ""} — '
        f'{rows} price{"s" if rows != 1 else ""} in your book. Pinned prices were kept.',
    )
    return redirect('price_book_list')
