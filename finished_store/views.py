from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from accounts.mixins import get_current_user, role_required, store_type_required
from accounts.models import User
from audit.utils import log_action
from finished_store.models import FinishedGoodsReceipt, FinishedGoodsIssuance, PRODUCT_SIZE_CHOICES
from django.db.models import Sum
import datetime


def _fg_balance(material_type, product_size):
    from finished_store.models import FinishedGoodsReturn
    # Only count ACCEPTED receipts toward the balance (pending receipts not yet acknowledged)
    received = FinishedGoodsReceipt.objects.filter(material_type=material_type, product_size=product_size, status='accepted').aggregate(t=Sum('qty_received'))['t'] or 0
    issued   = FinishedGoodsIssuance.objects.filter(material_type=material_type, product_size=product_size, status='accepted').aggregate(t=Sum('qty_issued'))['t'] or 0
    returned = FinishedGoodsReturn.objects.filter(material_type=material_type, product_size=product_size, status='accepted').aggregate(t=Sum('qty_returned'))['t'] or 0
    return received - issued + returned


@role_required('store_officer', 'md')
@store_type_required('finished')
def dashboard(request):
    from procurement.models import MATERIAL_CHOICES
    from sales.models import SalesManagerCollection
    user = get_current_user(request)
    today = datetime.date.today()

    balances = {}
    for mat_val, mat_label in MATERIAL_CHOICES:
        for size_val, size_label in PRODUCT_SIZE_CHOICES:
            bal = _fg_balance(mat_val, size_val)
            if bal > 0 or size_val == '10kg':
                balances[f"{mat_val}|{size_val}"] = {
                    'material_label': mat_label.upper(),
                    'size_label': size_label,
                    'qty': bal,
                    'material_val': mat_val
                }

    # Dashboard Metrics
    pending_collections = SalesManagerCollection.objects.filter(status='pending').order_by('-date', '-created_at')
    pending_receipts = FinishedGoodsReceipt.objects.filter(status='pending').order_by('-date', '-created_at')
    
    receipts_today = FinishedGoodsReceipt.objects.filter(date=today, status='accepted').count()
    issuances_today = SalesManagerCollection.objects.filter(date=today, status='accepted').count()

    # Real-world handshake: Goods issued to Company channel but not yet GM-acknowledged
    pending_company_issuances = FinishedGoodsIssuance.objects.filter(channel='company', status='pending').order_by('-date', '-created_at')

    return render(request, 'finished_store/dashboard.html', {
        'current_user': user,
        'balances': balances,
        'pending_collections': pending_collections,
        'pending_receipts': pending_receipts,
        'pending_company_issuances': pending_company_issuances,
        'receipts_today_count': receipts_today,
        'issuances_today_count': issuances_today,
    })


@role_required('store_officer', 'md')
@store_type_required('finished')
def acknowledge_receipt(request, receipt_id):
    """FG Store Officer accepts or rejects a pending FG Receipt submitted by Production."""
    user = get_current_user(request)
    receipt = get_object_or_404(FinishedGoodsReceipt, pk=receipt_id, status='pending')

    if request.method == 'POST':
        action = request.POST.get('action')
        note   = request.POST.get('rejection_note', '').strip()

        if action == 'accept':
            receipt.status      = 'accepted'
            receipt.received_by = user
            receipt.save()
            log_action(request, user, 'finished_store', 'ACCEPT_RECEIPT',
                       f'Accepted FG Receipt #{receipt.pk}: {receipt.qty_received} × {receipt.product_size} | {receipt.packaging_ref}',
                       'FinishedGoodsReceipt', receipt.pk)
            messages.success(request, f'Receipt #{receipt.pk} accepted. {receipt.qty_received} × {receipt.product_size} added to store.')

        elif action == 'reject':
            if not note:
                messages.error(request, 'Please provide a rejection reason.')
                return redirect('finished_store:list')
            receipt.status         = 'rejected'
            receipt.received_by    = user
            receipt.rejection_note = note
            receipt.save()
            log_action(request, user, 'finished_store', 'REJECT_RECEIPT',
                       f'Rejected FG Receipt #{receipt.pk}: {note}',
                       'FinishedGoodsReceipt', receipt.pk)
            messages.warning(request, f'Receipt #{receipt.pk} rejected. Production Officer will be notified.')

    return redirect('finished_store:list')


@role_required('store_officer')
@store_type_required('finished')
def issue_fg(request):
    """FG issuance for company-channel only. Requires management handshake."""
    user = get_current_user(request)
    error = None

    if request.method == 'POST':
        try:
            date_val = request.POST.get('date')
            material_type = request.POST.get('material_type', 'maize')
            product_size = '10kg'
            qty_issued = int(request.POST.get('qty_issued', 0))
            buyer_name = request.POST.get('buyer_name', '').strip()
            approver_id = request.POST.get('approver_id')
            notes = request.POST.get('notes', '').strip()

            if not date_val or qty_issued <= 0 or not buyer_name or not approver_id:
                error = 'All fields required (Date, Quantity, Buyer Name, Approver).'
            else:
                balance = _fg_balance(material_type, product_size)
                if qty_issued > balance:
                    error = f'Insufficient stock. Current {material_type.upper()} {product_size} balance: {balance} units.'
                else:
                    approver = get_object_or_404(User, pk=approver_id)
                    issuance = FinishedGoodsIssuance.objects.create(
                        date=date_val,
                        material_type=material_type,
                        product_size=product_size,
                        qty_issued=qty_issued,
                        channel='company',
                        buyer_name=buyer_name,
                        approver=approver,
                        issued_by=user,
                        notes=notes,
                        status='pending', # New: Always pending until Handshake
                        is_locked=False,  # Unlock so GM can edit if needed
                    )
                    log_action(request, user, 'finished_store', 'INITIATE_ISSUE_FG',
                               f'Initiated issuance of {qty_issued} × {product_size} to Company | Handshake Pending',
                               'FinishedGoodsIssuance', issuance.pk)
                    messages.info(request, f'Company Handover #{issuance.pk} initiated. Awaiting approval from {approver.full_name}.')
                    return redirect('finished_store:list')
        except Exception as e:
            error = f'Error: {str(e)}'

    from procurement.models import MATERIAL_CHOICES
    
    approvers = User.objects.filter(role__in=['manager', 'md'], status='active')
    
    return render(request, 'finished_store/issue_fg.html', {
        'current_user': user, 'error': error,
        'today': datetime.date.today().isoformat(), 'size_choices': PRODUCT_SIZE_CHOICES,
        'material_choices': MATERIAL_CHOICES, 'approvers': approvers,
    })


@role_required('store_officer', 'md')
@store_type_required('finished')
def create_sm_collection(request):
    """
    FG Store Officer records goods collected by the Sales Manager.
    Creates a PENDING SalesManagerCollection record.
    The Sales Manager must then acknowledge (accept or reject).

    COMPANY TRUTH: Once accepted, the SM is fully responsible for those goods.
    """
    from sales.models import SalesManagerCollection
    from accounts.models import User
    from pricing.models import PriceConfig
    from procurement.models import MATERIAL_CHOICES

    user = get_current_user(request)
    error = None
    today = datetime.date.today().isoformat()

    sales_managers = User.objects.filter(role='sales_manager', status='active')

    if request.method == 'POST':
        try:
            date_val = datetime.date.fromisoformat(request.POST.get('date'))
            sm_id = request.POST.get('sales_manager_id')
            material_type = request.POST.get('material_type', 'maize')
            qty_sacks = int(request.POST.get('qty_sacks', 0))
            notes = request.POST.get('notes', '').strip()

            if not sm_id or qty_sacks <= 0:
                error = 'Sales Manager and quantity are required.'
            else:
                balance = _fg_balance(material_type, '10kg')
                if qty_sacks > balance:
                    error = (f'Insufficient stock. Current {material_type.upper()} 10kg balance: '
                             f'{balance} sacks. Requested: {qty_sacks}.')
                else:
                    sm = get_object_or_404(User, pk=sm_id, role='sales_manager')

                    # Lookup price from MD config
                    price = PriceConfig.get_active_price('sales_manager', material_type, '10kg', date_val)

                    collection = SalesManagerCollection.objects.create(
                        date=date_val,
                        material_type=material_type,
                        qty_sacks=qty_sacks,
                        store_officer=user,
                        sales_manager=sm,
                        price_per_sack=price or 0,
                        notes=notes,
                        status='pending',
                        is_locked=True,
                    )

                    # Create linked FG Issuance record (also pending — only counts when collection accepted)
                    FinishedGoodsIssuance.objects.create(
                        date=date_val,
                        material_type=material_type,
                        product_size='10kg',
                        qty_issued=qty_sacks,
                        channel='sales_manager',
                        issued_by=user,
                        sm_collection=collection,
                        notes=f'SM Collection #{collection.pk} — pending SM acknowledgement',
                        status='pending',
                        is_locked=True,
                    )

                    log_action(
                        request, user, 'finished_store', 'CREATE_SM_COLLECTION',
                        f'Store recorded {qty_sacks} × {material_type} sacks for '
                        f'{sm.full_name} | Pending SM acknowledgement',
                        'SalesManagerCollection', collection.pk
                    )
                    messages.success(
                        request,
                        f'Collection #{collection.pk} recorded for {sm.full_name}. '
                        f'{qty_sacks} {material_type.upper()} sacks — awaiting SM acknowledgement.'
                        + (f' Price: ₦{price:,.0f}/sack (Total ₦{float(price) * qty_sacks:,.0f})' if price else
                           ' (No price configured — please ask MD to set a price for sales_manager channel.)')
                    )
                    return redirect('finished_store:list')

        except Exception as e:
            error = f'Error: {str(e)}'

    return render(request, 'finished_store/collect_for_sm.html', {
        'current_user': user,
        'error': error,
        'today': today,
        'sales_managers': sales_managers,
        'material_choices': MATERIAL_CHOICES,
        'balances': {
            mat: _fg_balance(mat, '10kg')
            for mat in ['maize', 'wheat']
        },
    })


@role_required('store_officer', 'md')
@store_type_required('finished')
def acknowledge_return(request, return_id):
    from finished_store.models import FinishedGoodsReturn
    user = get_current_user(request)
    ret = get_object_or_404(FinishedGoodsReturn, pk=return_id, status='pending')
    
    if request.method == 'POST':
        action = request.POST.get('action')
        note = request.POST.get('rejection_note', '').strip()

        if action == 'accept':
            ret.status = 'accepted'
            ret.received_by = user
            ret.save()
            log_action(request, user, 'finished_store', 'ACCEPT_RETURN', f'Accepted {ret.qty_returned} {ret.product_size} sacks from {ret.returned_by.full_name}', 'FinishedGoodsReturn', ret.pk)
            messages.success(request, f'Return #{ret.pk} accepted. Stock added to Finished Goods store.')
        elif action == 'reject':
            if not note:
                messages.error(request, 'You must provide a reason for rejecting the return.')
                return redirect('finished_store:list')
            ret.status = 'rejected'
            ret.rejection_note = note
            ret.received_by = user
            ret.save()
            log_action(request, user, 'finished_store', 'REJECT_RETURN', f'Rejected {ret.qty_returned} {ret.product_size} sacks. Note: {note}', 'FinishedGoodsReturn', ret.pk)
            messages.warning(request, f'Return #{ret.pk} rejected. Sacks bounce back to Sales.')

    return redirect('finished_store:list')


@role_required('store_officer', 'md')
@store_type_required('finished')
def acknowledge_issuance(request, issuance_id):
    """
    FG Officer or Manager clicks Issue Goods on a pending sale/company issuance.
    For CHANNEL=COMPANY, only management (manager/md) can accept.
    """
    user = get_current_user(request)
    issuance = get_object_or_404(FinishedGoodsIssuance, pk=issuance_id, status='pending')
    
    if request.method == 'POST':
        action = request.POST.get('action')
        
        if action == 'accept':
            # Check permission for Company Handshake
            if issuance.channel == 'company':
                if issuance.approver and user != issuance.approver:
                    messages.error(request, f'Only the designated approver ({issuance.approver.full_name}) can authorize this Company Handover.')
                    return redirect('finished_store:list')
                elif not issuance.approver and user.role != 'md':
                    messages.error(request, 'Only the Managing Director can authorize Company Handovers.')
                    return redirect('finished_store:list')

            issuance.status = 'accepted'
            # Sync the SalesRecord status based on handed-over goods
            if issuance.sales_record:
                sale = issuance.sales_record
                if sale.is_fully_paid:
                    sale.status = 'paid'
                elif sale.total_paid > 0:
                    sale.status = 'partial'
                else:
                    sale.status = 'issued'
                sale.save(update_fields=['status'])
            elif issuance.channel == 'company' and issuance.product_size == '10kg' and \
                 ("Open" in issuance.notes or "retail" in issuance.notes.lower()):
                # This is an Open Sack auto-request from the OM for piece retail
                from sales.models import CompanyRetailLedger
                CompanyRetailLedger.objects.create(
                    date=issuance.date,
                    material_type=issuance.material_type,
                    action='open_sack',
                    pieces_changed=issuance.qty_issued * 10,
                    recorded_by=user,
                    notes=f"Auto-credit from opening {issuance.qty_issued} sacks (Issuance #{issuance.pk})"
                )
            
            issuance.issued_by = user  # Update to the actual physical issuer
            issuance.save()
            log_action(
                request, user, 'finished_store', 'ACCEPT_ISSUANCE', 
                f'Issued {issuance.qty_issued} {issuance.product_size} (Sale #{issuance.sales_record_id})', 
                'FinishedGoodsIssuance', issuance.pk
            )
            messages.success(request, f'Issuance #{issuance.pk} accepted. Goods handed over successfully.')
            
    return redirect('finished_store:list')


@role_required('store_officer', 'md')
@store_type_required('finished')
def list_records(request):
    from finished_store.models import FinishedGoodsReturn
    user = get_current_user(request)
    if user.role == 'store_officer':
        receipts = FinishedGoodsReceipt.objects.all().order_by('-date', '-created_at')
        issuances = FinishedGoodsIssuance.objects.all().order_by('-date', '-created_at')
        historical_returns = FinishedGoodsReturn.objects.all().order_by('-date', '-created_at')
    else:
        receipts = FinishedGoodsReceipt.objects.all().order_by('-date', '-created_at')
        issuances = FinishedGoodsIssuance.objects.all().order_by('-date', '-created_at')
        historical_returns = FinishedGoodsReturn.objects.all().order_by('-date', '-created_at')
    
    from procurement.models import MATERIAL_CHOICES
    balances = {}
    for mat_val, mat_label in MATERIAL_CHOICES:
        for size_val, size_label in PRODUCT_SIZE_CHOICES:
            bal = _fg_balance(mat_val, size_val)
            if bal > 0 or size_val == '10kg':
                balances[f"{mat_val}|{size_val}"] = {
                    'material_label': mat_label.upper(),
                    'size_label': size_label,
                    'qty': bal,
                    'material_val': mat_val
                }

    pending_returns   = FinishedGoodsReturn.objects.filter(status='pending').order_by('-date', '-created_at')
    pending_issuances = FinishedGoodsIssuance.objects.filter(status='pending').order_by('-date', '-created_at')
    pending_receipts  = FinishedGoodsReceipt.objects.filter(status='pending').order_by('-date', '-created_at')
    
    return render(request, 'finished_store/list.html', {
        'current_user': user, 'receipts': receipts, 'issuances': issuances,
        'balances': balances, 'pending_returns': pending_returns,
        'pending_issuances': pending_issuances, 'pending_receipts': pending_receipts,
        'returns': historical_returns,
    })
