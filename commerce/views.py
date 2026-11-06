from decimal import Decimal
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from accounts.mixins import forbidden_response
from django.shortcuts import get_object_or_404, redirect, render
from audit.utils import log_action
from bag_stock.models import SalesManagerStock
from operations.views import access
from .forms import SaleForm, CustomerPaymentForm
from .models import ReportedSale, ReportedCustomerPayment
from .services import record_sale, record_customer_payment

@access('sales_manager','manager','md')
def home(request):
    user=request.ops_user
    sales=ReportedSale.objects.select_related('recorded_by')
    if user.role=='sales_manager':sales=sales.filter(recorded_by=user)
    return render(request,'commerce/home.html',{'current_user':user,'sales':sales[:25], 'can_record':user.role=='sales_manager'})

@access('sales_manager')
def create_sale(request):
    user=request.ops_user
    form=SaleForm(request.POST or None)
    if request.method=='POST' and form.is_valid():
        d=form.cleaned_data
        try:
            with transaction.atomic():
                item=record_sale(actor=user,key=d['request_key'],date=d['date'],material=d['material'],pack_size_kg=d['pack_size_kg'],packs=d['packs'],unit_price=d['unit_price'],buyer=d['buyer'],notes=d['notes'])
                log_action(request,user,'commerce','REPORT_SALE','Report customer sale','ReportedSale',item.pk)
            holdings_now=SalesManagerStock.objects.filter(officer=user,material=d['material'],pack_size_kg=d['pack_size_kg']).first()
            stock_now=holdings_now.packs if holdings_now else 0
            messages.success(request,f'Sale reported. {d["material"]} {d["pack_size_kg"]} kg stock in hand now: {stock_now} packs.')
            return redirect('commerce:detail',pk=item.pk)
        except ValidationError as exc:form.add_error(None,exc)
        except IntegrityError:
            if not ReportedSale.objects.filter(request_key=d['request_key']).exists():raise
            form.add_error(None,'This submission was already recorded. Check sales before trying again.')
    holdings=SalesManagerStock.objects.filter(officer=user).order_by('material','pack_size_kg')
    return render(request,'commerce/sale_form.html',{'current_user':user,'form':form,'holdings':holdings})

@access('sales_manager','manager','md')
def detail(request,pk):
    user=request.ops_user
    sales=ReportedSale.objects.select_related('recorded_by')
    if user.role=='sales_manager':sales=sales.filter(recorded_by=user)
    item=get_object_or_404(sales,pk=pk)
    can_record=user.role=='sales_manager' and item.recorded_by_id==user.pk
    if request.method=='POST' and not can_record:return forbidden_response(request)
    form=CustomerPaymentForm(request.POST or None)
    if request.method=='POST' and form.is_valid():
        d=form.cleaned_data
        try:
            with transaction.atomic():
                payment=record_customer_payment(sale_id=item.pk,actor=user,key=d['request_key'],date=d['date'],method=d['method'],amount=d['amount'],note=d['note'])
                log_action(request,user,'commerce','REPORT_CUSTOMER_PAYMENT','Report customer payment','ReportedCustomerPayment',payment.pk)
            messages.success(request,'Customer payment reported.')
            return redirect('commerce:detail',pk=pk)
        except ValidationError as exc:form.add_error(None,exc)
        except IntegrityError:
            if not ReportedCustomerPayment.objects.filter(request_key=d['request_key']).exists():raise
            form.add_error(None,'This submission was already recorded. Check payments before trying again.')
    payments=list(item.customer_payments.select_related('recorded_by'))
    total_paid=sum((p.amount for p in payments),Decimal('0'))
    return render(request,'commerce/detail.html',{'current_user':user,'item':item,'payments':payments,'total_paid':total_paid,'overpaid':total_paid>item.total,'can_record':can_record,'form':form})

@access('sales_manager','manager','md')
def money_home(request):
    from django.db.models import Q
    from .models import MoneyHandover
    user=request.ops_user
    items=MoneyHandover.objects.select_related('sender','recipient')
    if user.role!='md':items=items.filter(Q(sender=user)|Q(recipient=user))
    from django.db.models import Case, When, IntegerField
    items=items.order_by(Case(When(recipient=user,status='pending',then=0),When(recipient=user,status='review',then=1),default=2,output_field=IntegerField()),'-created_at','-id')
    from django.core.paginator import Paginator
    page=Paginator(items,50).get_page(request.GET.get('page'))
    return render(request,'commerce/money_home.html',{'current_user':user,'items':page.object_list,'page_obj':page,'can_send':user.role in ('sales_manager','manager')})

@access('sales_manager','manager')
def money_send(request):
    from .forms import MoneyHandoverForm
    from .models import MoneyHandover
    from .services import report_money_handover
    user=request.ops_user
    form=MoneyHandoverForm(request.POST or None,actor=user)
    if request.method=='POST' and form.is_valid():
        d=form.cleaned_data
        try:
            with transaction.atomic():
                item=report_money_handover(actor=user,recipient_id=d['recipient'].pk,key=d['request_key'],date=d['date'],method=d['method'],amount=d['amount'],reference=d['reference'],note=d['note'])
                log_action(request,user,'commerce','REPORT_MONEY_HANDOVER','Report money handover','MoneyHandover',item.pk)
            messages.success(request,f'Money handover reported: ₦{d["amount"]:,.0f} to {d["recipient"].full_name} ({d["method"]}). Waiting for the receiver to confirm.')
            return redirect('commerce:money_detail',pk=item.pk)
        except ValidationError as exc:form.add_error(None,exc)
        except IntegrityError:
            if not MoneyHandover.objects.filter(request_key=d['request_key']).exists():raise
            form.add_error(None,'This submission was already recorded. Check money handovers before trying again.')
    return render(request,'commerce/money_send.html',{'current_user':user,'form':form})

@access('sales_manager','manager','md')
def money_detail(request,pk):
    from django.db.models import Q
    from .models import MoneyHandover, MoneyHandoverReceipt, ReportedPaymentAllocation
    from .forms import MoneyDecisionForm, MoneyReceiptForm, ReportedAllocationForm
    from .services import decide_money_handover, record_money_receipt, report_payment_allocation
    user=request.ops_user
    items=MoneyHandover.objects.select_related('sender','recipient','decided_by')
    if user.role!='md':items=items.filter(Q(sender=user)|Q(recipient=user))
    item=get_object_or_404(items,pk=pk)
    expected='manager' if item.route=='sales_to_gm' else 'md'
    can_decide=item.status in ('pending','review') and item.recipient_id==user.pk and user.role==expected
    can_allocate=user.role=='sales_manager' and item.sender_id==user.pk and item.route=='sales_to_gm'
    action=request.POST.get('action') if request.method=='POST' else ''
    if request.method=='POST' and ((action=='allocate' and not can_allocate) or (action!='allocate' and not can_decide)):return forbidden_response(request)
    is_allocation=request.method=='POST' and action=='allocate'
    is_receipt=request.method=='POST' and action=='receipt'
    form=MoneyDecisionForm(request.POST if request.method=='POST' and not is_receipt and not is_allocation else None)
    receipt_form=MoneyReceiptForm(request.POST if is_receipt else None)
    allocation_form=ReportedAllocationForm(request.POST if is_allocation else None,actor=user)
    if is_allocation and allocation_form.is_valid():
        d=allocation_form.cleaned_data
        try:
            with transaction.atomic():
                allocation=report_payment_allocation(actor=user,payment_id=d['payment'].pk,handover_id=item.pk,key=d['request_key'],amount=d['amount'],note=d['note'])
                log_action(request,user,'commerce','REPORT_PAYMENT_LINK','Report payment link','ReportedPaymentAllocation',allocation.pk)
            messages.success(request,'Payment link reported; not independently verified.')
            return redirect('commerce:money_detail',pk=pk)
        except ValidationError as exc:allocation_form.add_error(None,exc)
        except IntegrityError:
            if not ReportedPaymentAllocation.objects.filter(request_key=d['request_key']).exists():raise
            allocation_form.add_error(None,'This submission was already recorded. Check payment links.')
    if is_receipt and receipt_form.is_valid():
        d=receipt_form.cleaned_data
        try:
            with transaction.atomic():
                receipt=record_money_receipt(handover_id=item.pk,actor=user,key=d['request_key'],amount=d['amount'],note=d['note'])
                log_action(request,user,'commerce','RECORD_MONEY_RECEIPT','Record money receipt','MoneyHandoverReceipt',receipt.pk)
            messages.success(request,'Money receipt recorded.')
            return redirect('commerce:money_detail',pk=pk)
        except ValidationError as exc:receipt_form.add_error(None,exc)
        except IntegrityError:
            if not MoneyHandoverReceipt.objects.filter(request_key=d['request_key']).exists():raise
            receipt_form.add_error(None,'This submission was already recorded. Check receipt history.')
    if request.method=='POST' and not is_receipt and not is_allocation and form.is_valid():
        try:
            with transaction.atomic():
                item=decide_money_handover(handover_id=item.pk,actor=user,decision=form.cleaned_data['decision'],reason=form.cleaned_data['reason'])
                log_action(request,user,'commerce','REVIEW_MONEY_HANDOVER','Review money handover','MoneyHandover',item.pk)
            messages.success(request,'Money handover reviewed.')
            return redirect('commerce:money_detail',pk=pk)
        except ValidationError as exc:form.add_error(None,exc)
    from django.db.models import Exists, OuterRef
    from .models import MoneyCorrectionRequest
    receipts=list(item.receipts.select_related('actor').annotate(corrected=Exists(MoneyCorrectionRequest.objects.filter(receipt_id=OuterRef('pk'),status='approved')),correction_pending=Exists(MoneyCorrectionRequest.objects.filter(receipt_id=OuterRef('pk'),status='pending'))))
    allocations=item.payment_allocations.select_related('payment','payment__sale','recorded_by').annotate(corrected=Exists(MoneyCorrectionRequest.objects.filter(allocation_id=OuterRef('pk'),status='approved')),correction_pending=Exists(MoneyCorrectionRequest.objects.filter(allocation_id=OuterRef('pk'),status='pending')))
    received=sum((r.amount for r in receipts if not r.corrected),Decimal('0'))
    can_request=user.pk in (item.sender_id,item.recipient_id)
    return render(request,'commerce/money_detail.html',{'current_user':user,'item':item,'form':form,'receipt_form':receipt_form,'receipts':receipts,'received':received,'remaining':item.amount-received,'can_decide':can_decide,'can_allocate':can_allocate,'allocation_form':allocation_form,'allocations':allocations,'can_request':can_request,'corrections':item.corrections.select_related('requested_by','decided_by','receipt','allocation'),'events':item.events.select_related('actor')})


@access('sales_manager','manager','md')
def correction_request(request,pk,kind,target_id):
    from django.db.models import Q
    from .models import MoneyHandover, MoneyHandoverReceipt, ReportedPaymentAllocation, MoneyCorrectionRequest
    from .forms import MoneyCorrectionRequestForm
    from .services import request_money_correction
    user=request.ops_user
    h=get_object_or_404(MoneyHandover.objects.filter(Q(sender=user)|Q(recipient=user)),pk=pk)
    model=MoneyHandoverReceipt if kind=='receipt' else ReportedPaymentAllocation if kind=='allocation' else None
    if not model:return forbidden_response(request)
    target=get_object_or_404(model,handover=h,pk=target_id)
    form=MoneyCorrectionRequestForm(request.POST or None)
    if request.method=='POST' and form.is_valid():
        d=form.cleaned_data
        try:
            with transaction.atomic():
                c=request_money_correction(actor=user,handover_id=h.pk,kind=kind,target_id=target.pk,key=d['request_key'],reason=d['reason'])
                log_action(request,user,'commerce','REQUEST_MONEY_CORRECTION','Request correction','MoneyCorrectionRequest',c.pk)
            messages.success(request,'Correction requested.')
            return redirect('commerce:money_detail',pk=h.pk)
        except ValidationError as exc:form.add_error(None,exc)
        except IntegrityError:
            if not (MoneyCorrectionRequest.objects.filter(request_key=d['request_key']).exists() or target.corrections.filter(status__in=['pending','approved']).exists()):raise
            form.add_error(None,'Correction already requested or approved.')
    return render(request,'commerce/correction_request.html',{'current_user':user,'item':h,'target':target,'kind':kind,'form':form})

@access('md')
def corrections_home(request):
    from .models import MoneyCorrectionRequest
    from django.core.paginator import Paginator
    items=MoneyCorrectionRequest.objects.filter(status='pending').select_related('handover','requested_by','receipt','allocation')
    page=Paginator(items,50).get_page(request.GET.get('page'))
    return render(request,'commerce/corrections_home.html',{'current_user':request.ops_user,'items':page.object_list,'page_obj':page})

@access('md')
def correction_detail(request,pk):
    from .models import MoneyCorrectionRequest
    from .forms import MoneyCorrectionDecisionForm
    from .services import decide_money_correction
    c=get_object_or_404(MoneyCorrectionRequest.objects.select_related('handover','requested_by','decided_by','receipt__actor','allocation__recorded_by'),pk=pk)
    user=request.ops_user
    original_actor=c.receipt.actor_id if c.receipt_id else c.allocation.recorded_by_id
    can_review=c.status=='pending' and user.pk not in (c.requested_by_id,original_actor)
    if request.method=='POST' and not can_review:return forbidden_response(request)
    form=MoneyCorrectionDecisionForm(request.POST or None)
    if request.method=='POST' and form.is_valid():
        try:
            with transaction.atomic():
                c=decide_money_correction(actor=user,correction_id=c.pk,decision=form.cleaned_data['decision'],note=form.cleaned_data['note'])
                log_action(request,user,'commerce','DECIDE_MONEY_CORRECTION','Review correction','MoneyCorrectionRequest',c.pk)
            messages.success(request,'Correction reviewed.')
            return redirect('commerce:correction_detail',pk=c.pk)
        except ValidationError as exc:form.add_error(None,exc)
    return render(request,'commerce/correction_detail.html',{'current_user':user,'correction':c,'form':form,'can_review':can_review})
