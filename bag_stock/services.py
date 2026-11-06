from decimal import Decimal, InvalidOperation
from datetime import datetime
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from procurement.models import MATERIAL_CHOICES
from .models import BagPosition,BagMovement,CleaningJob,CleaningReturn,ProductionTransfer,ProductionHolding,PowderHolding,MillingRecord,PackagingRecord,SHIFT_CHOICES,FinishedProductionStock,FinishedStoreStock,FinishedHandover,FinishedStockEvent,FinishedPartialReceipt,FinishedPartialReturn,FinishedReviewNote,FinishedStoreCount,SalesManagerStock,SalesGoodsHandover,SalesGoodsEvent
from accounts.models import User

VALID_MATERIALS={value for value,_ in MATERIAL_CHOICES}
LOCATIONS={'raw_store','cleaning','clean_store','transit','production'}

def count(value,allow_zero=False):
    if isinstance(value,bool): raise ValidationError('Enter a whole number of bags.')
    try:
        n=int(value)
        if str(n)!=str(value) or n<0 or (n==0 and not allow_zero) or n>2147483647: raise ValueError
        return n
    except (ValueError,TypeError,OverflowError): raise ValidationError('Enter a whole number of bags.')

def weight(value,allow_zero=False):
    if value in (None,''): return None
    try:
        x=Decimal(str(value))
        if not x.is_finite() or x<0 or (not allow_zero and x==0) or x>Decimal('9999999999.99') or x!=x.quantize(Decimal('.01')): raise ValueError
        return x
    except (ValueError,TypeError,InvalidOperation): raise ValidationError('Enter a valid weight greater than zero.')

def _post(*,material,source,destination,bags,date,actor,kind,**reference):
    bags=count(bags)
    if material not in VALID_MATERIALS or source==destination or (source and source not in LOCATIONS) or (destination and destination not in LOCATIONS) or not (source or destination): raise ValidationError('Invalid stock movement.')
    locs=sorted(filter(None,[source,destination]))
    for loc in locs: BagPosition.objects.get_or_create(material=material,location=loc)
    positions={p.location:p for p in BagPosition.objects.select_for_update().filter(material=material,location__in=locs).order_by('location')}
    if source:
        if positions[source].bags<bags: raise ValidationError('Not enough available bags.')
        positions[source].bags-=bags; positions[source].save(update_fields=['bags'])
    if destination:
        positions[destination].bags+=bags; positions[destination].save(update_fields=['bags'])
    return BagMovement.objects.create(material=material,from_location=source or '',to_location=destination or '',bags=bags,occurred_on=date,recorded_by=actor,kind=kind,**reference)

@transaction.atomic
def post_receipt(receipt,actor):
    return _post(material=receipt.material_type,source=None,destination='raw_store',bags=receipt.num_bags,date=receipt.date,actor=actor,kind='receipt',receipt=receipt)

@transaction.atomic
def send_to_cleaner(*,key,date,material,cleaner,bags,weight_kg,actor):
    bags=count(bags); measured=weight(weight_kg)
    if not cleaner.strip(): raise ValidationError('Enter the cleaner’s name.')
    job=CleaningJob.objects.create(request_key=key,date=date,material=material,cleaner=cleaner.strip(),issued_bags=bags,weight_kg=measured,issued_by=actor)
    _post(material=material,source='raw_store',destination=None,bags=bags,date=date,actor=actor,kind='cleaning_issue',cleaning_job=job)
    return job

@transaction.atomic
def receive_from_cleaner(*,key,job_id,date,clean_bags,clean_weight_kg,loss_weight_kg,is_final,actor):
    clean_bags=count(clean_bags,allow_zero=True)
    cw,loss=weight(clean_weight_kg),weight(loss_weight_kg,allow_zero=True)
    if not isinstance(is_final, bool): raise ValidationError('Select partial or final return.')
    if not is_final and clean_bags == 0: raise ValidationError('Enter the clean bags received for a partial return.')
    job=CleaningJob.objects.select_for_update().get(pk=job_id)
    if job.status != 'in_progress': raise ValidationError('This cleaning record is closed or needs review.')
    if date<job.date: raise ValidationError('Date cannot be before the material was sent.')
    if job.returns.filter(date__gt=date).exists(): raise ValidationError('Date cannot be before an earlier recorded return.')
    if clean_bags==0 and cw is not None: raise ValidationError('Clean weight requires at least one clean bag.')
    returned=CleaningReturn.objects.create(request_key=key,job=job,date=date,clean_bags=clean_bags,clean_weight_kg=cw,loss_weight_kg=loss,is_final=is_final,received_by=actor)
    if clean_bags: _post(material=job.material,source=None,destination='clean_store',bags=clean_bags,date=date,actor=actor,kind='cleaning_output',cleaning_job=job,cleaning_return=returned)
    if is_final:
        from django.db.models import Sum
        total=job.returns.aggregate(n=Sum('clean_bags'))['n'] or 0
        job.status='closed'
        # A count difference is a prompt to review, never a calculated loss.
        job.counts_differ=(total != job.issued_bags)
        job.save(update_fields=['status','counts_differ'])
    return returned

@transaction.atomic
def send_to_production(*,key,date,material,bags,weight_kg,sender,recipient):
    bags=count(bags); measured=weight(weight_kg)
    if recipient.status!='active' or recipient.role!='production_officer' or sender.pk==recipient.pk: raise ValidationError('Select an active production officer.')
    transfer=ProductionTransfer.objects.create(request_key=key,date=date,material=material,bags=bags,weight_kg=measured,sent_by=sender,recipient=recipient)
    _post(material=material,source='clean_store',destination='transit',bags=bags,date=date,actor=sender,kind='production_issue',transfer=transfer)
    return transfer

@transaction.atomic
def decide_transfer(*,transfer_id,actor,accept,reason=''):
    transfer=ProductionTransfer.objects.select_for_update().get(pk=transfer_id)
    if actor.pk!=transfer.recipient_id or actor.status!='active' or actor.role!='production_officer': raise ValidationError('Only the assigned production officer can confirm this handover.')
    if transfer.status!='pending': raise ValidationError('This handover has already been reviewed.')
    if not accept and not reason.strip(): raise ValidationError('Enter a reason for returning the handover.')
    if accept:
        User.objects.select_for_update().get(pk=actor.pk)
        holding,_=ProductionHolding.objects.get_or_create(officer=actor,material=transfer.material)
        holding.bags+=transfer.bags
        holding.save(update_fields=['bags'])
    _post(material=transfer.material,source='transit',destination='production' if accept else 'clean_store',bags=transfer.bags,date=timezone.localdate(),actor=actor,kind='production_accepted' if accept else 'production_rejected',transfer=transfer)
    transfer.status='accepted' if accept else 'rejected';transfer.decision_by=actor;transfer.decided_at=timezone.now();transfer.rejection_reason='' if accept else reason.strip()
    transfer.save(update_fields=['status','decision_by','decided_at','rejection_reason'])
    return transfer


def _production_actor(actor, material, shift, date):
    locked=User.objects.select_for_update().get(pk=actor.pk)
    if locked.status!='active' or locked.role!='production_officer': raise ValidationError('Only an active production officer can record production.')
    if material not in VALID_MATERIALS or shift not in dict(SHIFT_CHOICES): raise ValidationError('Select a valid material and shift.')
    if date>timezone.localdate(): raise ValidationError('Date cannot be in the future.')
    # Keep this development ledger in chronological order; later-dated work must
    # not make stock available to an earlier transaction.
    if FinishedHandover.objects.filter(sent_by=locked,material=material,date__gt=date).exists(): raise ValidationError('Date cannot be before a later finished-goods handover.')
    for model in (MillingRecord,PackagingRecord):
        if model.objects.filter(officer=locked,material=material,date__gt=date).exists(): raise ValidationError('Date cannot be before a later production record.')
    return locked

@transaction.atomic
def record_milling(*,key,date,material,shift,bags,input_weight_kg,powder_kg,machine,actor,powder_bags=None):
    actor=_production_actor(actor,material,shift,date)
    bags=count(bags); input_weight=weight(input_weight_kg); powder=weight(powder_kg)
    if powder is None: raise ValidationError('Enter the powder produced.')
    powder_bags=count(powder_bags) if powder_bags not in (None,'') else None
    if ProductionTransfer.objects.filter(recipient=actor,material=material,status='accepted',date__gt=date).exists(): raise ValidationError('Date cannot be before a later confirmed handover.')
    holding,_=ProductionHolding.objects.get_or_create(officer=actor,material=material)
    if holding.bags<bags: raise ValidationError('Not enough clean bags available to you.')
    record=MillingRecord.objects.create(request_key=key,date=date,material=material,shift=shift,bags=bags,input_weight_kg=input_weight,powder_kg=powder,powder_bags=powder_bags,machine=machine.strip(),officer=actor)
    _post(material=material,source='production',destination=None,bags=bags,date=date,actor=actor,kind='milling_input',milling=record)
    holding.bags-=bags;holding.save(update_fields=['bags'])
    stock,_=PowderHolding.objects.get_or_create(officer=actor,material=material)
    if stock.kg is not None:
        stock.kg+=powder
        stock.save(update_fields=['kg'])
    return record

@transaction.atomic
def record_packaging(*,key,date,material,shift,powder_used_kg,packs,pack_size_kg,actor,powder_used_bags=None):
    actor=_production_actor(actor,material,shift,date)
    used=weight(powder_used_kg); size=weight(pack_size_kg); packs=count(packs)
    if size is None: raise ValidationError('Enter the pack size.')
    bags_used=count(powder_used_bags) if powder_used_bags not in (None,'') else None
    if size>Decimal('999999.99'): raise ValidationError('Enter a valid pack size.')
    # A new-path milling record establishes this officer's powder holding.
    # Absence of a ledger is not proof of zero; opening stock requires reconciliation.
    stock=PowderHolding.objects.filter(officer=actor,material=material).first()
    if stock is None: raise ValidationError('No powder record exists for this material.')
    if used is not None and stock.kg is not None and used>stock.kg: raise ValidationError('Not enough recorded powder available to you.')
    record=PackagingRecord.objects.create(request_key=key,date=date,material=material,shift=shift,powder_used_kg=used,powder_used_bags=bags_used,packs=packs,pack_size_kg=size,officer=actor)
    if stock.kg is not None:
        stock.kg=stock.kg-used if used is not None else None
        stock.save(update_fields=['kg'])
    finished,_=FinishedProductionStock.objects.get_or_create(officer=actor,material=material,pack_size_kg=size)
    finished.packs+=packs;finished.save(update_fields=['packs'])
    FinishedStockEvent.objects.create(material=material,pack_size_kg=size,packs=packs,kind='packaged',recorded_by=actor,occurred_on=date,packaging=record)
    return record


@transaction.atomic
def send_finished(*,key,date,material,pack_size_kg,packs,recipient,sender):
    sender=User.objects.select_for_update().get(pk=sender.pk)
    if sender.status!='active' or sender.role!='production_officer': raise ValidationError('Only an active production officer can send finished goods.')
    recipient=User.objects.get(pk=recipient.pk)
    if recipient.status!='active' or recipient.role!='store_officer' or recipient.store_type!='finished' or recipient.pk==sender.pk: raise ValidationError('Select an active finished-goods store officer.')
    size=weight(pack_size_kg);packs=count(packs)
    if material not in VALID_MATERIALS or size is None or size>Decimal('999999.99'): raise ValidationError('Select a valid product and size.')
    if date>timezone.localdate(): raise ValidationError('Date cannot be in the future.')
    if PackagingRecord.objects.filter(officer=sender,material=material,pack_size_kg=size,date__gt=date).exists() or FinishedHandover.objects.filter(sent_by=sender,material=material,pack_size_kg=size,date__gt=date).exists(): raise ValidationError('Date cannot be before a later production or handover record.')
    stock=FinishedProductionStock.objects.filter(officer=sender,material=material,pack_size_kg=size).first()
    if stock is None or packs>stock.packs: raise ValidationError('Not enough recorded packs available to send.')
    obj=FinishedHandover.objects.create(request_key=key,date=date,material=material,pack_size_kg=size,packs=packs,sent_by=sender,recipient=recipient)
    stock.packs-=packs;stock.save(update_fields=['packs'])
    FinishedStockEvent.objects.create(material=material,pack_size_kg=size,packs=packs,kind='sent',recorded_by=sender,occurred_on=date,handover=obj)
    return obj

def _remaining(obj):
    return obj.packs-obj.received_packs-obj.returned_packs

def _finished_receiver(obj, actor):
    actor=User.objects.get(pk=actor.pk)
    if actor.pk!=obj.recipient_id or actor.status!='active' or actor.role!='store_officer' or actor.store_type!='finished': raise ValidationError('Only the assigned finished-goods store officer can record this receipt.')
    return actor

@transaction.atomic
def receive_finished(*,handover_id,actor,key,packs,is_final,reason=''):
    obj=FinishedHandover.objects.select_for_update().get(pk=handover_id)
    actor=_finished_receiver(obj,actor)
    if obj.status not in ('pending','partial','disputed'): raise ValidationError('This handover is closed.')
    if not isinstance(is_final,bool): raise ValidationError('Select partial or final receipt.')
    packs=count(packs);remaining=_remaining(obj)
    if packs>remaining: raise ValidationError('Packs received cannot exceed the unaccounted amount.')
    if not is_final and packs==remaining: raise ValidationError('Select final receipt when all remaining packs are received.')
    if is_final and packs<remaining and not reason.strip(): raise ValidationError('Enter a reason for the difference.')
    receipt=FinishedPartialReceipt.objects.create(request_key=key,handover=obj,packs=packs,is_final=is_final,recorded_by=actor)
    FinishedStoreStock.objects.get_or_create(material=obj.material,pack_size_kg=obj.pack_size_kg)
    stock=FinishedStoreStock.objects.select_for_update().get(material=obj.material,pack_size_kg=obj.pack_size_kg)
    stock.packs+=packs;stock.save(update_fields=['packs'])
    FinishedStockEvent.objects.create(material=obj.material,pack_size_kg=obj.pack_size_kg,packs=packs,kind='received',recorded_by=actor,occurred_on=obj.date,handover=obj,receipt=receipt)
    obj.received_packs+=packs
    if is_final and _remaining(obj)>0:
        obj.status='disputed';obj.reason=reason.strip();obj.decision_by=actor;obj.decided_at=timezone.now()
    elif obj.status!='disputed':obj.status='accepted' if _remaining(obj)==0 else 'partial'
    if obj.status=='accepted':obj.decision_by=actor;obj.decided_at=timezone.now()
    obj.save(update_fields=['received_packs','status','reason','decision_by','decided_at'])
    return receipt

@transaction.atomic
def flag_finished(*,handover_id,actor,reason):
    obj=FinishedHandover.objects.select_for_update().get(pk=handover_id)
    actor=_finished_receiver(obj,actor)
    if obj.status not in ('pending','partial'): raise ValidationError('This handover cannot be flagged again.')
    if not reason.strip(): raise ValidationError('Enter a reason for review.')
    obj.status='disputed';obj.reason=reason.strip();obj.decision_by=actor;obj.decided_at=timezone.now()
    obj.save(update_fields=['status','reason','decision_by','decided_at'])
    return obj

@transaction.atomic
def return_finished(*,handover_id,actor,key,packs):
    obj=FinishedHandover.objects.select_for_update().get(pk=handover_id)
    actor=User.objects.select_for_update().get(pk=actor.pk)
    if actor.pk!=obj.sent_by_id or actor.status!='active' or actor.role!='production_officer': raise ValidationError('Only the sender can confirm the returned goods.')
    if obj.status!='disputed': raise ValidationError('This handover is not under review.')
    packs=count(packs)
    if packs>_remaining(obj): raise ValidationError('Packs returned cannot exceed the unaccounted amount.')
    returned=FinishedPartialReturn.objects.create(request_key=key,handover=obj,packs=packs,recorded_by=actor)
    stock=FinishedProductionStock.objects.select_for_update().get(officer=actor,material=obj.material,pack_size_kg=obj.pack_size_kg)
    stock.packs+=packs;stock.save(update_fields=['packs'])
    FinishedStockEvent.objects.create(material=obj.material,pack_size_kg=obj.pack_size_kg,packs=packs,kind='returned',recorded_by=actor,occurred_on=obj.date,handover=obj,goods_return=returned)
    obj.returned_packs+=packs;obj.returned_by=actor;obj.returned_at=timezone.now();obj.save(update_fields=['returned_packs','returned_by','returned_at'])
    return returned

@transaction.atomic
def resolve_finished(*,handover_id,actor,note):
    obj=FinishedHandover.objects.select_for_update().get(pk=handover_id)
    actor=User.objects.get(pk=actor.pk)
    if actor.status!='active' or actor.role not in ('manager','md'): raise ValidationError('Only management can close this review.')
    if obj.status!='disputed': raise ValidationError('This handover is not under review.')
    if _remaining(obj)!=0: raise ValidationError('All packs must be accounted for before closing the review.')
    if not note.strip(): raise ValidationError('Enter a resolution note.')
    obj.status='accepted' if obj.returned_packs==0 else ('returned' if obj.received_packs==0 else 'resolved')
    obj.resolved_by=actor;obj.resolved_at=timezone.now();obj.resolution_note=note.strip()
    obj.save(update_fields=['status','resolved_by','resolved_at','resolution_note'])
    return obj

@transaction.atomic
def add_finished_review_note(*,handover_id,actor,key,note):
    obj=FinishedHandover.objects.select_for_update().get(pk=handover_id)
    actor=User.objects.get(pk=actor.pk)
    involved=(actor.role=='production_officer' and actor.pk==obj.sent_by_id) or (actor.role=='store_officer' and actor.store_type=='finished' and actor.pk==obj.recipient_id)
    if actor.status!='active' or not (involved or actor.role in ('manager','md')): raise ValidationError('Only the people involved or management can add a review note.')
    if obj.status!='disputed': raise ValidationError('This handover is not under review.')
    if not isinstance(note,str) or not note.strip() or len(note.strip())>1000: raise ValidationError('Enter a review note of up to 1,000 characters.')
    return FinishedReviewNote.objects.create(request_key=key,handover=obj,note=note.strip(),recorded_by=actor)

@transaction.atomic
def record_finished_store_count(*,actor,key,material,pack_size_kg,counted_packs,counted_at,scope,note=''):
    actor=User.objects.get(pk=actor.pk)
    if actor.status!='active' or not (actor.role in ('manager','md') or (actor.role=='store_officer' and actor.store_type=='finished')): raise ValidationError('Only the finished-goods store officer or management can record a store count.')
    size=weight(pack_size_kg)
    if material not in VALID_MATERIALS or size is None or size>Decimal('999999.99'): raise ValidationError('Select a valid product and size.')
    counted=count(counted_packs,allow_zero=True)
    if not isinstance(counted_at, datetime) or timezone.is_naive(counted_at) or counted_at>timezone.now(): raise ValidationError('Enter a valid count time that is not in the future.')
    if not isinstance(scope,str) or not scope.strip() or len(scope.strip())>300: raise ValidationError('Describe what was counted.')
    if not isinstance(note,str) or len(note.strip())>1000: raise ValidationError('Note must be at most 1,000 characters.')
    position=FinishedStoreStock.objects.select_for_update().filter(material=material,pack_size_kg=size).first()
    return FinishedStoreCount.objects.create(request_key=key,material=material,pack_size_kg=size,counted_packs=counted,counted_at=counted_at,scope=scope.strip(),note=note.strip(),recorded_balance=position.packs if position else None,recorded_by=actor)

@transaction.atomic
def send_sales_goods(*,actor,key,date,material,pack_size_kg,packs,recipient):
    actor=User.objects.get(pk=actor.pk)
    if actor.status!='active' or actor.role!='store_officer' or actor.store_type!='finished': raise ValidationError('Only an active finished-goods store officer can send goods.')
    recipient=User.objects.get(pk=recipient.pk)
    if recipient.status!='active' or recipient.role!='sales_manager':raise ValidationError('Select an active sales manager.')
    size=weight(pack_size_kg);packs=count(packs)
    if material not in VALID_MATERIALS or size is None or size>Decimal('999999.99'):raise ValidationError('Select a valid product and size.')
    if date>timezone.localdate():raise ValidationError('Date cannot be in the future.')
    stock=FinishedStoreStock.objects.select_for_update().filter(material=material,pack_size_kg=size).first()
    if stock is None or packs>stock.packs:raise ValidationError('Not enough recorded packs in the store.')
    if FinishedStockEvent.objects.filter(material=material,pack_size_kg=size,kind='received',occurred_on__gt=date).exists() or SalesGoodsHandover.objects.filter(material=material,pack_size_kg=size,date__gt=date).exists():raise ValidationError('Date cannot be before a later stock movement.')
    obj=SalesGoodsHandover.objects.create(request_key=key,date=date,material=material,pack_size_kg=size,packs=packs,sent_by=actor,recipient=recipient)
    stock.packs-=packs;stock.save(update_fields=['packs'])
    SalesGoodsEvent.objects.create(handover=obj,kind='sent',recorded_by=actor)
    return obj

@transaction.atomic
def decide_sales_goods(*,handover_id,actor,accept,reason=''):
    obj=SalesGoodsHandover.objects.select_for_update().get(pk=handover_id)
    actor=User.objects.get(pk=actor.pk)
    if actor.status!='active' or actor.role!='sales_manager' or actor.pk!=obj.recipient_id:raise ValidationError('Only the assigned sales manager can review this handover.')
    if obj.status!='pending':raise ValidationError('This handover has already been reviewed.')
    if not isinstance(accept,bool):raise ValidationError('Select a decision.')
    if not isinstance(reason,str) or len(reason.strip())>300:raise ValidationError('Enter a valid review reason.')
    if not accept and not reason.strip():raise ValidationError('Enter a reason for review.')
    if accept:
        SalesManagerStock.objects.get_or_create(officer=actor,material=obj.material,pack_size_kg=obj.pack_size_kg)
        holding=SalesManagerStock.objects.select_for_update().get(officer=actor,material=obj.material,pack_size_kg=obj.pack_size_kg)
        holding.packs+=obj.packs;holding.save(update_fields=['packs'])
        SalesGoodsEvent.objects.create(handover=obj,kind='received',recorded_by=actor)
        obj.status='received'
    else:obj.status='disputed'
    obj.reason='' if accept else reason.strip();obj.decided_by=actor;obj.decided_at=timezone.now()
    obj.save(update_fields=['status','reason','decided_by','decided_at'])
    return obj

@transaction.atomic
def return_sales_goods(*,handover_id,actor):
    obj=SalesGoodsHandover.objects.select_for_update().get(pk=handover_id)
    actor=User.objects.get(pk=actor.pk)
    if actor.status!='active' or actor.pk!=obj.sent_by_id or actor.role!='store_officer' or actor.store_type!='finished':raise ValidationError('Only the sender can confirm the return.')
    if obj.status!='disputed':raise ValidationError('This handover is not awaiting return.')
    stock=FinishedStoreStock.objects.select_for_update().get(material=obj.material,pack_size_kg=obj.pack_size_kg)
    stock.packs+=obj.packs;stock.save(update_fields=['packs'])
    SalesGoodsEvent.objects.create(handover=obj,kind='returned',recorded_by=actor)
    obj.status='returned';obj.returned_by=actor;obj.returned_at=timezone.now()
    obj.save(update_fields=['status','returned_by','returned_at'])
    return obj
