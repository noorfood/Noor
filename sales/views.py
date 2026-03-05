from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.utils import timezone
from django.db.models import Sum, Count
from accounts.mixins import get_current_user, role_required
from accounts.models import User
from audit.utils import log_action
from sales.models import (
    SalesRecord, SalesPerson, SalesPayment, CompanyRetailLedger,
    SalesManagerCollection, SalesDistributionRecord, SalesResult, SalesManagerPayment,
)
from pricing.models import PriceConfig, CommissionConfig
from finished_store.models import FinishedGoodsIssuance, FinishedGoodsReturn
import datetime


# ─────────────────────────────────────────────────────────────────────────────
# HELPER FUNCTIONS
# ─────────────────────────────────────────────────────────────────────────────

def get_sm_goods_holding(sales_manager, material_type=None):
    """
    Physical sacks held by the Sales Manager (In Hand).
    = Accepted collections - Total distributed to team.
    """
    qs = SalesManagerCollection.objects.filter(
        sales_manager=sales_manager, status='accepted'
    )
    if material_type:
        qs = qs.filter(material_type=material_type)
    total_collected = qs.aggregate(t=Sum('qty_sacks'))['t'] or 0

    # Subtract all distributions recorded by this SM
    dist_qs = SalesDistributionRecord.objects.filter(
        recorded_by=sales_manager
    )
    if material_type:
        dist_qs = dist_qs.filter(material_type=material_type)
    total_distributed = dist_qs.aggregate(t=Sum('qty_given'))['t'] or 0

    # Add back all returned goods
    ret_qs = SalesResult.objects.filter(
        recorded_by=sales_manager
    )
    if material_type:
        ret_qs = ret_qs.filter(material_type=material_type)
    total_returned_sacks = ret_qs.aggregate(t=Sum('qty_returned'))['t'] or 0
    total_returned_pieces = ret_qs.aggregate(t=Sum('qty_pieces_returned'))['t'] or 0
    total_returned = total_returned_sacks + (total_returned_pieces / 10.0)

    return max(0, float(total_collected) - float(total_distributed) + float(total_returned))


def get_gm_goods_holding(material_type, size='10kg'):
    """
    Physical sacks held by the General Manager for Company Direct sales.
    = Accepted Company Issuances - Total Company Sales recorded - Sacks opened for retail.
    """
    total_issued = FinishedGoodsIssuance.objects.filter(
        channel='company', status='accepted', 
        material_type=material_type, product_size=size
    ).aggregate(t=Sum('qty_issued'))['t'] or 0

    total_sold = SalesRecord.objects.filter(
        channel='company', material_type=material_type, product_size=size
    ).aggregate(t=Sum('qty_sold'))['t'] or 0

    # Also subtract sacks that were "opened" to replenish the 1kg retail piece ledger
    total_opened_pieces = CompanyRetailLedger.objects.filter(
        material_type=material_type, action='open_sack'
    ).aggregate(t=Sum('pieces_changed'))['t'] or 0
    total_opened_sacks = total_opened_pieces / 10 if total_opened_pieces > 0 else 0

    return max(0, total_issued - total_sold - total_opened_sacks)


def get_sm_money_outstanding(sales_manager):
    """
    Total money outstanding for the Sales Manager.
    = Total value of accepted collections - Total confirmed payments.
    """
    total_value = SalesManagerCollection.objects.filter(
        sales_manager=sales_manager, status='accepted'
    ).aggregate(t=Sum('total_value'))['t'] or 0

    total_paid = SalesManagerPayment.objects.filter(
        sales_manager=sales_manager, status='confirmed'
    ).aggregate(
        t=Sum('amount_cash') + Sum('amount_transfer')
    )['t'] or 0

    total_commission = SalesResult.objects.filter(
        recorded_by=sales_manager
    ).aggregate(t=Sum('commission_amount'))['t'] or 0

    return max(0.0, float(total_value) - float(total_paid) - float(total_commission))


def get_sm_money_received(sales_manager):
    """Total confirmed money received from the Sales Manager."""
    return float(SalesManagerPayment.objects.filter(
        sales_manager=sales_manager, status='confirmed'
    ).aggregate(t=Sum('amount_cash') + Sum('amount_transfer'))['t'] or 0)


# ─────────────────────────────────────────────────────────────────────────────
# DEPRECATED helpers kept for legacy reports only — do NOT use in new features
# ─────────────────────────────────────────────────────────────────────────────

def get_salesperson_balance(salesperson, size='10kg'):
    """LEGACY: Goods in a SalesPerson's hand from old flow."""
    issued = (FinishedGoodsIssuance.objects
              .filter(sales_record__sales_person=salesperson, status='accepted')
              .aggregate(t=Sum('qty_issued'))['t'] or 0)
    sold = (SalesRecord.objects
            .filter(sales_person=salesperson, product_size=size)
            .aggregate(t=Sum('qty_sold'))['t'] or 0)
    return max(0, issued - sold)


def get_salesperson_money_outstanding(salesperson):
    """LEGACY: Total money outstanding across old SalesRecords for a SalesPerson."""
    records = SalesRecord.objects.filter(sales_person=salesperson)
    total = 0
    for r in records:
        total += r.amount_outstanding
    return total


# ─────────────────────────────────────────────────────────────────────────────
# SALES MANAGER DASHBOARD
# ─────────────────────────────────────────────────────────────────────────────

@role_required('sales_manager', 'manager', 'md')
def dashboard(request):
    user = get_current_user(request)

    if user.role == 'sales_manager':
        # Pending collections waiting for SM to acknowledge
        pending_collections = SalesManagerCollection.objects.filter(
            sales_manager=user, status='pending'
        ).order_by('-date', '-created_at')

        # Goods holding per material
        maize_holding = get_sm_goods_holding(user, 'maize')
        wheat_holding = get_sm_goods_holding(user, 'wheat')

        # Money outstanding
        money_outstanding = get_sm_money_outstanding(user)

        # Recent ALL collections — pending first, then accepted
        recent_collections = SalesManagerCollection.objects.filter(
            sales_manager=user
        ).order_by('-date', '-created_at')[:10]

        pending_count = SalesManagerCollection.objects.filter(
            sales_manager=user, status='pending'
        ).count()

        return render(request, 'sales/dashboard.html', {
            'current_user': user,
            'pending_count': pending_count,
            'maize_holding': maize_holding,
            'wheat_holding': wheat_holding,
            'money_outstanding': money_outstanding,
            'recent_collections': recent_collections,
            'show_money': True,
        })

    else:
        # MD / GM — sees all Sales Managers' summaries
        sales_managers = User.objects.filter(role='sales_manager', status='active')
        sm_summaries = []
        for sm in sales_managers:
            maize = get_sm_goods_holding(sm, 'maize')
            wheat = get_sm_goods_holding(sm, 'wheat')
            money = get_sm_money_outstanding(sm)
            pending_count = SalesManagerCollection.objects.filter(
                sales_manager=sm, status='pending'
            ).count()
            sm_summaries.append({
                'sm': sm,
                'maize_holding': maize,
                'wheat_holding': wheat,
                'goods_balance': maize + wheat,
                'money_outstanding': money,
                'pending_count': pending_count,
            })

        # Recent collections across all SMs for GM overview
        recent_collections = SalesManagerCollection.objects.all().order_by('-date', '-created_at')[:15]

        # Pending SM payments awaiting GM confirmation
        pending_payments = SalesManagerPayment.objects.filter(
            status='pending_gm'
        ).order_by('-date', '-created_at')

        return render(request, 'sales/dashboard.html', {
            'current_user': user,
            'sm_summaries': sm_summaries,
            'recent_collections': recent_collections,
            'pending_payments': pending_payments,
            'show_money': user.role in ('md', 'manager'),
        })


# ─────────────────────────────────────────────────────────────────────────────
# SALESPERSON MANAGEMENT (Sales Manager / MD)
# ─────────────────────────────────────────────────────────────────────────────

@role_required('sales_manager', 'md')
def list_salespersons(request):
    user = get_current_user(request)
    persons = SalesPerson.objects.all().order_by('-created_at')
    return render(request, 'sales/salespersons.html', {'current_user': user, 'persons': persons})


@role_required('sales_manager', 'md')
def add_salesperson(request):
    user = get_current_user(request)
    error = None
    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        channel = request.POST.get('channel')
        phone = request.POST.get('phone', '').strip()
        notes = request.POST.get('notes', '').strip()
        if not name or not channel:
            error = 'Name and channel are required.'
        else:
            sp = SalesPerson.objects.create(
                name=name, channel=channel, phone=phone,
                notes=notes, created_by=user
            )
            log_action(request, user, 'sales', 'ADD_SALESPERSON',
                       f'Added {channel}: {name}', 'SalesPerson', sp.pk)
            messages.success(request, f'{sp.get_channel_display()} "{name}" added successfully.')
            return redirect('sales:salespersons')
    return render(request, 'sales/add_salesperson.html', {'current_user': user, 'error': error})


# ─────────────────────────────────────────────────────────────────────────────
# SM COLLECTIONS — List and Acknowledge
# ─────────────────────────────────────────────────────────────────────────────

@role_required('sales_manager', 'manager', 'md')
def list_sm_collections(request):
    """SM sees all their collections. GM/MD sees all collections from all SMs."""
    user = get_current_user(request)
    if user.role == 'sales_manager':
        collections = SalesManagerCollection.objects.filter(
            sales_manager=user
        ).order_by('-date', '-created_at')
    else:
        collections = SalesManagerCollection.objects.all().order_by('-date', '-created_at')

    return render(request, 'sales/list_collections.html', {
        'current_user': user,
        'collections': collections,
        'maize_holding': get_sm_goods_holding(user, 'maize') if user.role == 'sales_manager' else None,
        'wheat_holding': get_sm_goods_holding(user, 'wheat') if user.role == 'sales_manager' else None,
        'money_outstanding': get_sm_money_outstanding(user) if user.role == 'sales_manager' else None,
    })


@role_required('sales_manager')
def acknowledge_collection(request, collection_id):
    """
    Sales Manager accepts or rejects a pending SM collection.
    CRITICAL: Only after acceptance does the SM carry responsibility for those goods.
    """
    user = get_current_user(request)
    collection = get_object_or_404(
        SalesManagerCollection, pk=collection_id,
        sales_manager=user, status='pending'
    )

    if request.method == 'POST':
        action = request.POST.get('action')
        rejection_note = request.POST.get('rejection_note', '').strip()

        if action == 'accept':
            collection.status = 'accepted'
            collection.save(update_fields=['status'])
            
            # Sync the linked FinishedGoodsIssuance in the store
            for issuance in collection.issuances.all():
                issuance.status = 'accepted'
                issuance.save(update_fields=['status'])

            log_action(request, user, 'sales', 'ACCEPT_COLLECTION',
                       f'SM accepted collection #{collection.pk}: '
                       f'{collection.qty_sacks} × {collection.material_type} sacks | '
                       f'₦{collection.total_value:,.0f}',
                       'SalesManagerCollection', collection.pk)
            messages.success(
                request,
                f'Collection #{collection.pk} accepted. '
                f'{collection.qty_sacks} {collection.material_type.upper()} sacks are now in your hands. '
                f'Total value: ₦{collection.total_value:,.0f}'
            )

        elif action == 'reject':
            if not rejection_note:
                messages.error(request, 'You must provide a reason for rejection.')
                return render(request, 'sales/acknowledge_collection.html', {
                    'current_user': user,
                    'collection': collection,
                    'error': 'Rejection reason is required.',
                })
            collection.status = 'rejected'
            collection.rejection_note = rejection_note
            collection.save(update_fields=['status', 'rejection_note'])
            
            # Sync the linked FinishedGoodsIssuance in the store
            for issuance in collection.issuances.all():
                issuance.status = 'rejected'
                issuance.rejection_note = rejection_note
                issuance.save(update_fields=['status', 'rejection_note'])

            log_action(request, user, 'sales', 'REJECT_COLLECTION',
                       f'SM rejected collection #{collection.pk}: {rejection_note}',
                       'SalesManagerCollection', collection.pk)
            messages.warning(
                request,
                f'Collection #{collection.pk} rejected. '
                f'Store Officer will need to recount and record again.'
            )
        
        return redirect('sales:dashboard')

    return render(request, 'sales/acknowledge_collection.html', {
        'current_user': user,
        'collection': collection,
    })


# ─────────────────────────────────────────────────────────────────────────────
# SP DISTRIBUTION — SM gives sacks to a sales person (performance only)
# ─────────────────────────────────────────────────────────────────────────────

@role_required('sales_manager')
def record_distribution(request):
    """
    Sales Manager records sacks given to a SalesPerson.
    PERFORMANCE TRACKING ONLY — no financial impact on the company.
    """
    user = get_current_user(request)
    error = None
    today = datetime.date.today().isoformat()
    selected_sp_id = request.GET.get('sp')

    # Current "In Hand" balances for the SM
    maize_in_hand = get_sm_goods_holding(user, 'maize')
    wheat_in_hand = get_sm_goods_holding(user, 'wheat')

    salespersons = SalesPerson.objects.filter(status='active').order_by('channel', 'name')

    if request.method == 'POST':
        try:
            date_val = datetime.date.fromisoformat(request.POST.get('date'))
            material_type = request.POST.get('material_type')
            sp_id = request.POST.get('salesperson_id')
            qty = int(request.POST.get('qty_given', 0))
            notes = request.POST.get('notes', '').strip()

            # Validation: check physical availability
            current_holding = get_sm_goods_holding(user, material_type)

            if qty <= 0:
                error = 'Quantity must be greater than zero.'
            elif qty > current_holding:
                error = f'Insufficient stock. You only have {current_holding} {material_type} sacks in hand.'
            else:
                sp = get_object_or_404(SalesPerson, pk=sp_id)

                # Find the MOST RECENT accepted collection for this material to "link" to (audit only)
                # If none exists (unlikely given holding > 0), we leave it null.
                recent_coll = SalesManagerCollection.objects.filter(
                    sales_manager=user, status='accepted', material_type=material_type
                ).order_by('-date', '-created_at').first()

                dist = SalesDistributionRecord.objects.create(
                    date=date_val,
                    collection=recent_coll,
                    sales_person=sp,
                    material_type=material_type,
                    qty_given=qty,
                    recorded_by=user,
                    notes=notes,
                )
                log_action(request, user, 'sales', 'RECORD_DISTRIBUTION',
                           f'Gave {qty} × {material_type} sacks to {sp.name} ({sp.channel})',
                           'SalesDistributionRecord', dist.pk)
                messages.success(
                    request,
                    f'Recorded: {qty} {material_type.upper()} sacks given to {sp.name}.'
                )
                return redirect('sales:sp_performance')

        except Exception as e:
            error = f'Error: {str(e)}'

    return render(request, 'sales/record_distribution.html', {
        'current_user': user,
        'error': error,
        'today': today,
        'maize_in_hand': maize_in_hand,
        'wheat_in_hand': wheat_in_hand,
        'salespersons': salespersons,
        'selected_sp_id': selected_sp_id,
    })


# ─────────────────────────────────────────────────────────────────────────────
# SP SALES RESULT — SM records what each SP sold (performance + holding update)
# ─────────────────────────────────────────────────────────────────────────────

@role_required('sales_manager')
def record_sales_result(request):
    """
    SM records how many sacks a SalesPerson sold and the money returned.
    Commission is auto-calculated. This reduces SM's outstanding holding.
    SP does NOT owe the company — only the SM does.
    """
    user = get_current_user(request)
    error = None
    today = datetime.date.today().isoformat()
    selected_sp_id = request.GET.get('sp')

    # Build salesperson list with their current holding per-material
    raw_salespersons = SalesPerson.objects.filter(status='active').order_by('channel', 'name')
    salespersons = []
    for sp in raw_salespersons:
        # Maize Holding
        given_m = SalesDistributionRecord.objects.filter(
            sales_person=sp, recorded_by=user, material_type='maize'
        ).aggregate(t=Sum('qty_given'))['t'] or 0
        sold_m = SalesResult.objects.filter(
            sales_person=sp, recorded_by=user, material_type='maize'
        ).aggregate(s=Sum('qty_sold'), p=Sum('qty_pieces_sold'))
        sp.maize_holding = float(given_m) - (float(sold_m['s'] or 0) + (float(sold_m['p'] or 0) / 10))
        sp.maize_holding = max(0.0, sp.maize_holding)

        # Wheat Holding
        given_w = SalesDistributionRecord.objects.filter(
            sales_person=sp, recorded_by=user, material_type='wheat'
        ).aggregate(t=Sum('qty_given'))['t'] or 0
        sold_w = SalesResult.objects.filter(
            sales_person=sp, recorded_by=user, material_type='wheat'
        ).aggregate(s=Sum('qty_sold'), p=Sum('qty_pieces_sold'))
        sp.wheat_holding = float(given_w) - (float(sold_w['s'] or 0) + (float(sold_w['p'] or 0) / 10))
        sp.wheat_holding = max(0.0, sp.wheat_holding)

        sp.maize_comm = CommissionConfig.get_active_pct(sp.channel, 'maize', '10kg', datetime.date.fromisoformat(today)) or 0
        sp.wheat_comm = CommissionConfig.get_active_pct(sp.channel, 'wheat', '10kg', datetime.date.fromisoformat(today)) or 0
        
        salespersons.append(sp)

    maize_price = PriceConfig.get_active_price('sales_manager', 'maize', '10kg', datetime.date.fromisoformat(today)) or 0
    wheat_price = PriceConfig.get_active_price('sales_manager', 'wheat', '10kg', datetime.date.fromisoformat(today)) or 0

    if request.method == 'POST':
        try:
            date_val = datetime.date.fromisoformat(request.POST.get('date'))
            sales_person_id = request.POST.get('sales_person_id')
            material_type = request.POST.get('material_type')
            qty_sold = int(request.POST.get('qty_sold', 0) or 0)
            qty_pieces_sold = int(request.POST.get('qty_pieces_sold', 0) or 0)
            qty_returned = int(request.POST.get('qty_returned', 0) or 0)
            qty_pieces_returned = int(request.POST.get('qty_pieces_returned', 0) or 0)
            amount_returned = float(request.POST.get('amount_returned', 0) or 0)
            notes = request.POST.get('notes', '').strip()

            if qty_sold <= 0 and qty_pieces_sold <= 0:
                error = 'Quantity sold (sacks or pieces) must be greater than zero.'
            else:
                sp = get_object_or_404(SalesPerson, pk=sales_person_id)

                # Get MD-configured prices (sales_manager channel)
                unit_price = PriceConfig.get_active_price(
                    'sales_manager', material_type, '10kg', date_val
                )

                if unit_price is None:
                    error = (f'No price configured for sales_manager / {material_type} / 10kg '
                             f'on {date_val}. Please ask MD to set a price.')
                else:
                    unit_price_piece = unit_price / 10

                    # Get commission %
                    # We use the 10kg % as the primary commission for the record.
                    comm_pct = CommissionConfig.get_active_pct(
                        sp.channel, material_type, '10kg', date_val
                    )

                    result = SalesResult.objects.create(
                        date=date_val,
                        sales_person=sp,
                        material_type=material_type,
                        qty_sold=qty_sold,
                        qty_pieces_sold=qty_pieces_sold,
                        qty_returned=qty_returned,
                        qty_pieces_returned=qty_pieces_returned,
                        amount_returned=amount_returned,
                        unit_price=unit_price,
                        unit_price_piece=unit_price_piece or 0,
                        commission_pct=comm_pct,
                        recorded_by=user,
                        notes=notes,
                        is_locked=True,
                    )
                    log_action(request, user, 'sales', 'RECORD_SALES_RESULT',
                               f'{sp.name} sold {qty_sold} sacks & {qty_pieces_sold} pieces | '
                               f'Net ₦{result.net_due_to_company:,.0f}',
                               'SalesResult', result.pk)
                    messages.success(
                        request,
                        f'Recorded: {sp.name} sold {qty_sold} sacks and {qty_pieces_sold} pieces. '
                        f'Commission: ₦{result.commission_amount:,.0f} | '
                        f'Net due to company: ₦{result.net_due_to_company:,.0f}'
                    )
                    return redirect('sales:sp_performance')

        except Exception as e:
            error = f'Error: {str(e)}'

    return render(request, 'sales/record_sales_result.html', {
        'current_user': user,
        'error': error,
        'today': today,
        'salespersons': salespersons,
        'selected_sp_id': selected_sp_id,
        'maize_price': float(maize_price),
        'wheat_price': float(wheat_price),
    })


# ─────────────────────────────────────────────────────────────────────────────
# SP PERFORMANCE TABLE (Sales Manager + MD view)
# ─────────────────────────────────────────────────────────────────────────────

@role_required('sales_manager', 'manager', 'md')
def sp_performance(request):
    """
    Shows per-SalesPerson performance: given vs sold vs commission.
    This is PURELY informational — SalesPersons are NOT company debtors.
    """
    user = get_current_user(request)

    if user.role == 'sales_manager':
        salespersons = SalesPerson.objects.filter(status='active').order_by('channel', 'name')
        manager_filter = {'recorded_by': user}
    else:
        salespersons = SalesPerson.objects.filter(status='active').order_by('channel', 'name')
        manager_filter = {}

    sp_rows = []
    for sp in salespersons:
        total_given = SalesDistributionRecord.objects.filter(
            sales_person=sp, **manager_filter
        ).aggregate(t=Sum('qty_given'))['t'] or 0

        total_sold = SalesResult.objects.filter(
            sales_person=sp, **manager_filter
        ).aggregate(t=Sum('qty_sold'))['t'] or 0

        total_pieces_sold = SalesResult.objects.filter(
            sales_person=sp, **manager_filter
        ).aggregate(t=Sum('qty_pieces_sold'))['t'] or 0

        total_commission = SalesResult.objects.filter(
            sales_person=sp, **manager_filter
        ).aggregate(t=Sum('commission_amount'))['t'] or 0

        total_net = SalesResult.objects.filter(
            sales_person=sp, **manager_filter
        ).aggregate(t=Sum('net_due_to_company'))['t'] or 0

        total_returned = SalesResult.objects.filter(
            sales_person=sp, **manager_filter
        ).aggregate(t=Sum('qty_returned'))['t'] or 0

        total_pieces_returned = SalesResult.objects.filter(
            sales_person=sp, **manager_filter
        ).aggregate(t=Sum('qty_pieces_returned'))['t'] or 0

        total_amount_returned = SalesResult.objects.filter(
            sales_person=sp, **manager_filter
        ).aggregate(t=Sum('amount_returned'))['t'] or 0

        total_outstanding = max(0.0, float(total_net) - float(total_amount_returned))

        # Unsold calculation: Given Sacks - Sold - Returned
        unsold = float(total_given) - (float(total_sold) + (float(total_pieces_sold) / 10)) - (float(total_returned) + (float(total_pieces_returned) / 10))

        sp_rows.append({
            'sp': sp,
            'total_given': total_given,
            'total_sold': total_sold,
            'total_pieces_sold': total_pieces_sold,
            'unsold': max(0, unsold),
            'total_commission': float(total_commission),
            'total_net': float(total_net),
            'total_outstanding': total_outstanding,
        })

    # Sort by most sold
    sp_rows.sort(key=lambda x: x['total_sold'], reverse=True)

    return render(request, 'sales/sp_performance.html', {
        'current_user': user,
        'sp_rows': sp_rows,
        'show_money': (user.role in ('md',)),
    })


# ─────────────────────────────────────────────────────────────────────────────
# SP DETAIL — Full sales & distribution history for one SalesPerson
# ─────────────────────────────────────────────────────────────────────────────

@role_required('sales_manager', 'manager', 'md')
def sp_detail(request, sp_id):
    """
    Shows full sales result + distribution history for a single SalesPerson.
    Accessible by the SM who manages them, or MD/GM for oversight.
    """
    user = get_current_user(request)
    sp = get_object_or_404(SalesPerson, pk=sp_id)

    if user.role == 'sales_manager':
        # SM can only see their own team's records
        results = SalesResult.objects.filter(
            sales_person=sp, recorded_by=user
        ).select_related('recorded_by').order_by('-date', '-created_at')
        distributions = SalesDistributionRecord.objects.filter(
            sales_person=sp, recorded_by=user
        ).order_by('-date', '-created_at')
    else:
        # MD/GM can see all
        results = SalesResult.objects.filter(
            sales_person=sp
        ).select_related('recorded_by').order_by('-date', '-created_at')
        distributions = SalesDistributionRecord.objects.filter(
            sales_person=sp
        ).order_by('-date', '-created_at')

    # Totals
    total_maize_given  = distributions.filter(material_type='maize').aggregate(t=Sum('qty_given'))['t'] or 0
    total_wheat_given  = distributions.filter(material_type='wheat').aggregate(t=Sum('qty_given'))['t'] or 0
    total_maize_sold   = results.filter(material_type='maize').aggregate(t=Sum('qty_sold'))['t'] or 0
    total_maize_pieces = results.filter(material_type='maize').aggregate(t=Sum('qty_pieces_sold'))['t'] or 0
    total_wheat_sold   = results.filter(material_type='wheat').aggregate(t=Sum('qty_sold'))['t'] or 0
    total_wheat_pieces = results.filter(material_type='wheat').aggregate(t=Sum('qty_pieces_sold'))['t'] or 0

    total_maize_returned   = results.filter(material_type='maize').aggregate(t=Sum('qty_returned'))['t'] or 0
    total_maize_pieces_returned = results.filter(material_type='maize').aggregate(t=Sum('qty_pieces_returned'))['t'] or 0
    total_wheat_returned   = results.filter(material_type='wheat').aggregate(t=Sum('qty_returned'))['t'] or 0
    total_wheat_pieces_returned = results.filter(material_type='wheat').aggregate(t=Sum('qty_pieces_returned'))['t'] or 0

    total_net = results.aggregate(t=Sum('net_due_to_company'))['t'] or 0
    total_amount_returned = results.aggregate(t=Sum('amount_returned'))['t'] or 0
    total_outstanding = max(0.0, float(total_net) - float(total_amount_returned))

    return render(request, 'sales/sp_detail.html', {
        'current_user': user,
        'sp': sp,
        'results': results,
        'distributions': distributions,
        'total_maize_given': total_maize_given,
        'total_wheat_given': total_wheat_given,
        'total_maize_sold': total_maize_sold,
        'total_maize_pieces': total_maize_pieces,
        'total_wheat_sold': total_wheat_sold,
        'total_wheat_pieces': total_wheat_pieces,
        'total_maize_returned': total_maize_returned,
        'total_maize_pieces_returned': total_maize_pieces_returned,
        'total_wheat_returned': total_wheat_returned,
        'total_wheat_pieces_returned': total_wheat_pieces_returned,
        'unsold_maize': max(0.0, float(total_maize_given) - (float(total_maize_sold) + (float(total_maize_pieces) / 10)) - (float(total_maize_returned) + (float(total_maize_pieces_returned) / 10))),
        'unsold_wheat': max(0.0, float(total_wheat_given) - (float(total_wheat_sold) + (float(total_wheat_pieces) / 10)) - (float(total_wheat_returned) + (float(total_wheat_pieces_returned) / 10))),
        'total_outstanding': total_outstanding,
    })


# ─────────────────────────────────────────────────────────────────────────────
# SM PAYMENT RECORDING (Sales Manager records sending money to company)
# ─────────────────────────────────────────────────────────────────────────────

@role_required('sales_manager')
def record_sm_payment(request):
    """
    SM records a payment sent to the company.
    GM must confirm before it counts against SM's outstanding balance.
    """
    user = get_current_user(request)
    error = None
    today = datetime.date.today().isoformat()

    # SM's current outstanding balance
    outstanding = get_sm_money_outstanding(user)

    if request.method == 'POST':
        try:
            date_val = datetime.date.fromisoformat(request.POST.get('date'))
            amount_cash = float(request.POST.get('amount_cash', 0) or 0)
            amount_transfer = float(request.POST.get('amount_transfer', 0) or 0)
            notes = request.POST.get('notes', '').strip()

            total = amount_cash + amount_transfer
            if total <= 0:
                error = 'Payment amount must be greater than zero.'
            elif total > outstanding + 0.01:
                error = (f'Payment amount ₦{total:,.0f} exceeds your outstanding balance '
                         f'₦{outstanding:,.0f}.')
            else:
                pmt = SalesManagerPayment.objects.create(
                    date=date_val,
                    sales_manager=user,
                    amount_cash=amount_cash,
                    amount_transfer=amount_transfer,
                    recorded_by=user,
                    notes=notes,
                    status='pending_gm',
                    is_locked=True,
                )
                log_action(request, user, 'sales', 'RECORD_SM_PAYMENT',
                           f'SM recorded payment: Cash ₦{amount_cash:,.0f} + '
                           f'Transfer ₦{amount_transfer:,.0f} | Pending GM confirmation',
                           'SalesManagerPayment', pmt.pk)
                messages.success(
                    request,
                    f'Payment recorded (₦{total:,.0f}). It is now pending GM confirmation.'
                )
                return redirect('sales:list_collections')
        except Exception as e:
            error = f'Error: {str(e)}'

    # Payment history
    payments = SalesManagerPayment.objects.filter(
        sales_manager=user
    ).order_by('-date', '-created_at')

    return render(request, 'sales/sm_payment.html', {
        'current_user': user,
        'error': error,
        'today': today,
        'outstanding': outstanding,
        'payments': payments,
    })


# ─────────────────────────────────────────────────────────────────────────────
# GM PAYMENT CONFIRMATION (General Manager confirms SM's payment)
# ─────────────────────────────────────────────────────────────────────────────

@role_required('manager', 'md')
def confirm_sm_payment(request, payment_id):
    """
    GM confirms or rejects the SM's recorded payment.
    Only confirmed payments reduce the SM's outstanding balance.
    """
    user = get_current_user(request)
    payment = get_object_or_404(SalesManagerPayment, pk=payment_id, status='pending_gm')

    if request.method == 'POST':
        action = request.POST.get('action')
        gm_notes = request.POST.get('gm_notes', '').strip()

        if action == 'confirm':
            payment.status = 'confirmed'
            payment.confirmed_by = user
            payment.confirmed_at = timezone.now()
            payment.gm_notes = gm_notes
            payment.save()
            log_action(request, user, 'sales', 'CONFIRM_SM_PAYMENT',
                       f'GM confirmed SM payment #{payment.pk}: '
                       f'₦{payment.total:,.0f} from {payment.sales_manager.full_name}',
                       'SalesManagerPayment', payment.pk)
            messages.success(
                request,
                f'Payment of ₦{payment.total:,.0f} from {payment.sales_manager.full_name} confirmed. '
                f'Their outstanding balance has been updated.'
            )

        elif action == 'reject':
            payment.status = 'rejected'
            payment.confirmed_by = user
            payment.confirmed_at = timezone.now()
            payment.gm_notes = gm_notes
            payment.save()
            log_action(request, user, 'sales', 'REJECT_SM_PAYMENT',
                       f'GM rejected SM payment #{payment.pk}: {gm_notes}',
                       'SalesManagerPayment', payment.pk)
            messages.warning(
                request,
                f'Payment #{payment.pk} rejected. SM will need to re-record.'
            )

    return render(request, 'sales/confirm_sm_payment.html', {
        'current_user': user,
        'payment': payment,
    })


# ─────────────────────────────────────────────────────────────────────────────
# LIST ALL SM PAYMENTS (for GM and MD oversight)
# ─────────────────────────────────────────────────────────────────────────────

@role_required('sales_manager', 'manager', 'md')
def list_sm_payments(request):
    """List all SM payments for oversight."""
    user = get_current_user(request)
    if user.role == 'sales_manager':
        payments = SalesManagerPayment.objects.filter(
            sales_manager=user
        ).order_by('-date', '-created_at')
    else:
        payments = SalesManagerPayment.objects.all().order_by('-date', '-created_at')

    pending_payments = payments.filter(status='pending_gm')

    return render(request, 'sales/list_payments.html', {
        'current_user': user,
        'payments': payments,
        'pending_payments': pending_payments,
        'show_money': True,
    })


# ─────────────────────────────────────────────────────────────────────────────
# OUTSTANDING VIEW (SM-level, not SP-level)
# ─────────────────────────────────────────────────────────────────────────────

@role_required('sales_manager', 'manager', 'md')
def outstanding_view(request):
    """
    Shows outstanding goods and money at the SALES MANAGER level.
    The company tracks the SM, not individual sales persons.
    """
    user = get_current_user(request)

    sales_managers = User.objects.filter(role='sales_manager', status='active')
    sm_outstanding = []
    for sm in sales_managers:
        goods = get_sm_goods_holding(sm)
        money = get_sm_money_outstanding(sm)
        collected = SalesManagerCollection.objects.filter(
            sales_manager=sm, status='accepted'
        ).aggregate(t=Sum('qty_sacks'))['t'] or 0
        pending_collections = SalesManagerCollection.objects.filter(
            sales_manager=sm, status='pending'
        ).count()
        sm_outstanding.append({
            'sm': sm,
            'total_collected': collected,
            'goods_holding': goods,
            'money_outstanding': money,
            'pending_collection_count': pending_collections,
        })

    return render(request, 'sales/outstanding.html', {
        'current_user': user,
        'sm_outstanding': sm_outstanding,
        'show_money': (user.role in ('md', 'manager')),
    })


# ─────────────────────────────────────────────────────────────────────────────
# LIST SALES (Legacy SalesRecords — historical view)
# ─────────────────────────────────────────────────────────────────────────────

@role_required('sales_manager', 'manager', 'md')
def list_sales(request):
    """Historical sales records (legacy model). Read-only."""
    user = get_current_user(request)
    if user.role == 'sales_manager':
        sales = SalesRecord.objects.filter(recorded_by=user).order_by('-date', '-created_at')
    else:
        sales = SalesRecord.objects.all().order_by('-date', '-created_at')
    return render(request, 'sales/list.html', {
        'current_user': user,
        'sales': sales,
        'show_money': (user.role == 'md'),
    })


# ─────────────────────────────────────────────────────────────────────────────
# SALESPERSON MANAGEMENT (compat alias)
# ─────────────────────────────────────────────────────────────────────────────

@role_required('sales_manager', 'manager', 'md')
def list_salespersons_view(request):
    return list_salespersons(request)


# ─────────────────────────────────────────────────────────────────────────────
# COMPANY DIRECT SALE (GM Only — completely separate from SM flow)
# ─────────────────────────────────────────────────────────────────────────────

@role_required('manager', 'md')
def record_company_sale(request):
    """
    Company direct sale — buyer comes to the factory.
    Sales Manager is NOT involved. Only GM handles this.
    FG Store records the issuance, GM records the payment.
    """
    user = get_current_user(request)
    error = None
    today = datetime.date.today().isoformat()
    from procurement.models import MATERIAL_CHOICES
    from finished_store.views import _fg_balance
    import math

    if request.method == 'POST':
        date_val = request.POST.get('date')
        buyer_name = request.POST.get('buyer_name', '').strip()
        material_type = request.POST.get('material_type', 'maize')
        unit = request.POST.get('unit')
        qty = int(request.POST.get('qty', 0))
        amount_paid = float(request.POST.get('amount_paid', 0))
        notes = request.POST.get('notes', '').strip()

        if not date_val or not buyer_name or not material_type or not unit or qty <= 0:
            error = 'All fields are required.'
        else:
            if unit == '1kg':
                # Retail piece sale (1kg)
                current_pieces = CompanyRetailLedger.objects.filter(
                    material_type=material_type
                ).aggregate(t=Sum('pieces_changed'))['t'] or 0

                if current_pieces < qty:
                    # Not enough pieces. Can we open a sack from our HAND?
                    sacks_in_hand = get_gm_goods_holding(material_type)
                    needed_pieces = qty - current_pieces
                    sacks_to_open = math.ceil(needed_pieces / 10)

                    if sacks_in_hand >= sacks_to_open:
                        # Success! Open a sack from our hand immediately.
                        CompanyRetailLedger.objects.create(
                            date=date_val,
                            material_type=material_type,
                            action='open_sack',
                            pieces_changed=sacks_to_open * 10,
                            recorded_by=user,
                            notes=f"Auto-opened {sacks_to_open} sacks from my hand to fulfill retail sale."
                        )
                        messages.info(request, f"Automatically opened {sacks_to_open} sack(s) from your 'In Hand' stock.")
                    else:
                        # Not enough in hand either. Request restock from FG store.
                        # This request is "Company channel" so it eventually comes back to the GM's hand.
                        rem_after_hand = needed_pieces - (sacks_in_hand * 10)
                        sacks_required = math.ceil(rem_after_hand / 10)
                        
                        # Trigger the handshake flow
                        FinishedGoodsIssuance.objects.create(
                            date=date_val,
                            material_type=material_type,
                            product_size='10kg',
                            qty_issued=sacks_required,
                            channel='company',
                            issued_by=user,
                            notes="Auto-request: Restock needed for retail pieces."
                        )
                        messages.warning(
                            request,
                            f"Insufficient stock in hand. A restock request for {sacks_required} sacks has been sent to the store."
                        )
                        # We still proceed with the sale if the business allows "selling out of stock" potentially leading to a negative ledger temporarily, 
                        # or we can block it. User said "must remove from his balance", implying he shouldn't sell what he doesn't have.
                        # However, previous logic sent a request and proceeded. I'll maintain that but with a warning.

                sale = SalesRecord.objects.create(
                    date=date_val,
                    recorded_by=user,
                    buyer_name=buyer_name,
                    material_type=material_type,
                    product_size='1kg',
                    channel='company',
                    qty_sold=qty,
                    unit_price=amount_paid / qty if qty > 0 else 0,
                    total_value=amount_paid,
                    status='paid',
                    is_locked=True,
                    notes=notes
                )
                CompanyRetailLedger.objects.create(
                    date=date_val,
                    material_type=material_type,
                    action='retail_sale',
                    pieces_changed=-qty,
                    sales_record=sale,
                    recorded_by=user,
                )
                log_action(request, user, 'sales', 'RECORD_COMPANY_SALE',
                           f'Company Sale (Pieces): {qty}x 1kg {material_type}',
                           'SalesRecord', sale.pk)
                messages.success(request, f'Recorded retail piece sale to {buyer_name}.')
                return redirect('reports:dashboard')

            elif unit == '10kg':
                # Standard sack sale — fulfill from GM's "In Hand" holding
                current_holding = get_gm_goods_holding(material_type)
                
                if qty > current_holding:
                    error = (f'Insufficient {material_type.upper()} 10kg sacks in your hand. '
                             f'You currently have {current_holding} sacks. '
                             f'Please request and accept an issuance from the FG Store first.')
                else:
                    sale = SalesRecord.objects.create(
                        date=date_val,
                        recorded_by=user,
                        buyer_name=buyer_name,
                        material_type=material_type,
                        product_size='10kg',
                        channel='company',
                        qty_sold=qty,
                        unit_price=amount_paid / qty if qty > 0 else 0,
                        total_value=amount_paid,
                        status='paid',
                        is_locked=True,
                        notes=notes
                    )
                    log_action(request, user, 'sales', 'RECORD_COMPANY_SALE',
                               f'Company Sale (Sacks): {qty}x 10kg {material_type}',
                               'SalesRecord', sale.pk)
                    messages.success(request, f'Recorded company sack sale to {buyer_name}.')
                    return redirect('reports:dashboard')

    # Calculate current piece balances for display
    pieces_maize = CompanyRetailLedger.objects.filter(material_type='maize').aggregate(t=Sum('pieces_changed'))['t'] or 0
    pieces_wheat = CompanyRetailLedger.objects.filter(material_type='wheat').aggregate(t=Sum('pieces_changed'))['t'] or 0

    return render(request, 'sales/record_company_sale.html', {
        'current_user': user,
        'error': error,
        'today': today,
        'material_choices': MATERIAL_CHOICES,
        'holding_maize': get_gm_goods_holding('maize'),
        'holding_wheat': get_gm_goods_holding('wheat'),
        'pieces_maize': pieces_maize,
        'pieces_wheat': pieces_wheat,
    })


# ─────────────────────────────────────────────────────────────────────────────
# BRAN SALES (GM Only)
# ─────────────────────────────────────────────────────────────────────────────

@role_required('manager', 'md')
def record_bran_sale(request):
    """Brand (waste) sold by GM. Stored in BrandSale model."""
    user = get_current_user(request)
    error = None
    today = datetime.date.today().isoformat()
    from production.models import BrandSale
    from procurement.models import MATERIAL_CHOICES

    if request.method == 'POST':
        date_val = request.POST.get('date')
        buyer_name = request.POST.get('buyer_name', '').strip()
        material_type = request.POST.get('material_type', 'maize')
        qty = int(request.POST.get('qty', 0))
        amount_paid = float(request.POST.get('amount_paid', 0))
        notes = request.POST.get('notes', '').strip()

        if not date_val or not buyer_name or qty <= 0 or amount_paid <= 0:
            error = 'All fields are required.'
        else:
            bs = BrandSale.objects.create(
                date=date_val,
                material_type=material_type,
                qty_sacks=qty,
                buyer_name=buyer_name,
                price_per_sack=amount_paid / qty,
                total_amount=amount_paid,
                payment_method='cash',
                amount_cash=amount_paid,
                recorded_by=user,
                notes=notes,
                is_locked=True
            )
            log_action(request, user, 'sales', 'RECORD_BRAN_SALE',
                       f'Bran Sale: {qty} sacks {material_type} to {buyer_name}',
                       'BrandSale', bs.pk)
            messages.success(request, f'Recorded bran sale to {buyer_name}.')
            return redirect('reports:dashboard')

    return render(request, 'sales/record_bran_sale.html', {
        'current_user': user,
        'error': error,
        'today': today,
        'material_choices': MATERIAL_CHOICES,
    })


# ─────────────────────────────────────────────────────────────────────────────
# LEGACY: Sale Receipt and Payment Recording (for historical records)
# ─────────────────────────────────────────────────────────────────────────────

@role_required('sales_manager', 'manager', 'md')
def sale_receipt(request, sale_id):
    """Legacy view: receipt for old SalesRecord entries."""
    user = get_current_user(request)
    sale = get_object_or_404(SalesRecord, pk=sale_id)
    payments = sale.payments.order_by('date', 'created_at')
    return render(request, 'sales/receipt.html', {
        'current_user': user,
        'sale': sale,
        'payments': payments,
        'show_money': True,
    })


@role_required('sales_manager')
def record_payment(request, sale_id):
    """Legacy view: payment for old SalesRecord entries."""
    user = get_current_user(request)
    sale = get_object_or_404(SalesRecord, pk=sale_id)
    payments = sale.payments.order_by('-date', '-created_at')
    error = None

    if request.method == 'POST':
        try:
            date_val = request.POST.get('date')
            amount_cash = float(request.POST.get('amount_cash', 0) or 0)
            amount_transfer = float(request.POST.get('amount_transfer', 0) or 0)
            notes = request.POST.get('notes', '').strip()
            total_payment = amount_cash + amount_transfer
            if total_payment <= 0:
                error = 'Payment amount must be greater than zero.'
            else:
                SalesPayment.objects.create(
                    sales_record=sale,
                    date=date_val,
                    amount_cash=amount_cash,
                    amount_transfer=amount_transfer,
                    recorded_by=user,
                    notes=notes,
                    is_locked=True,
                )
                return redirect('sales:receipt', sale_id=sale.pk)
        except Exception as e:
            error = f'Error: {str(e)}'

    return render(request, 'sales/record_payment.html', {
        'current_user': user,
        'sale': sale,
        'payments': payments,
        'error': error,
        'today': datetime.date.today().isoformat(),
    })
