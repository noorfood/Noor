from django.shortcuts import render, redirect
from django.contrib import messages
from accounts.mixins import get_current_user, role_required
from audit.utils import log_action
from pricing.models import PriceConfig, CommissionConfig, SalesTarget, OperationalExpense
from finished_store.models import PRODUCT_SIZE_CHOICES, CHANNEL_CHOICES
from procurement.models import MATERIAL_CHOICES
from accounts.models import User
import datetime


COMMISSION_CHANNEL_CHOICES = [
    ('sales_team', 'Sales Team'),
]


# ─────────────────────────────────────────────────────────────────────────────
# PRICE CONFIGURATION
# ─────────────────────────────────────────────────────────────────────────────

@role_required('md')
def list_prices(request):
    user = get_current_user(request)
    prices = PriceConfig.objects.all().order_by('-effective_from', 'channel', 'material_type', 'product_size')
    
    from procurement.models import RawMaterialReceipt
    pending_costs = RawMaterialReceipt.objects.filter(cost_status='pending').order_by('-date', '-created_at')
    
    return render(request, 'pricing/list.html', {
        'current_user': user, 
        'prices': prices,
        'pending_costs': pending_costs,
    })


@role_required('md')
def new_price(request):
    user = get_current_user(request)
    error = None

    if request.method == 'POST':
        try:
            channel = request.POST.get('channel')
            material_type = request.POST.get('material_type')
            product_size = '10kg'
            price_per_unit = float(request.POST.get('price_per_unit', 0))
            effective_from = request.POST.get('effective_from')
            notes = request.POST.get('notes', '').strip()

            if not channel or not material_type or price_per_unit <= 0 or not effective_from:
                error = 'All fields are required with valid values.'
            else:
                price = PriceConfig.objects.create(
                    channel=channel, material_type=material_type,
                    product_size=product_size, price_per_unit=price_per_unit,
                    effective_from=effective_from, created_by=user, notes=notes,
                )
                
                # Retroactive Price Update Magic
                from sales.models import SalesManagerCollection, DirectSalePayment
                eff_date = price.effective_from
                updated_count = 0
                
                if channel == 'sales_manager':
                    collections = SalesManagerCollection.objects.filter(date__gte=eff_date, material_type=material_type)
                    for c in collections:
                        c.price_per_sack = price_per_unit
                        c.total_value = float(price_per_unit) * c.qty_sacks
                        c.save(update_fields=['price_per_sack', 'total_value'])
                        updated_count += 1
                elif channel == 'company':
                    direct_sales = DirectSalePayment.objects.filter(date__gte=eff_date, material_type=material_type, product_size=product_size)
                    for ds in direct_sales:
                        ds.unit_price = price_per_unit
                        ds.total_sale_value = float(price_per_unit) * ds.qty_sold
                        ds.save(update_fields=['unit_price', 'total_sale_value'])
                        updated_count += 1

                log_action(request, user, 'pricing', 'SET_PRICE',
                           f'Price: {channel}/{material_type}/{product_size} = ₦{price_per_unit} from {effective_from}. Auto-updated {updated_count} records.',
                           'PriceConfig', price.pk)
                
                msg = f'Price saved: {material_type.title()} {product_size} ({channel}) → ₦{price_per_unit:,.2f} from {effective_from}.'
                if updated_count > 0:
                    msg += f' Proactively applied to {updated_count} existing transactions.'
                messages.success(request, msg)
                
                return redirect('pricing:list')
        except Exception as e:
            error = f'Error: {str(e)}'

    return render(request, 'pricing/new_price.html', {
        'current_user': user, 'error': error,
        'today': datetime.date.today().isoformat(),
        'size_choices': PRODUCT_SIZE_CHOICES,
        'channel_choices': [
            ('sales_manager', 'Sales Manager'),
            ('company', 'Company Direct'),
        ],
        'material_choices': MATERIAL_CHOICES,
    })


# ─────────────────────────────────────────────────────────────────────────────
# COMMISSION CONFIGURATION
# ─────────────────────────────────────────────────────────────────────────────

@role_required('md')
def list_commissions(request):
    user = get_current_user(request)
    configs = CommissionConfig.objects.all().order_by('-effective_from', 'channel', 'material_type', 'product_size')
    return render(request, 'pricing/commissions.html', {'current_user': user, 'configs': configs})


@role_required('md')
def new_commission(request):
    user = get_current_user(request)
    error = None

    if request.method == 'POST':
        try:
            channel = request.POST.get('channel')
            material_type = request.POST.get('material_type')
            product_size = '10kg'
            commission_pct = float(request.POST.get('commission_pct', 0))
            effective_from = request.POST.get('effective_from')
            notes = request.POST.get('notes', '').strip()

            if not channel or not material_type or commission_pct < 0 or not effective_from:
                error = 'All fields are required.'
            else:
                cfg = CommissionConfig.objects.create(
                    channel=channel, material_type=material_type,
                    product_size=product_size, commission_pct=commission_pct,
                    effective_from=effective_from, created_by=user, notes=notes,
                )
                log_action(request, user, 'pricing', 'SET_COMMISSION',
                           f'Commission: {channel}/{material_type}/{product_size} = {commission_pct}% from {effective_from}',
                           'CommissionConfig', cfg.pk)
                messages.success(request, f'Commission saved: {commission_pct}% for {material_type.title()} {product_size} ({channel}) from {effective_from}.')
                return redirect('pricing:commissions')
        except Exception as e:
            error = f'Error: {str(e)}'

    return render(request, 'pricing/new_commission.html', {
        'current_user': user, 'error': error,
        'today': datetime.date.today().isoformat(),
        'size_choices': PRODUCT_SIZE_CHOICES,
        'channel_choices': COMMISSION_CHANNEL_CHOICES,
        'material_choices': MATERIAL_CHOICES,
    })


# ─────────────────────────────────────────────────────────────────────────────
# SALES TARGET CONFIGURATION
# ─────────────────────────────────────────────────────────────────────────────

@role_required('md')
def list_targets(request):
    user = get_current_user(request)
    targets = SalesTarget.objects.all().order_by('-year', '-month', 'sales_manager__full_name')
    return render(request, 'pricing/targets.html', {'current_user': user, 'targets': targets})


@role_required('md')
def new_target(request):
    user = get_current_user(request)
    error = None
    sales_managers = User.objects.filter(role='sales_manager', status='active').order_by('full_name')

    if request.method == 'POST':
        try:
            sm_id = request.POST.get('sales_manager_id')
            material_type = request.POST.get('material_type')
            product_size = '10kg'
            target_type = request.POST.get('target_type', 'monthly')
            year = int(request.POST.get('year'))
            target_qty = int(request.POST.get('target_qty', 0))
            notes = request.POST.get('notes', '').strip()

            month = None
            week = None
            if target_type == 'weekly':
                week = int(request.POST.get('week'))
            else:
                month = int(request.POST.get('month'))

            sm = User.objects.get(pk=sm_id, role='sales_manager')
            if target_qty <= 0:
                error = 'Target quantity must be greater than zero.'
            else:
                obj, created = SalesTarget.objects.update_or_create(
                    sales_manager=sm, material_type=material_type,
                    product_size=product_size, month=month, year=year,
                    week=week, target_type=target_type,
                    defaults={'target_qty': target_qty, 'created_by': user, 'notes': notes},
                )
                log_action(request, user, 'pricing', 'SET_TARGET',
                           f'Target: {sm.full_name} | {material_type}/{product_size} | {target_type} {week or month}/{year} = {target_qty} sacks',
                           'SalesTarget', obj.pk)
                messages.success(request, f'Target {"updated" if not created else "set"}: {sm.full_name} → {target_qty} sacks of {material_type} {product_size} for {target_type} {week or month}/{year}.')
                return redirect('pricing:targets')
        except Exception as e:
            error = f'Error: {str(e)}'

    now = datetime.date.today()
    current_week = now.isocalendar()[1]
    return render(request, 'pricing/new_target.html', {
        'current_user': user, 'error': error,
        'sales_managers': sales_managers,
        'size_choices': PRODUCT_SIZE_CHOICES,
        'material_choices': MATERIAL_CHOICES,
        'current_month': now.month,
        'current_year': now.year,
        'current_week': current_week,
    })


# ─────────────────────────────────────────────────────────────────────────────
# OPERATIONAL EXPENSES
# ─────────────────────────────────────────────────────────────────────────────

@role_required('md')
def list_expenses(request):
    user = get_current_user(request)
    expenses = OperationalExpense.objects.all().order_by('-date', '-created_at')
    from django.db.models import Sum
    total_expenses = expenses.aggregate(t=Sum('amount'))['t'] or 0
    return render(request, 'pricing/expenses.html', {
        'current_user': user,
        'expenses': expenses,
        'total_expenses': total_expenses,
    })


@role_required('md')
def new_expense(request):
    user = get_current_user(request)
    error = None

    if request.method == 'POST':
        try:
            date_val = request.POST.get('date')
            description = request.POST.get('description', '').strip()
            amount = float(request.POST.get('amount', 0))
            notes = request.POST.get('notes', '').strip()

            if not date_val or not description or amount <= 0:
                error = 'Please fill in all required fields with valid values.'
            else:
                exp = OperationalExpense.objects.create(
                    date=date_val,
                    description=description,
                    amount=amount,
                    notes=notes,
                    recorded_by=user,
                )
                log_action(request, user, 'pricing', 'NEW_EXPENSE',
                           f'Recorded expense: {description} | \u20a6{amount:,.0f}',
                           'OperationalExpense', exp.pk)
                messages.success(request, f'Expense recorded: {description} — \u20a6{amount:,.0f}')
                return redirect('pricing:expenses')
        except Exception as e:
            error = f'Error: {str(e)}'

    return render(request, 'pricing/new_expense.html', {
        'current_user': user,
        'error': error,
        'today': datetime.date.today().isoformat(),
    })


# ─────────────────────────────────────────────────────────────────────────────
# PACKAGING & MATERIAL COSTS (CONSTANT EXPENSES)
# ─────────────────────────────────────────────────────────────────────────────

@role_required('md')
def list_packaging_costs(request):
    user = get_current_user(request)
    from pricing.models import PackagingCostConfig, CleaningCostConfig, LabourCostConfig
    packaging_costs = PackagingCostConfig.objects.all().order_by('-effective_from')
    cleaning_costs = CleaningCostConfig.objects.all().order_by('-effective_from', 'material_type')
    labour_costs = LabourCostConfig.objects.all().order_by('-effective_from')
    return render(request, 'pricing/packaging_list.html', {
        'current_user': user,
        'costs': packaging_costs,
        'cleaning_costs': cleaning_costs,
        'labour_costs': labour_costs,
    })


@role_required('md')
def new_packaging_cost(request):
    user = get_current_user(request)
    from pricing.models import PackagingCostConfig
    error = None

    if request.method == 'POST':
        try:
            cost_per_sack = float(request.POST.get('cost_per_sack', 0))
            nylon_cost_per_piece = float(request.POST.get('nylon_cost_per_piece', 0))
            effective_from = request.POST.get('effective_from')
            notes = request.POST.get('notes', '').strip()

            if not effective_from:
                error = 'Effective date is required.'
            else:
                cost = PackagingCostConfig.objects.create(
                    cost_per_sack=cost_per_sack,
                    nylon_cost_per_piece=nylon_cost_per_piece,
                    effective_from=effective_from,
                    created_by=user,
                    notes=notes,
                )
                log_action(request, user, 'pricing', 'SET_PACKAGING_COST',
                           f'Set Packaging Costs (Global): Sack=₦{cost_per_sack}, Nylon=₦{nylon_cost_per_piece}',
                           'PackagingCostConfig', cost.pk)

                # Retroactive update for produced batches
                from production.models import PackagingBatch
                batches = PackagingBatch.objects.filter(date__gte=effective_from)
                for b in batches:
                    b.save()
                messages.success(request, f'Global packaging costs updated from {effective_from}.')
                return redirect('pricing:packaging_costs')
        except Exception as e:
            error = f'Error: {str(e)}'

    return render(request, 'pricing/new_packaging_cost.html', {
        'current_user': user,
        'error': error,
        'today': datetime.date.today().isoformat(),
    })


@role_required('md')
def new_cleaning_cost(request):
    user = get_current_user(request)
    from pricing.models import CleaningCostConfig
    from procurement.models import MATERIAL_CHOICES
    error = None

    if request.method == 'POST':
        try:
            material_type = request.POST.get('material_type')
            cleaning_cost_per_bag = float(request.POST.get('cleaning_cost_per_bag', 0))
            effective_from = request.POST.get('effective_from')
            notes = request.POST.get('notes', '').strip()

            if not material_type or not effective_from:
                error = 'Material type and effective date are required.'
            else:
                cost = CleaningCostConfig.objects.create(
                    material_type=material_type,
                    cleaning_cost_per_bag=cleaning_cost_per_bag,
                    effective_from=effective_from,
                    created_by=user,
                    notes=notes,
                )
                log_action(request, user, 'pricing', 'SET_CLEANING_COST',
                           f'Set Cleaning Cost for {material_type}: ₦{cleaning_cost_per_bag}',
                           'CleaningCostConfig', cost.pk)

                # Retroactive update for issuances
                from procurement.models import RawMaterialIssuance
                issuances = RawMaterialIssuance.objects.filter(material_type=material_type, date__gte=effective_from)
                for ri in issuances:
                    ri.save()
                messages.success(request, f'Cleaning fee updated for {material_type.title()} from {effective_from}.')
                return redirect('pricing:packaging_costs')
        except Exception as e:
            error = f'Error: {str(e)}'

    return render(request, 'pricing/new_cleaning_cost.html', {
        'current_user': user,
        'error': error,
        'material_choices': MATERIAL_CHOICES,
        'today': datetime.date.today().isoformat(),
    })


@role_required('md')
def new_labour_cost(request):
    user = get_current_user(request)
    from pricing.models import LabourCostConfig
    from sales.models import SalesResult, DirectSalePayment
    error = None

    if request.method == 'POST':
        try:
            labour_cost_per_sack = float(request.POST.get('labour_cost_per_sack', 0))
            effective_from = request.POST.get('effective_from')
            notes = request.POST.get('notes', '').strip()

            if not effective_from:
                error = 'Effective date is required.'
            else:
                cost = LabourCostConfig.objects.create(
                    labour_cost_per_sack=labour_cost_per_sack,
                    effective_from=effective_from,
                    created_by=user,
                    notes=notes,
                )
                
                # Retroactive Labour Update
                eff_date = cost.effective_from
                updated_count = 0
                
                # 1. Update SM Sales Results
                results = SalesResult.objects.filter(date__gte=eff_date)
                for r in results:
                    r.labour_unit_cost = labour_cost_per_sack
                    r.save() # This auto-recalculates total_labour_cost
                    updated_count += 1
                
                # 2. Update Direct Sales
                direct_sales = DirectSalePayment.objects.filter(date__gte=eff_date)
                for ds in direct_sales:
                    ds.labour_unit_cost = labour_cost_per_sack
                    ds.save()
                    updated_count += 1

                log_action(request, user, 'pricing', 'SET_LABOUR_COST',
                           f'Set Labour Cost (Global): ₦{labour_cost_per_sack}. Auto-updated {updated_count} records.',
                           'LabourCostConfig', cost.pk)
                
                msg = f'General labour cost updated from {effective_from}.'
                if updated_count > 0:
                    msg += f' Applied to {updated_count} existing transactions.'
                messages.success(request, msg)
                return redirect('pricing:packaging_costs')
        except Exception as e:
            error = f'Error: {str(e)}'

    return render(request, 'pricing/new_labour_cost.html', {
        'current_user': user,
        'error': error,
        'today': datetime.date.today().isoformat(),
    })

