"""Transactional development ledger. It intentionally makes no delivery cost allocation."""
from decimal import Decimal, InvalidOperation
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from .models import StockPosition, StockMovement, CleaningJob, CleaningReturn, ProductionTransfer
from procurement.models import MATERIAL_CHOICES

VALID_MATERIALS = {v for v, _ in MATERIAL_CHOICES}

def qty(value, *, allow_zero=False):
    try:
        value = Decimal(str(value))
        if not value.is_finite() or value < 0 or (not allow_zero and value == 0) or value != value.quantize(Decimal('.01')) or value > Decimal('999999999999.99'):
            raise ValueError
        return value
    except (InvalidOperation, ValueError, TypeError):
        raise ValidationError('Enter a valid weight in kilograms.')

def _post(*, material, source, destination, amount, date, actor, **reference):
    if material not in VALID_MATERIALS or source == destination:
        raise ValidationError('Invalid stock movement.')
    amount = qty(amount)
    locations = sorted(set([destination] + ([source] if source else [])))
    for loc in locations:
        StockPosition.objects.get_or_create(material=material, location=loc)
    positions = {p.location:p for p in StockPosition.objects.select_for_update().filter(material=material, location__in=locations).order_by('location')}
    if source:
        if positions[source].quantity_kg < amount:
            raise ValidationError('Not enough available stock.')
        positions[source].quantity_kg -= amount
        positions[source].save(update_fields=['quantity_kg'])
    positions[destination].quantity_kg += amount
    positions[destination].save(update_fields=['quantity_kg'])
    return StockMovement.objects.create(material=material, from_location=source or '', to_location=destination, quantity_kg=amount, occurred_on=date, recorded_by=actor, **reference)

@transaction.atomic
def post_receipt(receipt, actor):
    return _post(material=receipt.material_type, source=None, destination='raw_store', amount=receipt.approx_weight_kg, date=receipt.date, actor=actor, receipt=receipt)

@transaction.atomic
def send_to_cleaner(*, key, date, material, cleaner, amount, actor):
    if not cleaner.strip():
        raise ValidationError('Enter the cleaner’s name.')
    amount = qty(amount)
    job = CleaningJob.objects.create(request_key=key, date=date, material=material, cleaner=cleaner.strip(), issued_kg=amount, remaining_kg=amount, issued_by=actor)
    _post(material=material, source='raw_store', destination='cleaning', amount=amount, date=date, actor=actor, cleaning_job=job)
    return job

@transaction.atomic
def receive_from_cleaner(*, key, job_id, date, clean, loss, actor):
    clean, loss = qty(clean, allow_zero=True), qty(loss, allow_zero=True)
    if clean + loss <= 0:
        raise ValidationError('Enter a weight returned or lost.')
    job = CleaningJob.objects.select_for_update().get(pk=job_id)
    if date < job.date:
        raise ValidationError('Date cannot be before the material was sent.')
    if clean + loss > job.remaining_kg:
        raise ValidationError('The total exceeds the amount still with the cleaner.')
    returned = CleaningReturn.objects.create(request_key=key, job=job, date=date, clean_kg=clean, loss_kg=loss, received_by=actor)
    for dest, amount in [('clean_store', clean), ('loss', loss)]:
        if amount:
            _post(material=job.material, source='cleaning', destination=dest, amount=amount, date=date, actor=actor, cleaning_job=job, cleaning_return=returned)
    job.remaining_kg -= clean + loss
    job.save(update_fields=['remaining_kg'])
    return returned

@transaction.atomic
def send_to_production(*, key, date, material, amount, sender, recipient):
    amount = qty(amount)
    if recipient.status != 'active' or recipient.role != 'production_officer' or recipient.pk == sender.pk:
        raise ValidationError('Select an active production officer.')
    transfer = ProductionTransfer.objects.create(request_key=key, date=date, material=material, quantity_kg=amount, sent_by=sender, recipient=recipient)
    _post(material=material, source='clean_store', destination='transit', amount=amount, date=date, actor=sender, transfer=transfer)
    return transfer

@transaction.atomic
def decide_transfer(*, transfer_id, actor, accept, reason=''):
    transfer = ProductionTransfer.objects.select_for_update().get(pk=transfer_id)
    if actor.pk != transfer.recipient_id or actor.status != 'active' or actor.role != 'production_officer':
        raise ValidationError('Only the assigned production officer can confirm this handover.')
    if transfer.status != 'pending':
        raise ValidationError('This handover has already been reviewed.')
    if not accept and not reason.strip():
        raise ValidationError('Enter a reason for returning the handover.')
    _post(material=transfer.material, source='transit', destination='production' if accept else 'clean_store', amount=transfer.quantity_kg, date=timezone.localdate(), actor=actor, transfer=transfer)
    transfer.status = 'accepted' if accept else 'rejected'
    transfer.decision_by, transfer.decided_at = actor, timezone.now()
    transfer.rejection_reason = '' if accept else reason.strip()
    transfer.save(update_fields=['status','decision_by','decided_at','rejection_reason'])
    return transfer
