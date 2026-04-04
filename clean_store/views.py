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
    
    from audit.models import AuditLog
    import datetime
    today_activities = AuditLog.objects.filter(user_id=user.pk, timestamp__date=datetime.date.today()).order_by('-timestamp')
    
    balance_maize = _get_clean_store_balance('maize')
    balance_wheat = _get_clean_store_balance('wheat')
    recent_issuances = CleanRawIssuance.objects.order_by('-date', '-created_at')[:10]
    pending_returns = CleanRawReturn.objects.filter(status='pending').order_by('-date', '-created_at')
    return render(request, 'clean_store/dashboard.html', {
        'current_user': user,
        'balance_maize': balance_maize,
        'balance_wheat': balance_wheat,
        'recent_issuances': recent_issuances,
        'pending_returns': pending_returns,
        'today_activities': today_activities,
    })


@role_required('store_officer', 'manager', 'md')
@store_type_required('raw')
def receive_clean(request):
    """Receive clean bags into store from a cleaning process (handled by Store Officer)."""
    user = get_current_user(request)
    from procurement.models import RawMaterialIssuance
    from cleaning.models import CleanRawReceipt

    # Show issuances that have not been fully accounted for in receipts
    all_raw_issuances = RawMaterialIssuance.objects.order_by('-date', '-created_at')
    pending_issuances = [iss for iss in all_raw_issuances if not CleanRawReceipt.objects.filter(raw_issuance=iss).exists()]
    
    error = None

    if request.method == 'POST':
        try:
            date_val = request.POST.get('date')
            issuance_id = request.POST.get('issuance_id')
            clean_bags_produced = int(request.POST.get('clean_bags_produced', 0))
            approx_dirty_weight_kg = float(request.POST.get('approx_dirty_weight_kg', 0))
            notes = request.POST.get('notes', '').strip()

            if not date_val or not issuance_id or clean_bags_produced <= 0 or approx_dirty_weight_kg <= 0:
                error = 'Please fill in all required fields.'
            else:
                issuance = get_object_or_404(RawMaterialIssuance, pk=issuance_id)
                
                # Create the Clean Raw Receipt directly linked to issuance
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

                log_action(request, user, 'clean_store', 'RECEIVE_CLEAN',
                           f'Recorded cleaning results for Issuance #{issuance_id}: {clean_bags_produced} bags',
                           'CleanRawReceipt', receipt.pk)
                
                messages.success(request, f'Clean bag receipt #{receipt.pk} saved. {clean_bags_produced} bags added to store.')
                return redirect('clean_store:list')
        except Exception as e:
            error = f'Error: {str(e)}'

    return render(request, 'clean_store/receive_clean.html', {
        'current_user': user, 
        'pending_issuances': pending_issuances,
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
    if user.is_store_officer:
        issuances = CleanRawIssuance.objects.filter(issued_by=user).order_by('-date', '-created_at')
        returns = CleanRawReturn.objects.filter(received_by=user).order_by('-date', '-created_at')
    else:
        issuances = CleanRawIssuance.objects.all().order_by('-date', '-created_at')
        returns = CleanRawReturn.objects.all().order_by('-date', '-created_at')
    
    pending_returns = CleanRawReturn.objects.filter(status='pending').order_by('-date', '-created_at')
    
    return render(request, 'clean_store/list.html', {
        'current_user': user, 'issuances': issuances, 'returns': returns,
        'balance_maize': _get_clean_store_balance('maize'),
        'balance_wheat': _get_clean_store_balance('wheat'),
        'pending_returns': pending_returns,
    })
