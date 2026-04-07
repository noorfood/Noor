from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.db import models as db_models
from accounts.mixins import get_current_user, role_required, store_type_required
from accounts.models import User
from audit.utils import log_action
from clean_store.models import CleanRawIssuance, CleanRawReturn
from cleaning.models import CleanRawReceipt
from procurement.models import MATERIAL_CHOICES
import datetime


def _get_clean_store_balance(material_type):
    """Clean raw store balance = receipts - issuances + returns (per material type)."""
    receipts = CleanRawReceipt.objects.filter(material_type=material_type).aggregate(total=db_models.Sum('num_bags'))['total'] or 0
    issued = CleanRawIssuance.objects.filter(material_type=material_type).aggregate(total=db_models.Sum('num_bags'))['total'] or 0
    returned = CleanRawReturn.objects.filter(material_type=material_type, status='accepted').aggregate(total=db_models.Sum('num_bags'))['total'] or 0
    return receipts - issued + returned


@role_required('store_officer', 'manager', 'md')
@store_type_required('raw')
def dashboard(request):
    user = get_current_user(request)
    f_from = request.GET.get('date_from', '')
    f_to   = request.GET.get('date_to', '')
    
    from audit.models import AuditLog
    today = datetime.date.today()
    today_activities = AuditLog.objects.filter(user_id=user.pk, timestamp__date=today).order_by('-timestamp')
    
    # Calculate balances
    balance_maize = _get_clean_store_balance('maize')
    balance_wheat = _get_clean_store_balance('wheat')
    
    # Period activity if filtered
    m_receipts = CleanRawReceipt.objects.filter(material_type='maize')
    w_receipts = CleanRawReceipt.objects.filter(material_type='wheat')
    m_issues = CleanRawIssuance.objects.filter(material_type='maize')
    w_issues = CleanRawIssuance.objects.filter(material_type='wheat')
    
    if f_from:
        m_receipts = m_receipts.filter(date__gte=f_from)
        w_receipts = w_receipts.filter(date__gte=f_from)
        m_issues = m_issues.filter(date__gte=f_from)
        w_issues = w_issues.filter(date__gte=f_from)
    if f_to:
        m_receipts = m_receipts.filter(date__lte=f_to)
        w_receipts = w_receipts.filter(date__lte=f_to)
        m_issues = m_issues.filter(date__lte=f_to)
        w_issues = w_issues.filter(date__lte=f_to)

    p_rec_m = m_receipts.aggregate(t=db_models.Sum('num_bags'))['t'] or 0
    p_rec_w = w_receipts.aggregate(t=db_models.Sum('num_bags'))['t'] or 0
    p_iss_m = m_issues.aggregate(t=db_models.Sum('num_bags'))['t'] or 0
    p_iss_w = w_issues.aggregate(t=db_models.Sum('num_bags'))['t'] or 0

    recent_issuances = CleanRawIssuance.objects.order_by('-date', '-created_at')[:10]
    pending_returns = CleanRawReturn.objects.filter(status='pending').order_by('-date', '-created_at')
    
    return render(request, 'clean_store/dashboard.html', {
        'current_user': user,
        'balance_maize': balance_maize,
        'balance_wheat': balance_wheat,
        'p_rec_m': p_rec_m, 'p_rec_w': p_rec_w,
        'p_iss_m': p_iss_m, 'p_iss_w': p_iss_w,
        'recent_issuances': recent_issuances,
        'pending_returns': pending_returns,
        'today_activities': today_activities,
        'f_from': f_from, 'f_to': f_to,
        'today_str': today.isoformat(),
    })


@role_required('store_officer', 'manager', 'md')
@store_type_required('raw')
def receive_clean(request):
    """Receive clean bags into store from a cleaning process (handled by Store Officer)."""
    user = get_current_user(request)
    from procurement.models import RawMaterialIssuance
    from cleaning.models import CleanRawReceipt

    # Optional: Pre-select an issuance from list
    from django.shortcuts import get_object_or_404
    selected_issuance_id = request.GET.get('issuance')
    selected_issuance = None
    if selected_issuance_id:
        selected_issuance = get_object_or_404(RawMaterialIssuance, pk=selected_issuance_id)

    # Show ONLY active issuances part of an ongoing cleaning job
    all_raw_issuances = RawMaterialIssuance.objects.filter(is_fully_received=False).order_by('-date', '-created_at')
    
    # Enrich issuances with calculated balances (Expected Balance Matrix)
    pending_issuances = []
    for iss in all_raw_issuances:
        bags_already_received = CleanRawReceipt.objects.filter(raw_issuance=iss).aggregate(t=db_models.Sum('num_bags'))['t'] or 0
        iss.already_received = bags_already_received
        iss.outstanding = max(0, iss.num_bags_issued - bags_already_received)
        pending_issuances.append(iss)
    
    error = None

    if request.method == 'POST':
        try:
            date_val = request.POST.get('date')
            issuance_id = request.POST.get('issuance_id')
            clean_bags_produced = int(request.POST.get('clean_bags_produced', 0))
            approx_dirty_weight_kg = float(request.POST.get('approx_dirty_weight_kg', 0))
            is_final = request.POST.get('is_final') == 'on' # Checkbox: "Mark as Completed"
            notes = request.POST.get('notes', '').strip()

            if not date_val or not issuance_id or clean_bags_produced <= 0 or approx_dirty_weight_kg <= 0:
                error = 'Please fill in all required fields.'
            else:
                issuance = get_object_or_404(RawMaterialIssuance, pk=issuance_id)
                
                # Create the Clean Raw Receipt
                receipt = CleanRawReceipt.objects.create(
                    date=date_val,
                    raw_issuance=issuance,
                    approx_dirty_weight_kg=approx_dirty_weight_kg,
                    material_type=issuance.material_type,
                    num_bags=clean_bags_produced,
                    received_by=user,
                    notes=notes,
                    is_locked=True,
                )

                # If "Completed" checkbox was ticked, lock the issuance from further receipts
                if is_final:
                    issuance.is_fully_received = True
                    issuance.save()

                log_action(request, user, 'clean_store', 'RECEIVE_CLEAN',
                           f'Recorded cleaning results for Issuance #{issuance_id}: {clean_bags_produced} bags' + 
                           (' (Job Finalized)' if is_final else ' (Partial Reception)'),
                           'CleanRawReceipt', receipt.pk)
                
                messages.success(request, f'Clean bag receipt #{receipt.pk} saved. {clean_bags_produced} bags added to store.')
                return redirect('clean_store:list')
        except Exception as e:
            error = f'Error: {str(e)}'

    return render(request, 'clean_store/receive_clean.html', {
        'current_user': user, 
        'pending_issuances': pending_issuances,
        'selected_issuance': selected_issuance,
        'error': error, 
        'today': datetime.date.today().isoformat(),
        'balance_maize': _get_clean_store_balance('maize'),
        'balance_wheat': _get_clean_store_balance('wheat'),
    })


@role_required('store_officer', 'manager', 'md')
@store_type_required('raw')
def issue_clean(request):
    """Issue clean bags from store to a production officer."""
    user = get_current_user(request)
    prod_officers = User.objects.filter(role='production_officer', status='active')
    error = None

    if request.method == 'POST':
        try:
            date_val = request.POST.get('date')
            material_type = request.POST.get('material_type')
            num_bags = int(request.POST.get('num_bags', 0))
            issued_to_id = request.POST.get('issued_to_id')
            notes = request.POST.get('notes', '').strip()

            if not date_val or not material_type or num_bags <= 0 or not issued_to_id:
                error = 'All fields required.'
            else:
                # Check store balance
                balance = _get_clean_store_balance(material_type)
                if num_bags > balance:
                    error = f'Not enough stock. Current {material_type} balance: {balance} bags.'
                else:
                    issued_to = get_object_or_404(User, pk=issued_to_id, role='production_officer')
                    issuance = CleanRawIssuance.objects.create(
                        date=date_val,
                        material_type=material_type,
                        num_bags=num_bags,
                        issued_to=issued_to,
                        issued_by=user,
                        notes=notes,
                        is_locked=True,
                    )
                    log_action(request, user, 'clean_store', 'ISSUE_CLEAN',
                               f'Issued {num_bags} {material_type} bags to {issued_to.full_name}',
                               'CleanRawIssuance', issuance.pk)
                    messages.success(request, f'Issuance #{issuance.pk} saved. {num_bags} bags issued to {issued_to.full_name}.')
                    return redirect('clean_store:list')
        except Exception as e:
            error = f'Error: {str(e)}'

    return render(request, 'clean_store/issue_clean.html', {
        'current_user': user, 'prod_officers': prod_officers,
        'error': error, 'today': datetime.date.today().isoformat(),
        'material_choices': MATERIAL_CHOICES,
        'balance_maize': _get_clean_store_balance('maize'),
        'balance_wheat': _get_clean_store_balance('wheat'),
    })


@role_required('store_officer', 'manager', 'md')
@store_type_required('raw')
def acknowledge_return(request, return_id):
    """Receive Handshake acknowledgement for returned clean bags from production."""
    user = get_current_user(request)
    ret = get_object_or_404(CleanRawReturn, pk=return_id, status='pending')
    
    if request.method == 'POST':
        action = request.POST.get('action')
        note = request.POST.get('rejection_note', '').strip()

        if action == 'accept':
            ret.status = 'accepted'
            ret.received_by = user
            ret.save()
            log_action(request, user, 'clean_store', 'ACCEPT_RETURN', f'Accepted {ret.num_bags} {ret.material_type} bags from {ret.returned_by.full_name}', 'CleanRawReturn', ret.pk)
            messages.success(request, f'Return #{ret.pk} accepted. Stock added to store.')
        elif action == 'reject':
            if not note:
                messages.error(request, 'You must provide a reason for rejecting the return.')
                return redirect('clean_store:dashboard')
            ret.status = 'rejected'
            ret.rejection_note = note
            ret.received_by = user
            ret.save()
            log_action(request, user, 'clean_store', 'REJECT_RETURN', f'Rejected {ret.num_bags} {ret.material_type} returned bags. Note: {note}', 'CleanRawReturn', ret.pk)
            messages.warning(request, f'Return #{ret.pk} rejected. Stock bounces back to Production.')

    return redirect('clean_store:dashboard')


@role_required('store_officer', 'manager', 'md')
@store_type_required('raw')
def list_records(request):
    user = get_current_user(request)
    f_from = request.GET.get('date_from', '')
    f_to   = request.GET.get('date_to', '')
    
    issuances = CleanRawIssuance.objects.all()
    returns = CleanRawReturn.objects.all()
    receipts = CleanRawReceipt.objects.all()
    
    if f_from:
        issuances = issuances.filter(date__gte=f_from)
        returns = returns.filter(date__gte=f_from)
        receipts = receipts.filter(date__gte=f_from)
    if f_to:
        issuances = issuances.filter(date__lte=f_to)
        returns = returns.filter(date__lte=f_to)
        receipts = receipts.filter(date__lte=f_to)
        
    p_rec_m = receipts.filter(material_type='maize').aggregate(t=db_models.Sum('num_bags'))['t'] or 0
    p_rec_w = receipts.filter(material_type='wheat').aggregate(t=db_models.Sum('num_bags'))['t'] or 0
    p_iss_m = issuances.filter(material_type='maize').aggregate(t=db_models.Sum('num_bags'))['t'] or 0
    p_iss_w = issuances.filter(material_type='wheat').aggregate(t=db_models.Sum('num_bags'))['t'] or 0
    p_ret_m = returns.filter(material_type='maize', status='accepted').aggregate(t=db_models.Sum('num_bags'))['t'] or 0
    p_ret_w = returns.filter(material_type='wheat', status='accepted').aggregate(t=db_models.Sum('num_bags'))['t'] or 0

    if user.is_store_officer:
        issuances = issuances.filter(issued_by=user)
        returns = returns.filter(received_by=user)
    
    issuances = issuances.order_by('-date', '-created_at')
    returns = returns.order_by('-date', '-created_at')
    
    pending_returns = CleanRawReturn.objects.filter(status='pending').order_by('-date', '-created_at')
    
    return render(request, 'clean_store/list.html', {
        'current_user': user, 'issuances': issuances, 'returns': returns,
        'balance_maize': _get_clean_store_balance('maize'),
        'balance_wheat': _get_clean_store_balance('wheat'),
        'p_rec_m': p_rec_m, 'p_rec_w': p_rec_w,
        'p_iss_m': p_iss_m, 'p_iss_w': p_iss_w,
        'p_ret_m': p_ret_m, 'p_ret_w': p_ret_w,
        'pending_returns': pending_returns,
        'f_from': f_from, 'f_to': f_to,
        'today_str': datetime.date.today().isoformat(),
    })
