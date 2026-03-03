from django.shortcuts import render, redirect
from django.contrib import messages
from accounts.mixins import get_current_user, role_required
from audit.utils import log_action
from pricing.models import PriceConfig, CommissionConfig, SalesTarget
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
    return render(request, 'pricing/list.html', {'current_user': user, 'prices': prices})


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
                log_action(request, user, 'pricing', 'SET_PRICE',
                           f'Price: {channel}/{material_type}/{product_size} = ₦{price_per_unit} from {effective_from}',
                           'PriceConfig', price.pk)
                messages.success(request, f'Price saved: {material_type.title()} {product_size} ({channel}) → ₦{price_per_unit:,.2f} from {effective_from}.')
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
            month = int(request.POST.get('month'))
            year = int(request.POST.get('year'))
            target_qty = int(request.POST.get('target_qty', 0))
            notes = request.POST.get('notes', '').strip()

            sm = User.objects.get(pk=sm_id, role='sales_manager')
            if target_qty <= 0:
                error = 'Target quantity must be greater than zero.'
            else:
                obj, created = SalesTarget.objects.update_or_create(
                    sales_manager=sm, material_type=material_type,
                    product_size=product_size, month=month, year=year,
                    defaults={'target_qty': target_qty, 'created_by': user, 'notes': notes},
                )
                log_action(request, user, 'pricing', 'SET_TARGET',
                           f'Target: {sm.full_name} | {material_type}/{product_size} | {month}/{year} = {target_qty} sacks',
                           'SalesTarget', obj.pk)
                messages.success(request, f'Target {"updated" if not created else "set"}: {sm.full_name} → {target_qty} sacks of {material_type} {product_size} for {month}/{year}.')
                return redirect('pricing:targets')
        except Exception as e:
            error = f'Error: {str(e)}'

    now = datetime.date.today()
    return render(request, 'pricing/new_target.html', {
        'current_user': user, 'error': error,
        'sales_managers': sales_managers,
        'size_choices': PRODUCT_SIZE_CHOICES,
        'material_choices': MATERIAL_CHOICES,
        'current_month': now.month,
        'current_year': now.year,
    })
