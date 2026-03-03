from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from accounts.mixins import get_current_user, role_required
from accounts.models import User
from audit.utils import log_action
from production.models import MillingBatch, PackagingBatch, ProductionThreshold
from clean_store.models import CleanRawIssuance, CleanRawReturn
from django.db.models import Sum
import datetime

def get_production_balance(user, material_type):
    accepted = CleanRawIssuance.objects.filter(issued_to=user, status='accepted', material_type=material_type).aggregate(t=Sum('num_bags'))['t'] or 0
    milled_new = MillingBatch.objects.filter(production_officer=user, material_type=material_type).aggregate(t=Sum('bags_milled_new'))['t'] or 0
    milled_old = MillingBatch.objects.filter(production_officer=user, material_type=material_type).aggregate(t=Sum('outstanding_bags_milled'))['t'] or 0
    returned = CleanRawReturn.objects.filter(returned_by=user, status__in=['pending', 'accepted'], material_type=material_type).aggregate(t=Sum('num_bags'))['t'] or 0
    return max(0, accepted - milled_new - milled_old - returned)

def _get_milling_powder_balance(milling_batch):
    """Calculate remaining bulk powder kg on a milling batch: produced minus packaged."""
    used = PackagingBatch.objects.filter(milling_batch=milling_batch).aggregate(t=Sum('powder_used_kg'))['t'] or 0
    return float(milling_batch.bulk_powder_kg) - float(used)

def get_powder_balance(user, material_type):
    """Ledger: total bulk powder in hand = total milled kg - total packaged kg (per user per material)."""
    milled = MillingBatch.objects.filter(production_officer=user, material_type=material_type).aggregate(t=Sum('bulk_powder_kg'))['t'] or 0
    packaged = PackagingBatch.objects.filter(production_officer=user, material_type=material_type).aggregate(t=Sum('powder_used_kg'))['t'] or 0
    return max(0.0, float(milled) - float(packaged))


@role_required('production_officer', 'manager', 'md')
def dashboard(request):
    user = get_current_user(request)
    pending_transfers = []
    today = datetime.date.today()
    
    # Dashboard metrics for Production Officer
    today_milled_bags = 0
    today_packaged_sacks = 0
    all_user_stats = []
    
    if user.is_production_officer:
        pending_transfers = CleanRawIssuance.objects.filter(issued_to=user, status='pending').order_by('-date')
        milling_batches = MillingBatch.objects.filter(production_officer=user).order_by('-date', '-created_at')[:10]
        packaging_batches = PackagingBatch.objects.filter(production_officer=user).order_by('-date', '-created_at')[:10]
        
        balance_maize = get_production_balance(user, 'maize')
        balance_wheat = get_production_balance(user, 'wheat')
        powder_maize = get_powder_balance(user, 'maize')
        powder_wheat = get_powder_balance(user, 'wheat')
        outstanding_total = balance_maize + balance_wheat

        # Daily performance
        today_milled = MillingBatch.objects.filter(production_officer=user, date=today).aggregate(
            bags=Sum('bags_milled_new') + Sum('outstanding_bags_milled')
        )
        today_milled_bags = today_milled['bags'] or 0
        
        today_packaged = PackagingBatch.objects.filter(production_officer=user, date=today).aggregate(
            sacks=Sum('qty_10kg')
        )
        today_packaged_sacks = today_packaged['sacks'] or 0
    else:
        milling_batches = MillingBatch.objects.all().order_by('-date', '-created_at')[:10]
        packaging_batches = PackagingBatch.objects.all().order_by('-date', '-created_at')[:10]
        outstanding_total = None
        balance_maize = balance_wheat = powder_maize = powder_wheat = None

        # For MD/Manager: compute per-user totals
        prod_users = User.objects.filter(role='production_officer', status='active')
        for u in prod_users:
            bm = get_production_balance(u, 'maize')
            bw = get_production_balance(u, 'wheat')
            pm = get_powder_balance(u, 'maize')
            pw = get_powder_balance(u, 'wheat')
            
            # Add today's performance for manager view
            tm = MillingBatch.objects.filter(production_officer=u, date=today).aggregate(
                b=Sum('bags_milled_new') + Sum('outstanding_bags_milled')
            )['b'] or 0
            tp = PackagingBatch.objects.filter(production_officer=u, date=today).aggregate(s=Sum('qty_10kg'))['s'] or 0
            
            if bm > 0 or bw > 0 or pm > 0 or pw > 0 or tm > 0 or tp > 0:
                all_user_stats.append({
                    'user': u, 
                    'bags_maize': bm, 'bags_wheat': bw, 
                    'powder_maize': pm, 'powder_wheat': pw,
                    'today_milled': tm, 'today_packaged': tp
                })
        
    return render(request, 'production/dashboard.html', {
        'current_user': user, 'milling_batches': milling_batches, 'packaging_batches': packaging_batches, 
        'outstanding_total': outstanding_total, 'pending_transfers': pending_transfers,
        'balance_maize': balance_maize, 'balance_wheat': balance_wheat,
        'powder_maize': powder_maize, 'powder_wheat': powder_wheat,
        'today_milled_bags': today_milled_bags,
        'today_packaged_sacks': today_packaged_sacks,
        'all_user_stats': all_user_stats if not user.is_production_officer else None,
    })


@role_required('production_officer')
def record_milling(request):
    user = get_current_user(request)
    balance_maize = get_production_balance(user, 'maize')
    balance_wheat = get_production_balance(user, 'wheat')
    error = None

    if request.method == 'POST':
        try:
            date_val = request.POST.get('date')
            shift = request.POST.get('shift')
            material_type = request.POST.get('material_type')
            machine = request.POST.get('machine', '').strip()
            bags_milled_new = int(request.POST.get('bags_milled_new', 0))
            outstanding_bags_milled = int(request.POST.get('outstanding_bags_milled', 0))
            bulk_powder_kg = float(request.POST.get('bulk_powder_kg') or 0.0)
            notes = request.POST.get('notes', '').strip()

            total_bags = bags_milled_new + outstanding_bags_milled

            if not date_val or not shift or not material_type or total_bags <= 0:
                error = 'Please fill in date, shift, material type, and at least 1 bag milled.'
            elif bulk_powder_kg == 0:
                error = 'Please enter the bulk powder kg produced.'
            else:
                current_balance = balance_maize if material_type == 'maize' else balance_wheat
                if total_bags > current_balance:
                    error = f'Insufficient balance for {material_type}. Available: {current_balance} bags.'
                else:
                    batch = MillingBatch(
                        date=date_val,
                        shift=shift,
                        material_type=material_type,
                        machine=machine,
                        production_officer=user,
                        bags_milled_new=bags_milled_new,
                        outstanding_bags_milled=outstanding_bags_milled,
                        bulk_powder_kg=bulk_powder_kg,
                        notes=notes,
                        is_locked=True,
                    )
                    batch.save()
                    log_action(request, user, 'production', 'RECORD_MILLING',
                               f'Milling: {total_bags} bags milled | Powder: {bulk_powder_kg}kg',
                               'MillingBatch', batch.pk)
                    messages.success(request, f'Milling Batch #{batch.pk} saved. {total_bags} bags processed.')
                    return redirect('production:list')
        except Exception as e:
            error = f'Error: {str(e)}'

    return render(request, 'production/record_milling.html', {
        'current_user': user, 'balance_maize': balance_maize, 'balance_wheat': balance_wheat,
        'error': error, 'today': datetime.date.today().isoformat(),
    })


@role_required('production_officer')
def record_packaging(request):
    user = get_current_user(request)
    powder_maize = get_powder_balance(user, 'maize')
    powder_wheat = get_powder_balance(user, 'wheat')
    error = None

    if request.method == 'POST':
        try:
            date_val = request.POST.get('date')
            shift = request.POST.get('shift')
            material_type = request.POST.get('material_type')
            powder_used_kg = float(request.POST.get('powder_used_kg', 0.0))
            qty_10kg = int(request.POST.get('qty_10kg', 0))
            notes = request.POST.get('notes', '').strip()

            if not date_val or not shift or not material_type or powder_used_kg <= 0:
                error = 'Please fill in all required fields.'
            elif qty_10kg <= 0:
                error = 'Number of sacks packaged must be at least 1.'
            else:
                current_powder = powder_maize if material_type == 'maize' else powder_wheat
                if powder_used_kg > current_powder:
                    error = f'Insufficient powder. You have {current_powder:.2f}kg of {material_type} powder available.'
                else:
                    # Link to most recent milling batch for this user/material (for traceability)
                    last_milling = MillingBatch.objects.filter(
                        production_officer=user, material_type=material_type
                    ).order_by('-date', '-created_at').first()

                    batch = PackagingBatch(
                        date=date_val,
                        shift=shift,
                        material_type=material_type,
                        production_officer=user,
                        milling_batch=last_milling,
                        powder_used_kg=powder_used_kg,
                        qty_10kg=qty_10kg,
                        notes=notes,
                        is_locked=True,
                    )
                    batch.save()

                    # ── AUTO-CREATE PENDING FG RECEIPT (ledger-based handshake) ──
                    from finished_store.models import FinishedGoodsReceipt
                    fg_receipt = FinishedGoodsReceipt.objects.create(
                        date=date_val,
                        packaging_ref=f'Packaging Batch #{batch.pk}',
                        material_type=material_type,
                        product_size='10kg',
                        qty_received=qty_10kg,
                        submitted_by=user,
                        status='pending',
                        notes=notes,
                        is_locked=True,
                    )
                    # ─────────────────────────────────────────────────────────

                    log_action(request, user, 'production', 'RECORD_PACKAGING',
                               f'Packaging: Used {powder_used_kg}kg | {qty_10kg} sacks → FG Receipt #{fg_receipt.pk} pending',
                               'PackagingBatch', batch.pk)
                    messages.success(request, f'Packaging Batch #{batch.pk} saved. {qty_10kg} sacks submitted to FG Store for acknowledgment.')
                    return redirect('production:list')
        except Exception as e:
            error = f'Error: {str(e)}'

    return render(request, 'production/record_packaging.html', {
        'current_user': user, 'powder_maize': powder_maize, 'powder_wheat': powder_wheat,
        'error': error, 'today': datetime.date.today().isoformat(),
    })


@role_required('production_officer', 'manager', 'md')
def list_batches(request):
    user = get_current_user(request)
    f_from = request.GET.get('date_from', '')
    f_to = request.GET.get('date_to', '')
    f_material = request.GET.get('material', '')
    f_flag = request.GET.get('flag', '')

    if user.is_production_officer:
        milling_batches = MillingBatch.objects.filter(production_officer=user).order_by('-date', '-created_at')
        packaging_batches = PackagingBatch.objects.filter(production_officer=user).order_by('-date', '-created_at')
    else:
        milling_batches = MillingBatch.objects.all().order_by('-date', '-created_at')
        packaging_batches = PackagingBatch.objects.all().order_by('-date', '-created_at')
        # Apply filters for MD/Manager
        if f_from:
            milling_batches = milling_batches.filter(date__gte=f_from)
            packaging_batches = packaging_batches.filter(date__gte=f_from)
        if f_to:
            milling_batches = milling_batches.filter(date__lte=f_to)
            packaging_batches = packaging_batches.filter(date__lte=f_to)
        if f_material:
            milling_batches = milling_batches.filter(material_type=f_material)
            packaging_batches = packaging_batches.filter(material_type=f_material)
        if f_flag:
            milling_batches = milling_batches.filter(flag_level=f_flag)

    return render(request, 'production/list.html', {
        'current_user': user,
        'milling_batches': milling_batches,
        'packaging_batches': packaging_batches,
        'f_from': f_from, 'f_to': f_to, 'f_material': f_material, 'f_flag': f_flag,
    })


@role_required('production_officer', 'manager', 'md')
def outstanding_view(request):
    user = get_current_user(request)
    if user.is_production_officer:
        balance_maize = get_production_balance(user, 'maize')
        balance_wheat = get_production_balance(user, 'wheat')
        pending_transfers = CleanRawIssuance.objects.filter(issued_to=user, status='pending').order_by('-date')
        return render(request, 'production/outstanding.html', {
            'current_user': user, 
            'balance_maize': balance_maize, 
            'balance_wheat': balance_wheat,
            'pending_transfers': pending_transfers,
        })
    else:
        # MD / Manager view
        prod_users = User.objects.filter(role='production_officer', status='active')
        user_balances = []
        for u in prod_users:
            m = get_production_balance(u, 'maize')
            w = get_production_balance(u, 'wheat')
            if m > 0 or w > 0:
                user_balances.append({'user': u, 'maize': m, 'wheat': w})
        
        return render(request, 'production/outstanding.html', {
            'current_user': user, 'user_balances': user_balances,
        })


@role_required('md')
def manage_thresholds(request):
    user = get_current_user(request)
    thresholds = ProductionThreshold.objects.all().order_by('-effective_from')
    error = None

    if request.method == 'POST':
        try:
            material_type = request.POST.get('material_type')
            normal_max = float(request.POST.get('normal_max_loss_pct', 13))
            warning_max = float(request.POST.get('warning_max_loss_pct', 18))
            expected = float(request.POST.get('expected_loss_pct', 20))
            effective_from = request.POST.get('effective_from')
            notes = request.POST.get('notes', '').strip()

            if normal_max >= warning_max:
                error = 'Normal max must be less than warning max.'
            else:
                t = ProductionThreshold.objects.create(
                    material_type=material_type,
                    normal_max_loss_pct=normal_max,
                    warning_max_loss_pct=warning_max,
                    expected_loss_pct=expected,
                    effective_from=effective_from,
                    created_by=user,
                    notes=notes,
                )
                log_action(request, user, 'production', 'SET_THRESHOLD',
                           f'New threshold for {material_type}: normal<={normal_max}%, warn<={warning_max}%',
                           'ProductionThreshold', t.pk)
                messages.success(request, f'New threshold set for {material_type} from {effective_from}.')
                return redirect('production:thresholds')
        except Exception as e:
            error = f'Error: {str(e)}'

    return render(request, 'production/thresholds.html', {
        'current_user': user, 'thresholds': thresholds,
        'error': error, 'today': datetime.date.today().isoformat(),
    })

@role_required('production_officer')
def initiate_return(request):
    user = get_current_user(request)
    balance_maize = get_production_balance(user, 'maize')
    balance_wheat = get_production_balance(user, 'wheat')
    error = None

    if request.method == 'POST':
        try:
            date_val = request.POST.get('date')
            material_type = request.POST.get('material_type')
            num_bags = int(request.POST.get('num_bags', 0))
            notes = request.POST.get('notes', '').strip()

            if not date_val or not material_type or num_bags <= 0:
                error = 'Date, material type, and at least 1 bag are required.'
            else:
                current_balance = balance_maize if material_type == 'maize' else balance_wheat
                if num_bags > current_balance:
                    error = f'Cannot return {num_bags} bags. You only have {current_balance} {material_type} bags available.'
                else:
                    ret = CleanRawReturn.objects.create(
                        date=date_val,
                        material_type=material_type,
                        num_bags=num_bags,
                        returned_by=user,
                        notes=notes,
                        status='pending',
                        is_locked=True
                    )
                    log_action(request, user, 'production', 'INITIATE_RETURN', f'Initiated return of {num_bags} {material_type} bags to store', 'CleanRawReturn', ret.pk)
                    messages.success(request, f'Return logged. {num_bags} bags are marked as Pending for the store to acknowledge.')
                    return redirect('production:outstanding')
        except Exception as e:
            error = f'Error: {str(e)}'

    return render(request, 'production/return_to_store.html', {
        'current_user': user, 'balance_maize': balance_maize, 'balance_wheat': balance_wheat,
        'error': error, 'today': datetime.date.today().isoformat(),
    })

@role_required('production_officer')
def acknowledge_transfer(request, issuance_id):
    user = get_current_user(request)
    issuance = get_object_or_404(CleanRawIssuance, pk=issuance_id, issued_to=user, status='pending')
    
    if request.method == 'POST':
        action = request.POST.get('action') # 'accept' or 'reject'
        note = request.POST.get('rejection_note', '').strip()

        if action == 'accept':
            issuance.status = 'accepted'
            issuance.save()
            log_action(request, user, 'production', 'ACCEPT_TRANSFER', f'Accepted {issuance.num_bags} bags of {issuance.material_type}', 'CleanRawIssuance', issuance.pk)
            messages.success(request, f'Transfer #{issuance.pk} accepted. Bags added to your balance.')
        elif action == 'reject':
            if not note:
                messages.error(request, 'You must provide a reason for rejecting the transfer.')
                return redirect('production:dashboard')
            issuance.status = 'rejected'
            issuance.rejection_note = note
            issuance.save()
            log_action(request, user, 'production', 'REJECT_TRANSFER', f'Rejected {issuance.num_bags} bags. Reason: {note}', 'CleanRawIssuance', issuance.pk)
            messages.warning(request, f'Transfer #{issuance.pk} rejected. Bags returned to store.')
    
    return redirect('production:dashboard')
