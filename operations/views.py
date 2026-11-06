from functools import wraps
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Case, When, IntegerField, Sum, Value
from django.db.models.functions import Coalesce
from accounts.mixins import forbidden_response
from django.shortcuts import get_object_or_404, redirect, render
from accounts.models import User
from audit.utils import log_action
from .forms import CleaningIssueForm, CleaningReturnForm, ProductionIssueForm, DecisionForm, MillingForm, PackagingForm, FinishedIssueForm, FinishedReceiptForm, FinishedReviewForm, FinishedReturnForm, FinishedResolveForm, FinishedReviewNoteForm, FinishedStoreCountForm, SalesGoodsSendForm
from bag_stock.models import BagPosition, CleaningJob, CleaningReturn, ProductionTransfer, ProductionHolding, PowderHolding, MillingRecord, PackagingRecord, FinishedProductionStock, FinishedStoreStock, FinishedHandover, FinishedPartialReceipt, FinishedPartialReturn, FinishedReviewNote, FinishedStoreCount, SalesManagerStock, SalesGoodsHandover
from bag_stock import services

def access(*roles, store_types=('raw',)):
    def decorate(fn):
        @wraps(fn)
        def wrapper(request, *args, **kwargs):
            user_id = request.session.get('actual_user_id') or request.session.get('user_id')
            if not user_id:
                return redirect('login')
            user = User.objects.filter(pk=user_id, status='active').first()
            if not user or request.session.get('impersonate_id') or request.session.get('user_id') != user_id or user.role not in roles or (user.role == 'store_officer' and user.store_type not in store_types):
                return forbidden_response(request)
            request.ops_user = user
            return fn(request, *args, **kwargs)
        return wrapper
    return decorate

@access('store_officer','manager','md','production_officer')
def home(request):
    user = request.ops_user
    production = user.role == 'production_officer'
    balances = BagPosition.objects.filter(location__in=['raw_store','clean_store','transit']).order_by('material', Case(When(location='raw_store',then=0),When(location='cleaning',then=1),When(location='clean_store',then=2),When(location='transit',then=3),output_field=IntegerField())) if not production else []
    jobs = CleaningJob.objects.annotate(returned_bags=Coalesce(Sum('returns__clean_bags'),Value(0))).select_related('issued_by').order_by('-created_at','-id')[:8] if not production else []
    transfers = ProductionTransfer.objects.select_related('recipient','sent_by').filter(recipient=user, status='pending') if production else ProductionTransfer.objects.select_related('recipient','sent_by').all()[:8]
    return render(request,'operations/home.html',{'current_user':user,'balances':balances,'jobs':jobs,'transfers':transfers,'production':production})

def _form_page(request, form_class, title, action, operation):
    form = form_class(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        try:
            with transaction.atomic():
                obj = operation(form.cleaned_data, request.ops_user)
                log_action(request,request.ops_user,'operations',action, title, type(obj).__name__, obj.pk)
            messages.success(request, f'{title} saved · #{obj.pk}')
            return redirect('operations:home')
        except ValidationError as exc:
            form.add_error(None, exc)
        except IntegrityError:
            model = {CleaningIssueForm: CleaningJob, CleaningReturnForm: CleaningReturn, ProductionIssueForm: ProductionTransfer}[form_class]
            if not model.objects.filter(request_key=form.cleaned_data['request_key']).exists():
                raise
            form.add_error(None, 'This submission was already recorded. Check the records before trying again.')
    return render(request,'operations/form.html',{'current_user':request.ops_user,'form':form,'title':title})

@access('store_officer','manager','md')
def cleaning_issue(request):
    return _form_page(request,CleaningIssueForm,'Send for cleaning','SEND_CLEANING',lambda d,u: services.send_to_cleaner(key=d['request_key'],date=d['date'],material=d['material'],cleaner=d['cleaner'],bags=d['bags'],weight_kg=d['weight_kg'],actor=u))

@access('store_officer','manager','md')
def cleaning_return(request):
    return _form_page(request,CleaningReturnForm,'Receive from cleaning','RECEIVE_CLEANING',lambda d,u: services.receive_from_cleaner(key=d['request_key'],job_id=d['job'].pk,date=d['date'],clean_bags=d['clean_bags'],clean_weight_kg=d['clean_weight_kg'],loss_weight_kg=d['loss_weight_kg'],is_final=d['return_type']=='final',actor=u))

@access('store_officer','manager','md')
def production_issue(request):
    return _form_page(request,ProductionIssueForm,'Send to production','SEND_PRODUCTION',lambda d,u: services.send_to_production(key=d['request_key'],date=d['date'],material=d['material'],bags=d['bags'],weight_kg=d['weight_kg'],sender=u,recipient=d['recipient']))

@access('production_officer')
def production_decide(request, pk):
    handover = get_object_or_404(ProductionTransfer.objects.select_related('sent_by','recipient'),pk=pk,recipient=request.ops_user)
    form = DecisionForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        try:
            with transaction.atomic():
                obj = services.decide_transfer(transfer_id=handover.pk,actor=request.ops_user,accept=form.cleaned_data['decision']=='accept',reason=form.cleaned_data['reason'])
                log_action(request,request.ops_user,'operations','REVIEW_PRODUCTION_HANDOVER',f'Handover {obj.status}', 'ProductionTransfer',obj.pk)
            messages.success(request, f'Handover #{obj.pk} reviewed.')
            return redirect('operations:home')
        except ValidationError as exc:
            form.add_error(None, exc)
    return render(request,'operations/decision.html',{'current_user':request.ops_user,'handover':handover,'form':form})

@access('store_officer','manager','md')
def cleaning_detail(request, pk):
    job=get_object_or_404(CleaningJob.objects.select_related('issued_by').annotate(returned_bags=Coalesce(Sum('returns__clean_bags'),Value(0))),pk=pk)
    returns=job.returns.select_related('received_by').order_by('date','created_at')
    return render(request,'operations/cleaning_detail.html',{'current_user':request.ops_user,'job':job,'returns':returns})


@access('production_officer','manager','md')
def production_home(request):
    user=request.ops_user
    mine=user.role=='production_officer'
    holdings=ProductionHolding.objects.select_related('officer').order_by('officer__full_name','material')
    powder=PowderHolding.objects.select_related('officer').order_by('officer__full_name','material')
    milling=MillingRecord.objects.select_related('officer')
    packaging=PackagingRecord.objects.select_related('officer')
    if mine:
        holdings=holdings.filter(officer=user);powder=powder.filter(officer=user)
        milling=milling.filter(officer=user);packaging=packaging.filter(officer=user)
    return render(request,'operations/production_home.html',{'current_user':user,'mine':mine,'holdings':holdings,'powder':powder,'milling':milling[:8],'packaging':packaging[:8]})

def _production_form(request, form_class, title, model, service, action):
    form=form_class(request.POST or None)
    if request.method=='POST' and form.is_valid():
        try:
            with transaction.atomic():
                data=form.cleaned_data.copy();data['key']=data.pop('request_key');data['actor']=request.ops_user
                record=service(**data)
                log_action(request,request.ops_user,'operations',action,title,type(record).__name__,record.pk)
            # Show the officer what he now holds, so the balance is visible
            # right after the work is recorded.
            holding=ProductionHolding.objects.filter(officer=request.ops_user,material=record.material).first()
            powder=PowderHolding.objects.filter(officer=request.ops_user,material=record.material).first()
            stock=FinishedProductionStock.objects.filter(officer=request.ops_user,material=record.material,pack_size_kg=10).aggregate(t=Sum('packs'))['t'] or 0
            balance_note=(f" Clean bags in hand: {holding.bags if holding else 0} bags"
                          f" · Powder in hand: {powder.kg if powder and powder.kg is not None else 0} kg"
                          f" · Finished 10kg packs not yet sent: {stock}.")
            messages.success(request,f'{title} saved · #{record.pk}.{balance_note}')
            return redirect('operations:production_home')
        except ValidationError as exc: form.add_error(None,exc)
        except IntegrityError:
            if not model.objects.filter(request_key=form.cleaned_data['request_key']).exists(): raise
            form.add_error(None,'This submission was already recorded. Check the records before trying again.')
    return render(request,'operations/production_form.html',{'current_user':request.ops_user,'form':form,'title':title,'holdings':ProductionHolding.objects.filter(officer=request.ops_user),'powder':PowderHolding.objects.filter(officer=request.ops_user),'is_milling':form_class is MillingForm})

@access('production_officer')
def milling(request):
    return _production_form(request,MillingForm,'Record milling',MillingRecord,services.record_milling,'RECORD_MILLING')

@access('production_officer')
def packaging(request):
    return _production_form(request,PackagingForm,'Record packaging',PackagingRecord,services.record_packaging,'RECORD_PACKAGING')


@access('production_officer','store_officer','manager','md',store_types=('finished',))
def finished_home(request):
    user=request.ops_user
    production=user.role=='production_officer';store=user.role=='store_officer'
    handovers=FinishedHandover.objects.select_related('sent_by','recipient')
    prod_stock=FinishedProductionStock.objects.select_related('officer').order_by('officer__full_name','material','pack_size_kg')
    store_stock=FinishedStoreStock.objects.order_by('material','pack_size_kg')
    if production: handovers=handovers.filter(sent_by=user);prod_stock=prod_stock.filter(officer=user);store_stock=FinishedStoreStock.objects.none()
    elif store: handovers=handovers.filter(recipient=user);prod_stock=FinishedProductionStock.objects.none()
    return render(request,'operations/finished_home.html',{'current_user':user,'production':production,'store':store,'handovers':handovers[:15],'prod_stock':prod_stock,'store_stock':store_stock})

@access('production_officer')
def finished_send(request):
    form=FinishedIssueForm(request.POST or None)
    if request.method=='POST' and form.is_valid():
        try:
            with transaction.atomic():
                d=form.cleaned_data
                obj=services.send_finished(key=d['request_key'],date=d['date'],material=d['material'],pack_size_kg=d['pack_size_kg'],packs=d['packs'],recipient=d['recipient'],sender=request.ops_user)
                log_action(request,request.ops_user,'operations','SEND_FINISHED','Send finished goods','FinishedHandover',obj.pk)
            stock_now=FinishedProductionStock.objects.filter(officer=request.ops_user,material=d['material'],pack_size_kg=d['pack_size_kg']).first()
            messages.success(request,f'Handover sent · #{obj.pk}. Finished {d["material"]} {d["pack_size_kg"]} kg packs still with production: {stock_now.packs if stock_now else 0}.')
            return redirect('operations:finished_home')
        except ValidationError as exc:form.add_error(None,exc)
        except IntegrityError:
            if not FinishedHandover.objects.filter(request_key=form.cleaned_data['request_key']).exists(): raise
            form.add_error(None,'This submission was already recorded. Check the records before trying again.')
    return render(request,'operations/finished_send.html',{'current_user':request.ops_user,'form':form,'stocks':FinishedProductionStock.objects.filter(officer=request.ops_user).order_by('material','pack_size_kg')})

@access('production_officer','store_officer','manager','md',store_types=('finished',))
def finished_detail(request,pk):
    user=request.ops_user
    qs=FinishedHandover.objects.select_related('sent_by','recipient','decision_by','returned_by','resolved_by')
    if user.role=='production_officer':qs=qs.filter(sent_by=user)
    elif user.role=='store_officer':qs=qs.filter(recipient=user)
    item=get_object_or_404(qs,pk=pk)
    remaining=item.packs-item.received_packs-item.returned_packs
    can_receive=user.pk==item.recipient_id and user.role=='store_officer' and item.status in ('pending','partial','disputed') and remaining>0
    can_flag=user.pk==item.recipient_id and user.role=='store_officer' and item.status in ('pending','partial')
    can_return=user.pk==item.sent_by_id and user.role=='production_officer' and item.status=='disputed' and remaining>0
    can_resolve=user.role in ('manager','md') and item.status=='disputed' and remaining==0
    can_note=item.status=='disputed'
    action=request.POST.get('action') if request.method=='POST' else None
    note_form=FinishedReviewNoteForm(request.POST if action=='note' else None,prefix='note')
    receipt_form=FinishedReceiptForm(request.POST if action=='receive' else None,prefix='receipt')
    flag_form=FinishedReviewForm(request.POST if action=='flag' else None,prefix='review')
    return_form=FinishedReturnForm(request.POST if action=='return' else None,prefix='return')
    resolve_form=FinishedResolveForm(request.POST if action=='resolve' else None,prefix='resolve')
    forms={'receive':receipt_form,'flag':flag_form,'return':return_form,'resolve':resolve_form,'note':note_form}
    allowed={'receive':can_receive,'flag':can_flag,'return':can_return,'resolve':can_resolve,'note':can_note}
    if request.method=='POST':
        if action not in forms or not allowed[action]:return forbidden_response(request)
        form=forms[action]
        if form.is_valid():
            try:
                with transaction.atomic():
                    d=form.cleaned_data
                    if action=='receive': obj=services.receive_finished(handover_id=item.pk,actor=user,key=d['request_key'],packs=d['packs'],is_final=d['receipt_type']=='final',reason=d['reason'])
                    elif action=='flag': obj=services.flag_finished(handover_id=item.pk,actor=user,reason=d['reason'])
                    elif action=='return': obj=services.return_finished(handover_id=item.pk,actor=user,key=d['request_key'],packs=d['packs'])
                    elif action=='note': obj=services.add_finished_review_note(handover_id=item.pk,actor=user,key=d['request_key'],note=d['note'])
                    else: obj=services.resolve_finished(handover_id=item.pk,actor=user,note=d['note'])
                    log_action(request,user,'operations','FINISHED_'+action.upper(),'Finished goods handover',type(obj).__name__,obj.pk)
                messages.success(request,f'Handover #{item.pk} updated.')
                return redirect('operations:finished_detail',pk=item.pk)
            except ValidationError as exc: form.add_error(None,exc)
            except IntegrityError:
                model={'receive':FinishedPartialReceipt,'return':FinishedPartialReturn,'note':FinishedReviewNote}.get(action)
                if model is None or not model.objects.filter(request_key=form.cleaned_data['request_key']).exists():raise
                form.add_error(None,'This submission was already recorded. Check the handover before trying again.')
    history=[{'row':r,'kind':'receipt'} for r in item.partial_receipts.select_related('recorded_by')]+[{'row':r,'kind':'return'} for r in item.partial_returns.select_related('recorded_by')]
    history.sort(key=lambda e:(e['row'].created_at,e['row'].pk))
    return render(request,'operations/finished_detail.html',{'current_user':user,'item':item,'remaining':remaining,'can_receive':can_receive,'can_flag':can_flag,'can_return':can_return,'can_resolve':can_resolve,'receipt_form':receipt_form,'flag_form':flag_form,'return_form':return_form,'resolve_form':resolve_form,'history':history,'can_note':can_note,'note_form':note_form,'review_notes':item.review_notes.select_related('recorded_by')})

@access('store_officer','manager','md',store_types=('finished',))
def finished_counts(request):
    form=FinishedStoreCountForm(request.POST or None)
    if request.method=='POST' and form.is_valid():
        try:
            with transaction.atomic():
                d=form.cleaned_data
                obj=services.record_finished_store_count(actor=request.ops_user,key=d['request_key'],material=d['material'],pack_size_kg=d['pack_size_kg'],counted_packs=d['counted_packs'],counted_at=d['counted_at'],scope=d['scope'],note=d['note'])
                log_action(request,request.ops_user,'operations','FINISHED_STORE_COUNT','Record finished store count','FinishedStoreCount',obj.pk)
            messages.success(request,f'Count saved · #{obj.pk}')
            return redirect('operations:finished_count_detail',pk=obj.pk)
        except ValidationError as exc:form.add_error(None,exc)
        except IntegrityError:
            if not FinishedStoreCount.objects.filter(request_key=form.cleaned_data['request_key']).exists():raise
            form.add_error(None,'This submission was already recorded. Check recent counts before trying again.')
    counts=FinishedStoreCount.objects.select_related('recorded_by')[:20]
    return render(request,'operations/finished_counts.html',{'current_user':request.ops_user,'form':form,'counts':counts})

@access('store_officer','manager','md',store_types=('finished',))
def finished_count_detail(request,pk):
    item=get_object_or_404(FinishedStoreCount.objects.select_related('recorded_by'),pk=pk)
    return render(request,'operations/finished_count_detail.html',{'current_user':request.ops_user,'item':item})

@access('store_officer','sales_manager','manager','md',store_types=('finished',))
def sales_goods_home(request):
    user=request.ops_user
    handovers=SalesGoodsHandover.objects.select_related('sent_by','recipient')
    holdings=SalesManagerStock.objects.select_related('officer').order_by('officer__full_name','material','pack_size_kg')
    if user.role=='sales_manager':handovers=handovers.filter(recipient=user);holdings=holdings.filter(officer=user)
    return render(request,'operations/sales_goods_home.html',{'current_user':user,'handovers':handovers[:25],'holdings':holdings,'can_send':user.role=='store_officer','sales_manager':user.role=='sales_manager'})

@access('store_officer',store_types=('finished',))
def sales_goods_send(request):
    form=SalesGoodsSendForm(request.POST or None)
    if request.method=='POST' and form.is_valid():
        try:
            with transaction.atomic():
                d=form.cleaned_data
                obj=services.send_sales_goods(actor=request.ops_user,key=d['request_key'],date=d['date'],material=d['material'],pack_size_kg=d['pack_size_kg'],packs=d['packs'],recipient=d['recipient'])
                log_action(request,request.ops_user,'operations','SEND_SALES_GOODS','Send goods to sales manager','SalesGoodsHandover',obj.pk)
            stock_now=FinishedStoreStock.objects.filter(material=d['material'],pack_size_kg=d['pack_size_kg']).first()
            messages.success(request,f'Handover sent · #{obj.pk}. Finished store {d["material"]} {d["pack_size_kg"]} kg balance now: {stock_now.packs if stock_now else 0} packs.')
            return redirect('operations:sales_goods_detail',pk=obj.pk)
        except ValidationError as exc:form.add_error(None,exc)
        except IntegrityError:
            if not SalesGoodsHandover.objects.filter(request_key=form.cleaned_data['request_key']).exists():raise
            form.add_error(None,'This submission was already recorded. Check the handovers before trying again.')
    return render(request,'operations/sales_goods_send.html',{'current_user':request.ops_user,'form':form,'stocks':FinishedStoreStock.objects.order_by('material','pack_size_kg')})

@access('store_officer','sales_manager','manager','md',store_types=('finished',))
def sales_goods_detail(request,pk):
    user=request.ops_user
    qs=SalesGoodsHandover.objects.select_related('sent_by','recipient','decided_by','returned_by')
    if user.role=='sales_manager':qs=qs.filter(recipient=user)
    obj=get_object_or_404(qs,pk=pk)
    can_decide=user.role=='sales_manager' and obj.recipient_id==user.pk and obj.status=='pending'
    can_return=user.role=='store_officer' and obj.sent_by_id==user.pk and obj.status=='disputed'
    action=request.POST.get('action') if request.method=='POST' else None
    form=DecisionForm(request.POST if action=='decide' else None,prefix='decision')
    if request.method=='POST':
        if action=='decide' and can_decide:
            if form.is_valid():
                try:
                    with transaction.atomic():
                        d=form.cleaned_data
                        obj=services.decide_sales_goods(handover_id=obj.pk,actor=user,accept=d['decision']=='accept',reason=d['reason'])
                        log_action(request,user,'operations','REVIEW_SALES_GOODS','Review sales goods handover','SalesGoodsHandover',obj.pk)
                    messages.success(request,'Handover updated.')
                    return redirect('operations:sales_goods_detail',pk=obj.pk)
                except ValidationError as exc:form.add_error(None,exc)
        elif action=='return' and can_return:
            try:
                with transaction.atomic():
                    obj=services.return_sales_goods(handover_id=obj.pk,actor=user)
                    log_action(request,user,'operations','RETURN_SALES_GOODS','Confirm goods returned','SalesGoodsHandover',obj.pk)
                messages.success(request,'Return confirmed.')
                return redirect('operations:sales_goods_detail',pk=obj.pk)
            except ValidationError as exc:form.add_error(None,exc)
        else:return forbidden_response(request)
    return render(request,'operations/sales_goods_detail.html',{'current_user':user,'item':obj,'form':form,'can_decide':can_decide,'can_return':can_return,'events':obj.events.select_related('recorded_by')})
