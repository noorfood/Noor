from datetime import date as date_type
from decimal import Decimal, InvalidOperation
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from accounts.models import User
from bag_stock.models import SalesManagerStock, SalesGoodsHandover
from bag_stock.services import count, weight, VALID_MATERIALS
from .models import ReportedSale, ReportedCustomerPayment

MAX_PRICE=Decimal('9999999999.99')
MAX_TOTAL=Decimal('999999999999.99')
def money(value, maximum):
    try:
        val=Decimal(str(value))
        if not val.is_finite() or val<=0 or val>maximum or val!=val.quantize(Decimal('.01')):raise ValueError
        return val
    except (InvalidOperation,ValueError,TypeError):raise ValidationError('Enter a valid amount greater than zero.')

def actor_for_sale(actor):
    actor=User.objects.get(pk=actor.pk)
    if actor.status!='active' or actor.role!='sales_manager':raise ValidationError('Only an active sales manager can record this.')
    return actor

def valid_date(value):
    if not isinstance(value,date_type) or value>timezone.localdate():raise ValidationError('Enter a valid date that is not in the future.')
    return value

@transaction.atomic
def record_sale(*,actor,key,date,material,pack_size_kg,packs,unit_price,buyer='',notes=''):
    actor=actor_for_sale(actor);valid_date(date)
    size=weight(pack_size_kg);packs=count(packs);price=money(unit_price,MAX_PRICE)
    if material not in VALID_MATERIALS or size is None or size>Decimal('999999.99'):raise ValidationError('Select a valid product and size.')
    if not isinstance(buyer,str) or len(buyer.strip())>200 or not isinstance(notes,str) or len(notes.strip())>1000:raise ValidationError('Enter a valid buyer and notes.')
    total=price*packs
    if total>MAX_TOTAL:raise ValidationError('Sale value is too large.')
    holding=SalesManagerStock.objects.select_for_update().filter(officer=actor,material=material,pack_size_kg=size).first()
    if holding is None or holding.packs<packs:raise ValidationError('Not enough recorded packs available to you.')
    if SalesGoodsHandover.objects.filter(recipient=actor,material=material,pack_size_kg=size,status='received',decided_at__date__gt=date).exists() or ReportedSale.objects.filter(recorded_by=actor,material=material,pack_size_kg=size,date__gt=date).exists():raise ValidationError('Date cannot be before later recorded goods or sales.')
    sale=ReportedSale.objects.create(request_key=key,date=date,material=material,pack_size_kg=size,packs=packs,unit_price=price,total=total,buyer=buyer.strip(),notes=notes.strip(),recorded_by=actor)
    holding.packs-=packs;holding.save(update_fields=['packs'])
    return sale

@transaction.atomic
def record_customer_payment(*,sale_id,actor,key,date,amount,method,note=''):
    sale=ReportedSale.objects.select_for_update().get(pk=sale_id)
    actor=actor_for_sale(actor);valid_date(date)
    if sale.recorded_by_id!=actor.pk:raise ValidationError('Only the sales manager who recorded this sale can record its customer payment.')
    if date<sale.date:raise ValidationError('Payment date cannot be before the sale date.')
    if method not in ('cash','transfer'):raise ValidationError('Select a payment method.')
    if not isinstance(note,str) or len(note.strip())>500:raise ValidationError('Enter a valid note.')
    return ReportedCustomerPayment.objects.create(request_key=key,sale=sale,date=date,method=method,amount=money(amount,MAX_TOTAL),note=note.strip(),recorded_by=actor)

@transaction.atomic
def report_money_handover(*,actor,recipient_id,key,date,method,amount,reference='',note=''):
    from .models import MoneyHandover, MoneyHandoverEvent
    actor=User.objects.get(pk=actor.pk)
    if actor.status!='active' or actor.role not in ('sales_manager','manager'):raise ValidationError('Only an active sales manager or general manager can report this.')
    recipient=User.objects.filter(pk=recipient_id,status='active').first()
    required_role='manager' if actor.role=='sales_manager' else 'md'
    if not recipient or recipient.role!=required_role or recipient.pk==actor.pk:raise ValidationError('Select an active authorized recipient.')
    valid_date(date)
    if method not in ('cash','transfer'):raise ValidationError('Select a payment method.')
    if not isinstance(reference,str) or len(reference.strip())>150 or not isinstance(note,str) or len(note.strip())>500:raise ValidationError('Enter a valid reference and note.')
    handover=MoneyHandover.objects.create(request_key=key,date=date,sender=actor,recipient=recipient,route='sales_to_gm' if actor.role=='sales_manager' else 'gm_to_md',method=method,amount=money(amount,MAX_TOTAL),reference=reference.strip(),note=note.strip())
    MoneyHandoverEvent.objects.create(handover=handover,kind='sent',actor=actor)
    return handover

def _money_recipient(handover, actor):
    actor=User.objects.get(pk=actor.pk)
    expected='manager' if handover.route=='sales_to_gm' else 'md' if handover.route=='gm_to_md' else None
    if actor.status!='active' or actor.pk!=handover.recipient_id or actor.role!=expected:
        raise ValidationError('Only the assigned authorized recipient can review this handover.')
    return actor

def _received_total(handover):
    from django.db.models import Sum
    return handover.receipts.exclude(corrections__status='approved').aggregate(total=Sum('amount'))['total'] or Decimal('0')

@transaction.atomic
def record_money_receipt(*,handover_id,actor,key,amount,note=''):
    from .models import MoneyHandover, MoneyHandoverEvent, MoneyHandoverReceipt
    h=MoneyHandover.objects.select_for_update().get(pk=handover_id)
    actor=_money_recipient(h,actor)
    if h.status not in ('pending','review'):raise ValidationError('This handover is no longer open.')
    if not isinstance(note,str) or len(note.strip())>500:raise ValidationError('Enter a valid note.')
    amount=money(amount,MAX_TOTAL)
    remaining=h.amount-_received_total(h)
    if amount>remaining:raise ValidationError('Receipt exceeds the amount still unconfirmed. Request review instead.')
    if amount==remaining and h.status=='review' and not note.strip():raise ValidationError('Enter a resolution note when completing a handover under review.')
    receipt=MoneyHandoverReceipt.objects.create(handover=h,request_key=key,actor=actor,amount=amount,note=note.strip())
    if amount==remaining:
        h.status='confirmed';h.reason=note.strip();h.decided_at=timezone.now();h.decided_by=actor
        h.save(update_fields=['status','reason','decided_at','decided_by'])
        MoneyHandoverEvent.objects.create(handover=h,kind='confirmed',actor=actor,reason=note.strip())
    return receipt

@transaction.atomic
def decide_money_handover(*,handover_id,actor,decision,reason=''):
    from .models import MoneyHandover, MoneyHandoverEvent, MoneyHandoverReceipt
    h=MoneyHandover.objects.select_for_update().get(pk=handover_id)
    actor=_money_recipient(h,actor)
    if decision not in ('confirmed','review'):raise ValidationError('Select a valid action.')
    if h.status not in ('pending','review') or (h.status=='review' and decision!='confirmed'):raise ValidationError('This action is no longer available.')
    if not isinstance(reason,str) or len(reason.strip())>500 or ((decision=='review' or h.status=='review') and not reason.strip()):raise ValidationError('Enter a reason for review or resolution.')
    if decision=='confirmed':
        remaining=h.amount-_received_total(h)
        if remaining<=0:raise ValidationError('There is no unconfirmed amount.')
        MoneyHandoverReceipt.objects.create(handover=h,actor=actor,amount=remaining,note=reason.strip())
    h.status=decision;h.reason=reason.strip();h.decided_at=timezone.now();h.decided_by=actor
    h.save(update_fields=['status','reason','decided_at','decided_by'])
    MoneyHandoverEvent.objects.create(handover=h,kind=decision,actor=actor,reason=reason.strip())
    return h

@transaction.atomic
def report_payment_allocation(*,actor,payment_id,handover_id,key,amount,note=''):
    """Link reports only. Row locks protect both limits on supported databases."""
    from django.db.models import Sum
    from .models import MoneyHandover, ReportedPaymentAllocation
    actor=actor_for_sale(actor)
    # Always lock payment before handover to reduce inconsistent lock order.
    payment=ReportedCustomerPayment.objects.select_for_update().get(pk=payment_id)
    h=MoneyHandover.objects.select_for_update().get(pk=handover_id)
    if payment.recorded_by_id!=actor.pk or h.sender_id!=actor.pk or h.route!='sales_to_gm':
        raise ValidationError('Only your own customer payment and sales-to-GM handover can be linked.')
    if not isinstance(note,str) or len(note.strip())>500:raise ValidationError('Enter a valid note.')
    amount=money(amount,MAX_TOTAL)
    p_total=payment.handover_allocations.exclude(corrections__status='approved').aggregate(n=Sum('amount'))['n'] or Decimal('0')
    h_total=h.payment_allocations.exclude(corrections__status='approved').aggregate(n=Sum('amount'))['n'] or Decimal('0')
    if amount>payment.amount-p_total or amount>h.amount-h_total:
        raise ValidationError('Amount exceeds the remaining unlinked amount on the payment or handover.')
    return ReportedPaymentAllocation.objects.create(request_key=key,payment=payment,handover=h,amount=amount,recorded_by=actor,note=note.strip())


@transaction.atomic
def request_money_correction(*,actor,handover_id,kind,target_id,key,reason):
    from .models import MoneyHandover, MoneyHandoverReceipt, ReportedPaymentAllocation, MoneyCorrectionRequest
    actor=User.objects.get(pk=actor.pk)
    h=MoneyHandover.objects.select_for_update().get(pk=handover_id)
    roles={'sales_to_gm':('sales_manager','manager'),'gm_to_md':('manager','md')}.get(h.route)
    allowed=roles and ((actor.pk==h.sender_id and actor.role==roles[0]) or (actor.pk==h.recipient_id and actor.role==roles[1]))
    if actor.status!='active' or not allowed:
        raise ValidationError('Only an active authorized handover participant can request a correction.')
    if not isinstance(reason,str) or not reason.strip() or len(reason.strip())>500:raise ValidationError('Enter a reason.')
    if kind=='receipt':
        target=MoneyHandoverReceipt.objects.filter(pk=target_id,handover=h).first();field='receipt'
    elif kind=='allocation':
        target=ReportedPaymentAllocation.objects.filter(pk=target_id,handover=h).first();field='allocation'
    else:raise ValidationError('Select a valid record.')
    if not target:raise ValidationError('Record not found for this handover.')
    if target.corrections.filter(status__in=['pending','approved']).exists():raise ValidationError('This record already has a pending or approved correction.')
    return MoneyCorrectionRequest.objects.create(request_key=key,handover=h,requested_by=actor,reason=reason.strip(),**{field:target})

@transaction.atomic
def decide_money_correction(*,actor,correction_id,decision,note):
    from .models import MoneyHandover, MoneyHandoverEvent, MoneyCorrectionRequest
    actor=User.objects.get(pk=actor.pk)
    c=MoneyCorrectionRequest.objects.select_for_update().get(pk=correction_id)
    if actor.status!='active' or actor.role!='md':raise ValidationError('Only an active MD can review corrections.')
    original_actor=c.receipt.actor_id if c.receipt_id else c.allocation.recorded_by_id
    if actor.pk in (c.requested_by_id,original_actor):raise ValidationError('A different MD must review this request.')
    if c.status!='pending' or decision not in ('approved','rejected'):raise ValidationError('This request is no longer awaiting a decision.')
    if not isinstance(note,str) or not note.strip() or len(note.strip())>500:raise ValidationError('Enter a decision note.')
    # Match the allocation creation lock order: payment then handover.
    if c.allocation_id:ReportedCustomerPayment.objects.select_for_update().get(pk=c.allocation.payment_id)
    h=MoneyHandover.objects.select_for_update().get(pk=c.handover_id)
    if (c.receipt_id and c.receipt.handover_id!=h.pk) or (c.allocation_id and c.allocation.handover_id!=h.pk):raise ValidationError('Correction target does not belong to this handover.')
    if decision=='approved' and ((c.receipt_id and c.receipt.corrections.filter(status='approved').exists()) or (c.allocation_id and c.allocation.corrections.filter(status='approved').exists())):
        raise ValidationError('This record was already corrected.')
    c.status=decision;c.decision_note=note.strip();c.decided_by=actor;c.decided_at=timezone.now()
    c.save(update_fields=['status','decision_note','decided_by','decided_at'])
    if decision=='approved' and c.receipt_id:
        h.status='review';h.reason='Receipt correction approved';h.decided_at=timezone.now();h.decided_by=actor
        h.save(update_fields=['status','reason','decided_at','decided_by'])
        MoneyHandoverEvent.objects.create(handover=h,kind='corrected',actor=actor,reason=note.strip())
    return c
