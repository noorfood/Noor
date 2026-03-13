from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.db.models import Sum
from accounts.mixins import get_current_user, role_required, store_type_required
from audit.utils import log_action
from procurement.models import RawMaterialReceipt, RawMaterialIssuance, CleaningLossConfig
import datetime


def _get_raw_store_balance(material_type):
    """Raw store balance = bags received from market minus bags issued to cleaners."""
    received = RawMaterialReceipt.objects.filter(material_type=material_type).aggregate(t=Sum('num_bags'))['t'] or 0
    issued = RawMaterialIssuance.objects.filter(material_type=material_type).aggregate(t=Sum('num_bags_issued'))['t'] or 0
    return received - issued


@role_required('store_officer', 'manager', 'md')
@store_type_required('raw')
def dashboard(request):
    user = get_current_user(request)
    receipts = RawMaterialReceipt.objects.filter(received_by=user).order_by('-date', '-created_at')[:10] if user.is_store_officer else RawMaterialReceipt.objects.all().order_by('-date', '-created_at')[:20]
    balance_maize = _get_raw_store_balance('maize')
    balance_wheat = _get_raw_store_balance('wheat')
    pending_costs = RawMaterialReceipt.objects.filter(cost_status='pending').count() if user.role == 'md' else 0
    return render(request, 'procurement/dashboard.html', {
        'current_user': user, 'receipts': receipts,
        'balance_maize': balance_maize, 'balance_wheat': balance_wheat,
        'pending_costs': pending_costs,
    })


@role_required('store_officer', 'manager', 'md')
@store_type_required('raw')
def receive_raw(request):
    user = get_current_user(request)
    error = None

    if request.method == 'POST':
        try:
            date_val = request.POST.get('date')
            material_type = request.POST.get('material_type')
            supplier = request.POST.get('supplier', '').strip()
            num_bags = int(request.POST.get('num_bags', 0))
            approx_weight_kg = float(request.POST.get('approx_weight_kg', 0))
            reference_no = request.POST.get('reference_no', '').strip()
            notes = request.POST.get('notes', '').strip()

            if not date_val or not material_type or not supplier or num_bags <= 0 or approx_weight_kg <= 0:
                error = 'Please fill in all required fields with valid values.'
            else:
                receipt = RawMaterialReceipt.objects.create(
                    date=date_val,
                    material_type=material_type,
                    supplier=supplier,
                    num_bags=num_bags,
                    approx_weight_kg=approx_weight_kg,
                    reference_no=reference_no,
                    received_by=user,
                    notes=notes,
                    is_locked=True,
                    cost_status='pending',
                )
                log_action(request, user, 'procurement', 'RECEIVE_RAW',
                           f'Received {num_bags} bags of {material_type} from {supplier}',
                           'RawMaterialReceipt', receipt.pk)
                messages.success(request, f'Receipt #{receipt.pk} saved. Awaiting MD cost review.')
                return redirect('procurement:list')
        except Exception as e:
            error = f'Error saving record: {str(e)}'

    return render(request, 'procurement/receive_raw.html', {
        'current_user': user, 'error': error,
        'today': datetime.date.today().isoformat(),
    })


@role_required('store_officer', 'manager', 'md')
@store_type_required('raw')
def issue_raw(request):
    user = get_current_user(request)
    receipts = RawMaterialReceipt.objects.filter(received_by=user).order_by('-date', '-created_at') if user.is_store_officer else RawMaterialReceipt.objects.all().order_by('-date', '-created_at')
    error = None
    balance_maize = _get_raw_store_balance('maize')
    balance_wheat = _get_raw_store_balance('wheat')

    if request.method == 'POST':
        try:
            date_val = request.POST.get('date')
            material_type = request.POST.get('material_type')
            num_bags_issued = int(request.POST.get('num_bags_issued', 0))
            issued_to_name = request.POST.get('issued_to', '').strip()
            notes = request.POST.get('notes', '').strip()

            if not date_val or not material_type or num_bags_issued <= 0 or not issued_to_name:
                error = 'Please fill in all required fields.'
            else:
                balance = _get_raw_store_balance(material_type)
                if num_bags_issued > balance:
                    error = f'Not enough stock. Current {material_type} balance: {balance} bags.'
                else:
                    issuance = RawMaterialIssuance.objects.create(
                        date=date_val,
                        receipt=None,  # No longer tied to a specific receipt
                        material_type=material_type,
                        num_bags_issued=num_bags_issued,
                        issued_to=issued_to_name,
                        issued_by=user,
                        notes=notes,
                        is_locked=True,
                    )
                    log_action(request, user, 'procurement', 'ISSUE_RAW',
                               f'Issued {num_bags_issued} bags of {material_type} to {issued_to_name}',
                               'RawMaterialIssuance', issuance.pk)
                    messages.success(request, f'Issuance #{issuance.pk} saved. {num_bags_issued} bags of {material_type} issued to {issued_to_name}. Remaining: {balance - num_bags_issued} bags.')
                    return redirect('procurement:list')
        except Exception as e:
            error = f'Error: {str(e)}'

    return render(request, 'procurement/issue_raw.html', {
        'current_user': user, 'receipts': receipts,
        'error': error, 'today': datetime.date.today().isoformat(),
        'balance_maize': balance_maize, 'balance_wheat': balance_wheat,
    })


@role_required('store_officer', 'manager', 'md')
@store_type_required('raw')
def list_records(request):
    user = get_current_user(request)
    if user.is_store_officer:
        receipts = RawMaterialReceipt.objects.filter(received_by=user).order_by('-date', '-created_at')
        issuances = RawMaterialIssuance.objects.filter(issued_by=user).order_by('-date', '-created_at')
    else:
        receipts = RawMaterialReceipt.objects.all().order_by('-date', '-created_at')
        issuances = RawMaterialIssuance.objects.all().order_by('-date', '-created_at')

    # Compute cleaning loss warnings
    loss_warnings = {}
    today = datetime.date.today()
    for mat in ['maize', 'wheat']:
        threshold = CleaningLossConfig.get_active_threshold(mat, today)
        if threshold is not None:
            loss_warnings[mat] = threshold

    return render(request, 'procurement/list.html', {
        'current_user': user, 'receipts': receipts, 'issuances': issuances,
        'balance_maize': _get_raw_store_balance('maize'),
        'balance_wheat': _get_raw_store_balance('wheat'),
        'loss_warnings': loss_warnings,
    })


@role_required('md')
def set_receipt_cost(request, receipt_id):
    """MD enters the purchase cost per bag for a raw material receipt."""
    user = get_current_user(request)
    receipt = get_object_or_404(RawMaterialReceipt, pk=receipt_id)

    if request.method == 'POST':
        try:
            cost_per_bag = float(request.POST.get('cost_per_bag', 0))
            if cost_per_bag <= 0:
                messages.error(request, 'Cost per bag must be greater than zero.')
                return redirect('procurement:set_cost', receipt_id=receipt_id)

            import django.utils.timezone as tz
            receipt.cost_per_bag = cost_per_bag
            receipt.total_cost = cost_per_bag * receipt.num_bags
            receipt.cost_status = 'approved'
            receipt.cost_approved_by = user
            receipt.cost_approved_at = tz.now()
            receipt.save()

            log_action(request, user, 'procurement', 'SET_COST',
                       f'Set cost ₦{cost_per_bag}/bag for Receipt #{receipt.pk} '
                       f'({receipt.material_type}) — Total ₦{receipt.total_cost:,.0f}',
                       'RawMaterialReceipt', receipt.pk)
            messages.success(request,
                             f'Cost set: ₦{cost_per_bag:,.0f}/bag × {receipt.num_bags} bags = '
                             f'₦{receipt.total_cost:,.0f} for Receipt #{receipt.pk}.')
            return redirect('procurement:list')
        except Exception as e:
            messages.error(request, f'Error: {e}')

    return render(request, 'procurement/set_cost.html', {
        'current_user': user,
        'receipt': receipt,
    })


@role_required('md')
def cleaning_loss_config(request):
    """MD views and adds cleaning loss thresholds per material type."""
    user = get_current_user(request)
    error = None

    if request.method == 'POST':
        try:
            material_type = request.POST.get('material_type')
            max_loss_pct = float(request.POST.get('max_loss_pct', 0))
            effective_from = request.POST.get('effective_from')
            notes = request.POST.get('notes', '').strip()

            if not material_type or max_loss_pct <= 0 or not effective_from:
                error = 'All fields are required and max loss % must be positive.'
            else:
                config = CleaningLossConfig.objects.create(
                    material_type=material_type,
                    max_loss_pct=max_loss_pct,
                    effective_from=effective_from,
                    created_by=user,
                    notes=notes,
                )
                log_action(request, user, 'procurement', 'SET_CLEANING_LOSS',
                           f'Set max cleaning loss {max_loss_pct}% for {material_type} from {effective_from}',
                           'CleaningLossConfig', config.pk)
                messages.success(request,
                                 f'Cleaning loss threshold saved: max {max_loss_pct}% for '
                                 f'{material_type.upper()} from {effective_from}.')
                return redirect('procurement:cleaning_loss')
        except Exception as e:
            error = f'Error: {e}'

    configs = CleaningLossConfig.objects.all().order_by('-effective_from')
    today = datetime.date.today()
    active = {
        mat: CleaningLossConfig.get_active_threshold(mat, today)
        for mat in ['maize', 'wheat']
    }

    return render(request, 'procurement/loss_config.html', {
        'current_user': user,
        'configs': configs,
        'active': active,
        'error': error,
        'today': today.isoformat(),
        'material_choices': [('maize', 'Maize'), ('wheat', 'Wheat')],
    })
