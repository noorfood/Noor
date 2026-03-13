from django.shortcuts import render, redirect, get_object_or_404
from django.forms import modelform_factory
from django.contrib import messages
from accounts.mixins import get_current_user, role_required
from audit.utils import log_action

from procurement.models import RawMaterialReceipt, RawMaterialIssuance
from cleaning.models import CleanRawReceipt
from clean_store.models import CleanRawIssuance, CleanRawReturn
from production.models import MillingBatch, PackagingBatch
from finished_store.models import FinishedGoodsReceipt, FinishedGoodsIssuance
from sales.models import (
    SalesRecord, SalesPerson, SalesPayment, 
    SalesManagerCollection, SalesDistributionRecord, SalesResult, SalesManagerPayment
)
from reconciliation.models import MoneyReceipt, ReconciliationFlag
from audit.models import AuditLog


# ─── Central model registry ──────────────────────────────────────────────────
MODEL_MAP = {
    # Procurement
    'raw-receipts':       (RawMaterialReceipt,  ['created_at', 'date', 'material_type', 'supplier', 'num_bags', 'approx_weight_kg', 'reference_no']),
    'raw-issuances':      (RawMaterialIssuance, ['created_at', 'date', 'material_type', 'num_bags_issued', 'issued_to', 'issued_by']),
    
    # Cleaning
    'clean-receipts':     (CleanRawReceipt,      ['created_at', 'date', 'material_type', 'num_bags', 'received_by']),
    
    # Operations / Store
    'clean-issuances':    (CleanRawIssuance,     ['created_at', 'date', 'material_type', 'num_bags', 'issued_to', 'issued_by']),
    'clean-returns':      (CleanRawReturn,       ['created_at', 'date', 'material_type', 'num_bags', 'returned_by']),
    'milling-batches':    (MillingBatch,         ['created_at', 'date', 'material_type', 'shift', 'bags_milled_new', 'bulk_powder_kg', 'loss_kg', 'loss_pct', 'flag_level']),
    'packaging-batches':  (PackagingBatch,       ['created_at', 'date', 'material_type', 'shift', 'powder_used_kg', 'qty_10kg', 'total_output_kg', 'loss_kg', 'loss_pct']),
    'fg-receipts':        (FinishedGoodsReceipt, ['created_at', 'date', 'product_size', 'qty_received', 'received_by']),
    'fg-issuances':       (FinishedGoodsIssuance,['created_at', 'date', 'product_size', 'qty_issued', 'channel', 'status', 'sales_record', 'issued_to', 'issued_by']),
    
    # Sales & Team
    'sales-persons':      (SalesPerson,          ['created_at', 'name', 'channel', 'phone', 'status', 'created_by']),
    'sm-collections':     (SalesManagerCollection, ['created_at', 'date', 'sales_manager', 'material_type', 'qty_sacks', 'total_value', 'status']),
    'sp-distributions':   (SalesDistributionRecord, ['created_at', 'date', 'sales_manager', 'sales_person', 'material_type', 'qty_given']),
    'sp-results':         (SalesResult,          ['created_at', 'date', 'sales_person', 'qty_sold', 'gross_value', 'commission_amount', 'net_due_to_company']),
    'sm-payments':        (SalesManagerPayment,  ['created_at', 'date', 'sales_manager', 'amount_cash', 'amount_transfer', 'status']),
    
    # Financials & Reconciliation
    'money-receipts':     (MoneyReceipt,         ['created_at', 'date', 'sales_manager', 'sales_person', 'cash_received', 'transfer_received', 'notes']),
    'recon-flags':        (ReconciliationFlag,   ['created_at', 'date', 'sales_person', 'expected_amount', 'actual_amount', 'difference', 'resolved', 'flagged_by']),
    
    # Audit
    'audit-log':          (AuditLog,             ['timestamp', 'user_name', 'user_role', 'module', 'action', 'description']),

    # Legacy (kept for data integrity access)
    'sales-records':      (SalesRecord,          ['created_at', 'date', 'channel', 'sales_person', 'product_size', 'qty_sold', 'unit_price', 'total_value', 'status']),
    'sales-payments':     (SalesPayment,         ['created_at', 'date', 'sales_record', 'amount_cash', 'amount_transfer', 'recorded_by']),
}

CATEGORIZED_MODELS = [
    ('Procurement', ['raw-receipts', 'raw-issuances']),
    ('Cleaning', ['clean-receipts']),
    ('Operations & Store', ['clean-issuances', 'clean-returns', 'milling-batches', 'packaging-batches', 'fg-receipts', 'fg-issuances']),
    ('Sales Management', ['sales-persons', 'sm-collections', 'sp-distributions', 'sp-results', 'sm-payments']),
    ('Reconciliation', ['money-receipts', 'recon-flags']),
    ('System & Audit', ['audit-log']),
    ('Legacy Records', ['sales-records', 'sales-payments']),
]


import datetime

def _safe_val(val):
    """Safely stringify any field value for display including related objects, but leave dates alone."""
    if val is None:
        return '—'
    
    # Custom display logic for common relations
    if hasattr(val, 'full_name'):
        return val.full_name
    if hasattr(val, 'name') and hasattr(val, 'channel'): # SalesPerson
        return f"{val.name} ({val.get_channel_display()})"
    if hasattr(val, 'pk') and hasattr(val, 'material_type') and hasattr(val, 'qty_sacks'): # SM Collection
        return f"Coll #{val.pk} ({val.material_type} - {val.qty_sacks} bags)"
    
    if hasattr(val, 'name'):
        return val.name
    if isinstance(val, (datetime.date, datetime.datetime)):
        return val
    
    # Check for Decimal types or numbers to format them cleanly
    if isinstance(val, (int, float)):
        return f"{val:,}" if val > 1000 else str(val)

    return str(val)


@role_required('md')
def explorer_home(request):
    user = get_current_user(request)
    return render(request, 'data_explorer/home.html', {
        'current_user': user,
        'categorized_models': CATEGORIZED_MODELS,
    })


@role_required('md')
def explore_model(request, model_name):
    user = get_current_user(request)

    if model_name not in MODEL_MAP:
        return render(request, 'data_explorer/not_found.html', {
            'current_user': user, 'model_name': model_name,
        })

    Model, fields = MODEL_MAP[model_name]
    raw_records = Model.objects.all().order_by('-pk')[:500]

    # Pre-format field labels for the header
    field_labels = [f.replace('_', ' ').title() for f in fields]

    records = []
    for r in raw_records:
        values = []
        for f in fields:
            raw = getattr(r, f, None)
            values.append((_safe_val(raw), f))
        records.append({'pk': r.pk, 'values': values})

    return render(request, 'data_explorer/table.html', {
        'current_user': user,
        'model_name': model_name,
        'fields': field_labels, # Pass formatted labels
        'records': records,
        'all_models': list(MODEL_MAP.keys()),
        'record_count': len(records),
    })


@role_required('md')
def explore_edit(request, model_name, pk):
    """Universal Edit View (God Mode)"""
    user = get_current_user(request)

    if model_name not in MODEL_MAP:
        return redirect('data_explorer:home')

    Model = MODEL_MAP[model_name][0]
    instance = get_object_or_404(Model, pk=pk)

    exclude_fields = ['id', 'created_at', 'updated_at', 'timestamp']
    DynamicForm = modelform_factory(Model, exclude=exclude_fields)

    if request.method == 'POST':
        form = DynamicForm(request.POST, instance=instance)
        if form.is_valid():
            form.save()
            log_action(request, user, 'data_explorer', 'GOD_MODE_EDIT',
                       f'Edited {model_name} #{pk}', model_name, pk)
            messages.success(request, f'Record #{pk} in {model_name} updated successfully.')
            return redirect('data_explorer:model', model_name=model_name)
    else:
        form = DynamicForm(instance=instance)

    return render(request, 'data_explorer/edit.html', {
        'current_user': user,
        'model_name': model_name,
        'instance': instance,
        'form': form,
    })


@role_required('md')
def explore_delete(request, model_name, pk):
    """Universal Delete View (God Mode)"""
    user = get_current_user(request)

    if model_name not in MODEL_MAP:
        return redirect('data_explorer:home')

    Model = MODEL_MAP[model_name][0]
    instance = get_object_or_404(Model, pk=pk)

    if request.method == 'POST':
        instance.delete()
        log_action(request, user, 'data_explorer', 'GOD_MODE_DELETE',
                   f'PERMANENTLY DELETED {model_name} #{pk}', model_name, pk)
        messages.success(request, f'Record #{pk} permanently deleted from {model_name}.')
        return redirect('data_explorer:model', model_name=model_name)

    return render(request, 'data_explorer/delete.html', {
        'current_user': user,
        'model_name': model_name,
        'instance': instance,
    })
