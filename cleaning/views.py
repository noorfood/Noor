from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from accounts.mixins import get_current_user, role_required
from accounts.models import User
from audit.utils import log_action
from cleaning.models import CleaningBatch, CleanRawReceipt
from procurement.models import RawMaterialIssuance
from django.db.models import Sum
import datetime


def _get_raw_issuance_balance(issuance):
    """Calculate remaining bags on a raw issuance: issued minus already used in batches."""
    used = CleaningBatch.objects.filter(raw_issuance=issuance).aggregate(t=Sum('dirty_bags_used'))['t'] or 0
    return issuance.num_bags_issued - used


@role_required('cleaning_manager', 'manager', 'md')
def dashboard(request):
    user = get_current_user(request)
    batches = CleaningBatch.objects.filter(cleaning_manager=user).order_by('-date', '-created_at')[:10] if user.is_cleaning_manager else CleaningBatch.objects.all().order_by('-date', '-created_at')[:20]
    return render(request, 'cleaning/dashboard.html', {'current_user': user, 'batches': batches})


@role_required('cleaning_manager')
def new_batch(request):
    user = get_current_user(request)
    # Available issuances for this user (filtering by strict text match for now)
    all_issuances = RawMaterialIssuance.objects.filter(issued_to=user.full_name).order_by('-date', '-created_at')
    
    # Filter only those with remaining balance
    issuances = []
    for iss in all_issuances:
        balance = _get_raw_issuance_balance(iss)
        if balance > 0:
            iss.remaining_balance = balance # inject for template
            issuances.append(iss)
            
    error = None

    if request.method == 'POST':
        try:
            date_val = request.POST.get('date')
            material_type = request.POST.get('material_type')
            issuance_id = request.POST.get('issuance_id', '')
            dirty_bags_used = int(request.POST.get('dirty_bags_used', 0))
            approx_dirty_weight_kg = float(request.POST.get('approx_dirty_weight_kg', 0))
            clean_bags_produced = int(request.POST.get('clean_bags_produced', 0))
            notes = request.POST.get('notes', '').strip()

            if not date_val or not material_type or dirty_bags_used <= 0 or clean_bags_produced <= 0 or not issuance_id:
                error = 'Please fill in all required fields, including the raw issuance link.'
            else:
                issuance = get_object_or_404(RawMaterialIssuance, pk=issuance_id)
                balance = _get_raw_issuance_balance(issuance)
                
                if dirty_bags_used > balance:
                    error = f'Insufficient issuance balance. Available: {balance} bags.'
                else:
                    batch = CleaningBatch(
                    date=date_val,
                    material_type=material_type,
                    cleaning_manager=user,
                    raw_issuance=issuance,
                    dirty_bags_used=dirty_bags_used,
                    approx_dirty_weight_kg=approx_dirty_weight_kg,
                    clean_bags_produced=clean_bags_produced,
                    notes=notes,
                    status='draft',
                )
                batch.save()  # auto-calculates loss_kg
                log_action(request, user, 'cleaning', 'NEW_BATCH',
                           f'New cleaning batch: {dirty_bags_used} dirty → {clean_bags_produced} clean bags',
                           'CleaningBatch', batch.pk)
                messages.success(request, f'Cleaning batch #{batch.pk} saved. Awaiting approval.')
                return redirect('cleaning:list')
        except Exception as e:
            error = f'Error: {str(e)}'

    return render(request, 'cleaning/new_batch.html', {
        'current_user': user, 'issuances': issuances,
        'error': error, 'today': datetime.date.today().isoformat(),
    })


@role_required('cleaning_manager', 'manager', 'md')
def list_batches(request):
    user = get_current_user(request)
    if user.is_cleaning_manager:
        batches = CleaningBatch.objects.filter(cleaning_manager=user).order_by('-date', '-created_at')
    else:
        batches = CleaningBatch.objects.all().order_by('-date', '-created_at')
    return render(request, 'cleaning/list.html', {'current_user': user, 'batches': batches})


@role_required('manager', 'md')
def approve_batch(request, batch_id):
    user = get_current_user(request)
    batch = get_object_or_404(CleaningBatch, pk=batch_id)

    if request.method == 'POST':
        import datetime as dt
        batch.status = 'approved'
        batch.approved_by = user
        batch.approved_at = dt.datetime.now()
        batch.is_locked = True
        batch.save()
        log_action(request, user, 'cleaning', 'APPROVE_BATCH',
                   f'Approved cleaning batch #{batch_id}', 'CleaningBatch', batch_id)
        messages.success(request, f'Batch #{batch_id} approved.')
        return redirect('cleaning:list')

    return render(request, 'cleaning/approve.html', {'current_user': user, 'batch': batch})
