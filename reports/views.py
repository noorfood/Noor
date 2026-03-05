from django.shortcuts import render
from django.http import HttpResponse
from django.db.models import Sum, Avg, Count
from accounts.mixins import get_current_user, role_required
from production.models import MillingBatch, PackagingBatch
from clean_store.models import CleanRawIssuance, CleanRawReturn
from cleaning.models import CleanRawReceipt
from finished_store.models import FinishedGoodsReceipt, FinishedGoodsIssuance, FinishedGoodsReturn, PRODUCT_SIZE_CHOICES
from sales.models import SalesRecord
from reconciliation.models import MoneyReceipt, ReconciliationFlag
from accounts.models import User
from audit.models import AuditLog
import datetime

@role_required('manager', 'md')
def dashboard(request):
    user = get_current_user(request)

    # Quick stats (Operational)
    total_batches = MillingBatch.objects.count() + PackagingBatch.objects.count()
    flagged_batches = MillingBatch.objects.filter(flag_level__in=['warning', 'critical']).count()
    open_flags = ReconciliationFlag.objects.filter(resolved=False).count()

    # Calculate global outstanding for Production (bags in hand not yet milled)
    accepted = CleanRawIssuance.objects.filter(status='accepted').aggregate(t=Sum('num_bags'))['t'] or 0
    milled_new = MillingBatch.objects.aggregate(t=Sum('bags_milled_new'))['t'] or 0
    milled_old = MillingBatch.objects.aggregate(t=Sum('outstanding_bags_milled'))['t'] or 0
    returned = CleanRawReturn.objects.filter(status__in=['pending', 'accepted']).aggregate(t=Sum('num_bags'))['t'] or 0
    outstanding_production = max(0, accepted - milled_new - milled_old - returned)

    # ─────────────────────────────────────────────────────────────────
    # OVERARCHING FINANCIAL METRICS (MD ONLY)
    # ─────────────────────────────────────────────────────────────────
    total_revenue = 0.0
    total_received = 0.0
    total_outstanding = 0.0
    
    if user.role == 'md':
        from sales.models import SalesRecord
        from production.models import BrandSale
        
        # 1. Primary Sales
        all_sales = SalesRecord.objects.all()
        for r in all_sales:
            total_revenue += float(r.total_value)
            total_received += r.total_paid
            total_outstanding += r.amount_outstanding
            
        # 2. Brand / Waste Sales
        all_brands = BrandSale.objects.all()
        for b in all_brands:
            revenue = float(b.total_amount)
            received = float(b.amount_cash) + float(b.amount_transfer)
            total_revenue += revenue
            total_received += received
            total_outstanding += max(0, revenue - received)

    # Staff Roster and Live Feed (Phase 8/11)
    staff_roster = User.objects.filter(status='active').exclude(role='md').order_by('role', 'full_name')
    audit_feed = AuditLog.objects.all().order_by('-timestamp')[:15]
    
    recent_flagged = MillingBatch.objects.filter(flag_level__in=['warning', 'critical']).order_by('-date', '-created_at')[:5]

    # OM Retail and Bran Sales (Phase 20)
    from sales.models import CompanyRetailLedger, SalesRecord
    from production.models import BrandSale
    from procurement.models import MATERIAL_CHOICES
    
    company_sales = SalesRecord.objects.filter(channel='company').order_by('-date', '-created_at')[:10]
    bran_sales = BrandSale.objects.all().order_by('-date', '-created_at')[:10]
    
    retail_balances = []
    for mat_val, mat_label in MATERIAL_CHOICES:
        pieces = CompanyRetailLedger.objects.filter(material_type=mat_val).aggregate(t=Sum('pieces_changed'))['t'] or 0
        retail_balances.append({'material': mat_label, 'pieces': pieces})

    # SM Accountability Summaries for MD/GM Command Center
    from sales.views import get_sm_goods_holding, get_sm_money_outstanding
    from sales.models import SalesManagerCollection
    sm_list = User.objects.filter(role='sales_manager', status='active').order_by('full_name')
    sm_summaries = []
    for sm in sm_list:
        maize = get_sm_goods_holding(sm, 'maize')
        wheat = get_sm_goods_holding(sm, 'wheat')
        money = get_sm_money_outstanding(sm)
        pending_count = SalesManagerCollection.objects.filter(sales_manager=sm, status='pending').count()
        sm_summaries.append({
            'sm': sm,
            'goods_balance': maize + wheat,
            'money_outstanding': money,
            'pending_count': pending_count,
        })

    # Real-world handshake: Goods issued to Company channel but not yet GM-acknowledged
    from finished_store.models import FinishedGoodsIssuance
    pending_company_issuances = FinishedGoodsIssuance.objects.filter(channel='company', status='pending').order_by('-date', '-created_at')

    # Pending SM payments awaiting GM confirmation
    from sales.models import SalesManagerPayment
    pending_sm_payments = SalesManagerPayment.objects.filter(status='pending_gm').order_by('-date', '-created_at')

    return render(request, 'reports/dashboard.html', {
        'current_user': user,
        'total_batches': total_batches,
        'flagged_batches': flagged_batches,
        'open_flags': open_flags,
        'outstanding_production': outstanding_production,
        'total_revenue': total_revenue,
        'total_received': total_received,
        'total_outstanding': total_outstanding,
        'recent_flagged': recent_flagged,
        'staff_roster': staff_roster,
        'audit_feed': audit_feed,
        'company_sales': company_sales,
        'bran_sales': bran_sales,
        'retail_balances': retail_balances,
        'sm_summaries': sm_summaries,
        'pending_company_issuances': pending_company_issuances,
        'pending_sm_payments': pending_sm_payments,
    })


@role_required('manager', 'md')
def production_report(request):
    user = get_current_user(request)
    f_from = request.GET.get('date_from', '')
    f_to = request.GET.get('date_to', '')
    f_material = request.GET.get('material', '')
    f_flag = request.GET.get('flag', '')

    milling = MillingBatch.objects.all().order_by('-date', '-created_at')
    packaging = PackagingBatch.objects.all().order_by('-date', '-created_at')
    
    if f_from:
        milling = milling.filter(date__gte=f_from)
        packaging = packaging.filter(date__gte=f_from)
    if f_to:
        milling = milling.filter(date__lte=f_to)
        packaging = packaging.filter(date__lte=f_to)
    if f_material:
        milling = milling.filter(material_type=f_material)
        packaging = packaging.filter(material_type=f_material)
    if f_flag:
        milling = milling.filter(flag_level=f_flag)

    milling_totals = milling.aggregate(
        total_raw_kg=Sum('total_raw_kg'),
        total_powder_kg=Sum('bulk_powder_kg'),
        total_loss_kg=Sum('loss_kg'),
    )
    
    packaging_totals = packaging.aggregate(
        total_powder_used=Sum('powder_used_kg'),
        total_output_kg=Sum('total_output_kg'),
        total_loss_kg=Sum('loss_kg'),
    )

    if request.GET.get('export') == 'xlsx':
        return _export_production_xlsx(milling, packaging)

    return render(request, 'reports/production.html', {
        'current_user': user, 'milling': milling, 'packaging': packaging, 
        'milling_totals': milling_totals, 'packaging_totals': packaging_totals,
        'f_from': f_from, 'f_to': f_to, 'f_material': f_material, 'f_flag': f_flag,
    })


def _export_production_xlsx(milling, packaging):
    import openpyxl
    from openpyxl.styles import Font, PatternFill, Alignment
    wb = openpyxl.Workbook()
    
    # Milling Sheet
    ws_m = wb.active
    ws_m.title = 'Milling Report'
    headers_m = ['Batch ID', 'Date', 'Officer', 'Material', 'Shift', 'Bags Collected', 'Bags Milled',
               'Outstanding', 'Powder KG', 'Loss KG', 'Loss %', 'Flag']
    ws_m.append(['NOOR FOODS - Milling Report'])
    ws_m.append(['Generated:', datetime.datetime.now().strftime('%Y-%m-%d %H:%M')])
    ws_m.append([])
    ws_m.append(headers_m)

    for b in milling:
        ws_m.append([
            b.pk, str(b.date), b.production_officer.full_name, b.material_type.upper(),
            b.shift, b.bags_milled_new, b.outstanding_bags_milled,
            float(b.bulk_powder_kg), float(b.loss_kg), float(b.loss_pct), b.flag_level.upper()
        ])
        
    # Packaging Sheet
    ws_p = wb.create_sheet('Packaging Report')
    headers_p = ['Batch ID', 'Date', 'Officer', 'Material', 'Shift', 'Milling Source ID', 'Powder Used KG', 'Sacks Produced (10kg)', 'Output KG', 'Loss KG', 'Loss %']
    ws_p.append(['NOOR FOODS - Packaging Report'])
    ws_p.append(['Generated:', datetime.datetime.now().strftime('%Y-%m-%d %H:%M')])
    ws_p.append([])
    ws_p.append(headers_p)
    
    for p in packaging:
        ws_p.append([
            p.pk, str(p.date), p.production_officer.full_name, p.material_type.upper(),
            p.shift, p.milling_batch_id, float(p.powder_used_kg), p.qty_10kg,
            float(p.total_output_kg), float(p.loss_kg), float(p.loss_pct)
        ])

    response = HttpResponse(content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    response['Content-Disposition'] = 'attachment; filename=production_report.xlsx'
    wb.save(response)
    return response


@role_required('manager', 'md')
def store_report(request):
    user = get_current_user(request)
    from clean_store.views import _get_clean_store_balance
    from finished_store.views import _fg_balance
    from procurement.models import RawMaterialReceipt, RawMaterialIssuance

    # --- Dirty Raw Store: bags received from market minus bags issued to cleaning ---
    materials = ['maize', 'wheat']
    dirty_raw = {}
    for mat in materials:
        received = RawMaterialReceipt.objects.filter(material_type=mat).aggregate(
            t=Sum('num_bags'))['t'] or 0
        issued = RawMaterialIssuance.objects.filter(material_type=mat).aggregate(
            t=Sum('num_bags_issued'))['t'] or 0
        dirty_raw[mat] = max(0, received - issued)

    # --- Clean Raw Store (post-cleaning, pre-production) ---
    clean_maize = _get_clean_store_balance('maize')
    clean_wheat = _get_clean_store_balance('wheat')

    # --- Finished Goods: balance per (material, size) ---
    sizes = [s for s, _ in PRODUCT_SIZE_CHOICES]
    fg_maize_rows = []
    fg_wheat_rows = []
    fg_totals_rows = []
    for size in sizes:
        # Query total accepted receipts directly by material_type
        maize_in = FinishedGoodsReceipt.objects.filter(
            product_size=size, material_type='maize', status='accepted'
        ).aggregate(t=Sum('qty_received'))['t'] or 0
        wheat_in = FinishedGoodsReceipt.objects.filter(
            product_size=size, material_type='wheat', status='accepted'
        ).aggregate(t=Sum('qty_received'))['t'] or 0
        
        # Query total accepted issuances by material_type
        maize_out = FinishedGoodsIssuance.objects.filter(
            product_size=size, material_type='maize', status='accepted'
        ).aggregate(t=Sum('qty_issued'))['t'] or 0
        wheat_out = FinishedGoodsIssuance.objects.filter(
            product_size=size, material_type='wheat', status='accepted'
        ).aggregate(t=Sum('qty_issued'))['t'] or 0
        
        # Calculate net balances (In - Out + Returns normally, but report simplifies to just In - Out)
        # Adding Returned back in for accuracy
        maize_ret = FinishedGoodsReturn.objects.filter(
            product_size=size, material_type='maize', status='accepted'
        ).aggregate(t=Sum('qty_returned'))['t'] or 0
        wheat_ret = FinishedGoodsReturn.objects.filter(
            product_size=size, material_type='wheat', status='accepted'
        ).aggregate(t=Sum('qty_returned'))['t'] or 0

        total_in = maize_in + wheat_in
        total_out = maize_out + wheat_out
        total_ret = maize_ret + wheat_ret
        net = max(0, total_in - total_out + total_ret)
        
        fg_maize_rows.append((size.upper(), maize_in))
        fg_wheat_rows.append((size.upper(), wheat_in))
        fg_totals_rows.append((size.upper(), net))


    # Zip into a single list of tuples for template iteration: (size, maize_in, wheat_in, net)
    fg_rows = [
        (m[0], m[1], w[1], t[1])
        for m, w, t in zip(fg_maize_rows, fg_wheat_rows, fg_totals_rows)
    ]

    return render(request, 'reports/store.html', {
        'current_user': user,
        'dirty_raw': dirty_raw,
        'clean_maize': clean_maize,
        'clean_wheat': clean_wheat,
        'fg_rows': fg_rows,
    })


@role_required('md')
def sales_report(request):
    user = get_current_user(request)
    f_from = request.GET.get('date_from', '')
    f_to = request.GET.get('date_to', '')
    f_person = request.GET.get('sales_person', '')

    from sales.models import SalesPerson, SalesPayment

    sales = SalesRecord.objects.all().order_by('-date', '-created_at')
    if f_from:
        sales = sales.filter(date__gte=f_from)
    if f_to:
        sales = sales.filter(date__lte=f_to)
    if f_person:
        sales = sales.filter(sales_person__name__icontains=f_person)

    total_value      = sum(float(r.total_value) for r in sales)
    total_commission = sum(float(r.commission_amount) for r in sales)
    total_net        = sum(float(r.net_payable) for r in sales)
    total_received   = sum(r.total_paid for r in sales)
    total_outstanding= sum(r.amount_outstanding for r in sales)

    all_persons = SalesPerson.objects.all().order_by('name')

    return render(request, 'reports/sales.html', {
        'current_user': user,
        'sales': sales,
        'total_value': total_value,
        'total_commission': total_commission,
        'total_net': total_net,
        'total_received': total_received,
        'total_outstanding': total_outstanding,
        'all_persons': all_persons,
        'f_from': f_from, 'f_to': f_to, 'f_person': f_person,
    })


@role_required('manager', 'md')
def outstanding_report(request):
    user = get_current_user(request)

    # Production Balances: raw bags issued to a production officer but not yet milled
    from accounts.models import User
    from sales.views import get_sm_goods_holding, get_sm_money_outstanding
    from sales.models import SalesManagerCollection
    prod_users = User.objects.filter(role='production_officer', status='active')
    prod_balances = []
    for u in prod_users:
        accepted = CleanRawIssuance.objects.filter(issued_to=u, status='accepted').aggregate(t=Sum('num_bags'))['t'] or 0
        milled = MillingBatch.objects.filter(production_officer=u).aggregate(t=Sum('bags_milled_new'))['t'] or 0
        returned = CleanRawReturn.objects.filter(returned_by=u, status__in=['pending', 'accepted']).aggregate(t=Sum('num_bags'))['t'] or 0
        bal = max(0, accepted - milled - returned)
        if bal > 0:
            prod_balances.append({'user': u, 'balance': bal})

    # Sales Balances: money outstanding per Sales Manager (new flow)
    sales_managers = User.objects.filter(role='sales_manager', status='active').order_by('full_name')
    sales_balances = []
    for sm in sales_managers:
        goods_holding = get_sm_goods_holding(sm)
        money_out = get_sm_money_outstanding(sm)
        record_count = SalesManagerCollection.objects.filter(sales_manager=sm).count()
        
        if goods_holding > 0 or money_out > 0:
            sales_balances.append({
                'sm': sm,
                'goods_holding': goods_holding,
                'outstanding': money_out,
                'record_count': record_count,
            })

    recon_flags = ReconciliationFlag.objects.filter(resolved=False).order_by('-date', '-created_at')
    return render(request, 'reports/outstanding.html', {
        'current_user': user,
        'prod_outstanding': prod_balances,
        'sales_balances': sales_balances,
        'recon_flags': recon_flags,
    })


@role_required('manager', 'md')
def company_flow(request):
    """Full goods-to-money pipeline. Money totals only visible to MD."""
    user = get_current_user(request)
    show_money = (user.role == 'md')

    from clean_store.views import _get_clean_store_balance
    from finished_store.views import _fg_balance
    from procurement.models import RawMaterialReceipt, RawMaterialIssuance
    from accounts.models import User
    from sales.views import get_sm_goods_holding, get_sm_money_outstanding, get_gm_goods_holding
    from sales.models import SalesManagerCollection, SalesManagerPayment, SalesRecord, CompanyRetailLedger
    from production.models import BrandSale

    # Stage 1: Raw Store
    raw_maize_in  = RawMaterialReceipt.objects.filter(material_type='maize').aggregate(t=Sum('num_bags'))['t'] or 0
    raw_wheat_in  = RawMaterialReceipt.objects.filter(material_type='wheat').aggregate(t=Sum('num_bags'))['t'] or 0
    raw_maize_out = RawMaterialIssuance.objects.filter(material_type='maize').aggregate(t=Sum('num_bags_issued'))['t'] or 0
    raw_wheat_out = RawMaterialIssuance.objects.filter(material_type='wheat').aggregate(t=Sum('num_bags_issued'))['t'] or 0
    raw_maize_bal = max(0, raw_maize_in - raw_maize_out)
    raw_wheat_bal = max(0, raw_wheat_in - raw_wheat_out)

    # Stage 2: Clean Store
    from cleaning.models import CleanRawReceipt
    clean_maize_in  = CleanRawReceipt.objects.filter(material_type='maize').aggregate(t=Sum('num_bags'))['t'] or 0
    clean_wheat_in  = CleanRawReceipt.objects.filter(material_type='wheat').aggregate(t=Sum('num_bags'))['t'] or 0
    clean_maize_bal = _get_clean_store_balance('maize')
    clean_wheat_bal = _get_clean_store_balance('wheat')
    clean_maize_out = CleanRawIssuance.objects.filter(material_type='maize').aggregate(t=Sum('num_bags'))['t'] or 0
    clean_wheat_out = CleanRawIssuance.objects.filter(material_type='wheat').aggregate(t=Sum('num_bags'))['t'] or 0

    # Stage 3: Production
    total_bags_milled_new = MillingBatch.objects.aggregate(t=Sum('bags_milled_new'))['t'] or 0
    total_bags_milled_old = MillingBatch.objects.aggregate(t=Sum('outstanding_bags_milled'))['t'] or 0
    total_powder_kg       = float(MillingBatch.objects.aggregate(t=Sum('bulk_powder_kg'))['t'] or 0)
    total_powder_used     = float(PackagingBatch.objects.aggregate(t=Sum('powder_used_kg'))['t'] or 0)
    total_sacks_produced  = PackagingBatch.objects.aggregate(t=Sum('qty_10kg'))['t'] or 0
    powder_bal_kg         = max(0.0, total_powder_kg - total_powder_used)

    prod_users = User.objects.filter(role='production_officer', status='active')
    prod_officer_rows = []
    for u in prod_users:
        acc = CleanRawIssuance.objects.filter(issued_to=u, status='accepted').aggregate(t=Sum('num_bags'))['t'] or 0
        mld = MillingBatch.objects.filter(production_officer=u).aggregate(a=Sum('bags_milled_new'), b=Sum('outstanding_bags_milled'))
        mld_total = (mld['a'] or 0) + (mld['b'] or 0)
        ret = CleanRawReturn.objects.filter(returned_by=u, status__in=['pending', 'accepted']).aggregate(t=Sum('num_bags'))['t'] or 0
        bal = max(0, acc - mld_total - ret)
        prod_officer_rows.append({'user': u, 'accepted': acc, 'milled': mld_total, 'returned': ret, 'balance': bal})

    # Stage 4: Finished Goods Store
    fg_in  = FinishedGoodsReceipt.objects.aggregate(t=Sum('qty_received'))['t'] or 0
    fg_out = FinishedGoodsIssuance.objects.aggregate(t=Sum('qty_issued'))['t'] or 0
    fg_bal = _fg_balance('maize', '10kg') + _fg_balance('wheat', '10kg')

    # Stage 5: Brand Sales & Byproducts
    brand_sales = BrandSale.objects.all()
    total_brand_sacks = brand_sales.aggregate(t=Sum('qty_sacks'))['t'] or 0
    brand_sales_value = float(brand_sales.aggregate(t=Sum('total_amount'))['t'] or 0)
    brand_received    = float(brand_sales.aggregate(t=Sum('amount_cash'))['t'] or 0) + float(brand_sales.aggregate(t=Sum('amount_transfer'))['t'] or 0)
    brand_outstanding = max(0, brand_sales_value - brand_received)

    # Stage 6: Sales -> Money (Sales Manager Level)
    sales_managers = User.objects.filter(role='sales_manager', status='active').order_by('full_name')
    sm_rows = []
    total_sacks_collected   = 0
    total_goods_outstanding = 0
    total_money_outstanding = 0
    total_money_received    = 0
    total_sales_value       = 0

    for sm in sales_managers:
        # Goods collected (accepted)
        collections = SalesManagerCollection.objects.filter(sales_manager=sm, status='accepted')
        collected = sum(c.qty_sacks for c in collections)
        sales_val = sum(c.total_value for c in collections)
        
        # Money received (confirmed)
        payments = SalesManagerPayment.objects.filter(sales_manager=sm, status='confirmed')
        received = sum(p.total for p in payments)
        
        goods_bal = get_sm_goods_holding(sm)
        money_out = get_sm_money_outstanding(sm)

        total_sacks_collected   += collected
        total_goods_outstanding += goods_bal
        total_money_outstanding += money_out
        total_money_received    += received
        total_sales_value       += sales_val

        sm_rows.append({
            'sm': sm, 'collected': collected,
            'goods_balance': goods_bal, 'money_outstanding': money_out,
            'money_received': received, 'total_sales_value': sales_val,
        })

    # GM Direct Sales Context
    gm_maize_hand = get_gm_goods_holding('maize')
    gm_wheat_hand = get_gm_goods_holding('wheat')
    gm_maize_pieces = CompanyRetailLedger.objects.filter(material_type='maize').aggregate(t=Sum('pieces_changed'))['t'] or 0
    gm_wheat_pieces = CompanyRetailLedger.objects.filter(material_type='wheat').aggregate(t=Sum('pieces_changed'))['t'] or 0
    
    gm_sales = SalesRecord.objects.filter(channel='company')
    gm_revenue = float(gm_sales.aggregate(t=Sum('total_value'))['t'] or 0)
    gm_received = gm_revenue 
        
    company_total_revenue = float(total_sales_value) + float(brand_sales_value) + gm_revenue
    company_received_money = float(total_money_received) + float(brand_received) + gm_received
    company_outstanding_money = float(total_money_outstanding) + float(brand_outstanding)

    return render(request, 'reports/company_flow.html', {
        'current_user': user, 'show_money': show_money,
        'raw_maize_in': raw_maize_in, 'raw_wheat_in': raw_wheat_in,
        'raw_maize_out': raw_maize_out, 'raw_wheat_out': raw_wheat_out,
        'raw_maize_bal': raw_maize_bal, 'raw_wheat_bal': raw_wheat_bal,
        'clean_maize_in': clean_maize_in, 'clean_wheat_in': clean_wheat_in,
        'clean_maize_out': clean_maize_out, 'clean_wheat_out': clean_wheat_out,
        'clean_maize_bal': clean_maize_bal, 'clean_wheat_bal': clean_wheat_bal,
        'total_bags_milled': total_bags_milled_new + total_bags_milled_old,
        'total_powder_kg': total_powder_kg, 'total_powder_used': total_powder_used,
        'powder_bal_kg': powder_bal_kg, 'total_sacks_produced': total_sacks_produced,
        'prod_officer_rows': prod_officer_rows,
        'fg_in': fg_in, 'fg_out': fg_out, 'fg_bal': fg_bal,
        'total_brand_sacks': total_brand_sacks, 'brand_sales_value': brand_sales_value,
        'brand_received': brand_received, 'brand_outstanding': brand_outstanding,
        'sm_rows': sm_rows,
        'total_sacks_collected': total_sacks_collected,
        'total_goods_outstanding': total_goods_outstanding,
        'total_money_outstanding': total_money_outstanding,
        'total_money_received': total_money_received,
        'total_sales_value': total_sales_value,
        'gm_maize_hand': gm_maize_hand, 'gm_wheat_hand': gm_wheat_hand,
        'gm_maize_pieces': gm_maize_pieces, 'gm_wheat_pieces': gm_wheat_pieces,
        'gm_revenue': gm_revenue,
        'company_total_revenue': company_total_revenue,
        'company_received_money': company_received_money,
        'company_outstanding_money': company_outstanding_money,
    })


@role_required('md')
def md_insights(request):
    """
    MD Dashboard: high level insights, charts, period analysis. Phase 8.
    """
    user = get_current_user(request)

    from procurement.models import RawMaterialReceipt
    from clean_store.views import _get_clean_store_balance
    from finished_store.views import _fg_balance
    from sales.models import SalesManagerCollection, SalesManagerPayment, SalesPerson, SalesDistributionRecord, SalesResult
    from accounts.models import User
    from production.models import BrandSale
    import json
    from django.db.models.functions import TruncMonth

    # 1. Total Store Summary Layer (No money shown here)
    dirty_maize = RawMaterialReceipt.objects.filter(material_type='maize').aggregate(t=Sum('num_bags'))['t'] or 0
    clean_maize = _get_clean_store_balance('maize')
    fg_maize    = _fg_balance('maize', '10kg')

    dirty_wheat = RawMaterialReceipt.objects.filter(material_type='wheat').aggregate(t=Sum('num_bags'))['t'] or 0
    clean_wheat = _get_clean_store_balance('wheat')
    fg_wheat    = _fg_balance('wheat', '10kg')

    # 2. Who is holding what
    sales_managers = User.objects.filter(role='sales_manager', status='active')
    sm_holdings = []
    for sm in sales_managers:
        from sales.views import get_sm_goods_holding, get_sm_money_outstanding
        goods = get_sm_goods_holding(sm)
        money = get_sm_money_outstanding(sm)
        if goods > 0 or money > 0:
            sm_holdings.append({
                'name': sm.full_name,
                'goods': goods,
                'money': money
            })

    # 3. Best/Worst Sales Persons (Performance)
    all_sps = SalesPerson.objects.filter(status='active')
    sp_ranks = []
    for sp in all_sps:
        issued = SalesDistributionRecord.objects.filter(sales_person=sp).aggregate(t=Sum('qty_given'))['t'] or 0
        sold = SalesResult.objects.filter(distribution__sales_person=sp).aggregate(t=Sum('qty_sold'))['t'] or 0
        pct = (sold / issued * 100) if issued > 0 else 0
        if issued > 0:
            sp_ranks.append({
                'name': sp.name,
                'channel': sp.get_channel_display(),
                'issued': issued,
                'sold': sold,
                'pct': round(pct, 1)
            })
    sp_ranks.sort(key=lambda x: x['sold'], reverse=True)
    top_sps = sp_ranks[:5]

    # 4. Chart Data: Monthly Sales vs Collections
    # Group accepted collections by month
    monthly_colls = SalesManagerCollection.objects.filter(status='accepted').annotate(
        month=TruncMonth('date')
    ).values('month').annotate(total=Sum('qty_sacks')).order_by('month')

    monthly_sales = SalesResult.objects.annotate(
        month=TruncMonth('date')
    ).values('month').annotate(total=Sum('qty_sold')).order_by('month')

    months_list = []
    colls_list = []
    sales_list = []

    # Simple merging for charts (assuming current year focus)
    this_year = datetime.date.today().year
    month_names = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
    
    # Initialize 12 months with 0
    chart_data = {m: {'colls': 0, 'sales': 0} for m in month_names}

    for c in monthly_colls:
        if c['month'] and c['month'].year == this_year:
            m_name = c['month'].strftime('%b')
            if m_name in chart_data:
                chart_data[m_name]['colls'] = c['total']
                
    for s in monthly_sales:
        if s['month'] and s['month'].year == this_year:
            m_name = s['month'].strftime('%b')
            if m_name in chart_data:
                chart_data[m_name]['sales'] = s['total']

    for m in month_names:
        months_list.append(m)
        colls_list.append(chart_data[m]['colls'])
        sales_list.append(chart_data[m]['sales'])

    # 4b. Chart Data: Weekly Sales vs Collections (Current Month)
    today = datetime.date.today()
    this_month = today.month
    
    current_month_colls = SalesManagerCollection.objects.filter(status='accepted', date__year=this_year, date__month=this_month)
    current_month_sales = SalesResult.objects.filter(date__year=this_year, date__month=this_month)
    
    weeks_list = ['Week 1', 'Week 2', 'Week 3', 'Week 4', 'Week 5']
    weekly_chart_data = {w: {'colls': 0, 'sales': 0} for w in weeks_list}
    
    for c in current_month_colls:
        if c.date:
            w_idx = (c.date.day - 1) // 7
            w_name = f'Week {w_idx + 1}'
            if w_name in weekly_chart_data:
                weekly_chart_data[w_name]['colls'] += c.qty_sacks
            
    for s in current_month_sales:
        if s.date:
            w_idx = (s.date.day - 1) // 7
            w_name = f'Week {w_idx + 1}'
            if w_name in weekly_chart_data:
                weekly_chart_data[w_name]['sales'] += s.qty_sold
                
    w_colls_list = [weekly_chart_data[w]['colls'] for w in weeks_list]
    w_sales_list = [weekly_chart_data[w]['sales'] for w in weeks_list]

    # 5. Brand Recovery
    brand_sales = BrandSale.objects.all()
    brand_revenue = float(brand_sales.aggregate(t=Sum('total_amount'))['t'] or 0)
    brand_received = float(brand_sales.aggregate(t=Sum('amount_cash'))['t'] or 0) + float(brand_sales.aggregate(t=Sum('amount_transfer'))['t'] or 0)
    brand_outstanding = max(0, brand_revenue - brand_received)

    # 6. Product Sales Mix (Maize vs Wheat)
    from sales.models import SalesResult
    prod_mix = SalesResult.objects.values('material_type').annotate(total=Sum('qty_sold')).order_by('material_type')
    product_labels = [p['material_type'].title() for p in prod_mix]
    product_data = [p['total'] for p in prod_mix]


    context = {
        'current_user': user,
        'dirty_maize': dirty_maize,
        'clean_maize': clean_maize,
        'fg_maize': fg_maize,
        'dirty_wheat': dirty_wheat,
        'clean_wheat': clean_wheat,
        'fg_wheat': fg_wheat,
        'sm_holdings': sm_holdings,
        'top_sps': top_sps,
        'months_json': json.dumps(months_list),
        'colls_json': json.dumps(colls_list),
        'sales_json': json.dumps(sales_list),
        'weeks_json': json.dumps(weeks_list),
        'w_colls_json': json.dumps(w_colls_list),
        'w_sales_json': json.dumps(w_sales_list),
        'brand_revenue': brand_revenue,
        'brand_received': brand_received,
        'brand_outstanding': brand_outstanding,
        'product_labels_json': json.dumps(product_labels),
        'product_data_json': json.dumps(product_data),
        'this_year': this_year,
        'this_month_name': today.strftime('%B'),
    }

    return render(request, 'reports/md_insights.html', context)
