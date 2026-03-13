from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.db.models import Sum
from accounts.mixins import get_current_user, role_required
from accounts.models import User
from audit.utils import log_action
from reconciliation.models import MoneyReceipt, ReconciliationFlag
from sales.models import SalesRecord, SalesPerson, SalesPayment, SalesResult, SalesDistributionRecord
import datetime


@role_required('sales_manager', 'manager', 'md')
def dashboard(request):
    user = get_current_user(request)
    # Recent receipts physically collected
    receipts = MoneyReceipt.objects.all().order_by('-date', '-created_at')[:10]
    flags = ReconciliationFlag.objects.filter(resolved=False).order_by('-date', '-created_at')[:5]

    # Overall Stats
    # Actual money collected from personnel: Remittances + Initial Handovers
    remittances = MoneyReceipt.objects.aggregate(t=Sum('cash_received') + Sum('transfer_received'))['t'] or 0
    initial_handovers = SalesResult.objects.aggregate(t=Sum('amount_returned'))['t'] or 0
    total_actual = float(remittances) + float(initial_handovers)
    
    # Expected money from sales results
    total_expected = SalesResult.objects.aggregate(t=Sum('net_due_to_company'))['t'] or 0

    return render(request, 'reconciliation/dashboard.html', {
        'current_user': user,
        'receipts': receipts,
        'flags': flags,
        'total_actual': float(total_actual),
        'total_expected': float(total_expected),
        'total_diff': float(total_expected) - float(total_actual),
    })


@role_required('sales_manager')
def record_money(request):
    user = get_current_user(request)
    sales_persons = SalesPerson.objects.filter(status='active').order_by('name')
    error = None
    preselected_sp_id = request.GET.get('sp')

    if request.method == 'POST':
        try:
            date_val = request.POST.get('date')
            sp_id = request.POST.get('sales_person_id')
            cash_received = float(request.POST.get('cash_received') or 0)
            transfer_received = float(request.POST.get('transfer_received') or 0)
            notes = request.POST.get('notes', '').strip()
            period_start = request.POST.get('period_start')
            period_end = request.POST.get('period_end')

            if not date_val or not sp_id:
                error = 'Date and Sales Person are required.'
            elif cash_received == 0 and transfer_received == 0:
                error = 'At least one of cash or transfer received must be greater than zero.'
            else:
                sp = get_object_or_404(SalesPerson, pk=sp_id)
                receipt = MoneyReceipt.objects.create(
                    date=date_val,
                    sales_manager=user,
                    sales_person=sp,
                    cash_received=cash_received,
                    transfer_received=transfer_received,
                    notes=notes,
                    is_locked=True,
                )
                log_action(request, user, 'reconciliation', 'RECORD_MONEY',
                           f'Received ₦{cash_received + transfer_received:,.2f} from {sp.name}',
                           'MoneyReceipt', receipt.pk)

                # Auto-check reconciliation if period provided
                if period_start and period_end:
                    # Expected from SalesResults
                    results_in_period = SalesResult.objects.filter(
                        sales_person=sp,
                        date__gte=period_start,
                        date__lte=period_end
                    )
                    expected = sum(float(r.net_due_to_company) for r in results_in_period)

                    # Actual from Money Receipts
                    recon_receipts = MoneyReceipt.objects.filter(
                        sales_person=sp,
                        date__gte=period_start,
                        date__lte=period_end
                    )
                    actual = float(recon_receipts.aggregate(t=Sum('cash_received') + Sum('transfer_received'))['t'] or 0)

                    diff = expected - actual
                    if abs(diff) > 0.01:
                        ReconciliationFlag.objects.create(
                            date=date_val,
                            sales_person=sp,
                            period_start=period_start,
                            period_end=period_end,
                            expected_amount=expected,
                            actual_amount=actual,
                            difference=diff,
                            flagged_by=user,
                            notes=f'Auto-flagged. Expected ₦{expected:,.2f} (from sales results), received ₦{actual:,.2f}',
                        )
                        messages.warning(request, f'Money saved. ⚠ Discrepancy detected: ₦{diff:,.2f} difference flagged.')
                    else:
                        messages.success(request, f'Money receipt saved. Reconciliation matches for {sp.name}.')
                else:
                    messages.success(request, f'Money receipt saved.')
                return redirect('reconciliation:list')
        except Exception as e:
            error = f'Error: {str(e)}'

    return render(request, 'reconciliation/record_money.html', {
        'current_user': user,
        'sales_persons': sales_persons,
        'error': error,
        'preselected_sp_id': preselected_sp_id,
        'today': datetime.date.today().isoformat(),
    })


@role_required('sales_manager', 'manager', 'md')
def list_view(request):
    """
    Detailed Recon Hub:
    Finance: SalesResult.net_due (Expected) vs MoneyReceipt (Actual)
    Stock: SalesDistributionRecord (Given) vs SalesResult (Sold)
    """
    user = get_current_user(request)

    f_sp = request.GET.get('sp', '')
    all_persons = SalesPerson.objects.all().order_by('name')

    rows = []
    
    persons_qs = SalesPerson.objects.all().order_by('name')
    if f_sp:
        persons_qs = persons_qs.filter(pk=f_sp)
    elif user.role == 'sales_manager':
        # SM only sees their own team — persons they have distributed to or recorded results for
        my_sp_ids = list(
            SalesDistributionRecord.objects.filter(recorded_by=user).values_list('sales_person_id', flat=True).distinct()
        )
        persons_qs = persons_qs.filter(pk__in=my_sp_ids)

    for sp in persons_qs:
        # 1. Finance (Include initial handovers from SalesResult)
        results_qs = SalesResult.objects.filter(sales_person=sp)
        expected_finance = float(results_qs.aggregate(t=Sum('net_due_to_company'))['t'] or 0)
        
        remitted = float(MoneyReceipt.objects.filter(sales_person=sp).aggregate(t=Sum('cash_received') + Sum('transfer_received'))['t'] or 0)
        initial_paid = float(results_qs.aggregate(t=Sum('amount_returned'))['t'] or 0)
        actual_finance = remitted + initial_paid
        
        # 2. Stock (Use piece conversion 10:1)
        total_given = float(SalesDistributionRecord.objects.filter(sales_person=sp).aggregate(t=Sum('qty_given'))['t'] or 0)
        
        # We iterate over results to get piece-accurate totals
        total_sold  = sum(r.equivalent_sacks_sold for r in results_qs)
        total_ret   = sum(r.equivalent_sacks_returned for r in results_qs)
        
        if expected_finance == 0 and total_given == 0:
            continue # Skip if no activity

        rows.append({
            'sp': sp,
            'expected_finance': expected_finance,
            'actual_finance': actual_finance,
            'finance_diff': expected_finance - actual_finance,
            'total_given': total_given,
            'total_sold': total_sold,
            'total_ret': total_ret,
            'stock_diff': total_given - total_sold - total_ret,
            'status': 'settled' if (expected_finance - actual_finance) <= 0.01 else 'pending',
        })

    # Global Summaries
    grand_expected = sum(r['expected_finance'] for r in rows)
    grand_actual   = sum(r['actual_finance'] for r in rows)
    grand_given    = sum(r['total_given'] for r in rows)
    grand_sold     = sum(r['total_sold'] for r in rows)
    grand_ret      = sum(r['total_ret'] for r in rows)

    return render(request, 'reconciliation/list.html', {
        'current_user': user,
        'rows': rows,
        'all_persons': all_persons,
        'f_sp': f_sp,
        'grand_expected': grand_expected,
        'grand_actual': grand_actual,
        'grand_diff': grand_expected - grand_actual,
        'grand_given': grand_given,
        'grand_sold': grand_sold,
        'grand_stock_diff': grand_given - grand_sold - grand_ret,
    })


@role_required('sales_manager', 'manager', 'md')
def flags_view(request):
    user = get_current_user(request)
    flags = ReconciliationFlag.objects.all().order_by('-date', '-created_at')
    open_count = flags.filter(resolved=False).count()
    resolved_count = flags.filter(resolved=True).count()
    return render(request, 'reconciliation/flags.html', {
        'current_user': user,
        'flags': flags,
        'open_count': open_count,
        'resolved_count': resolved_count,
    })
