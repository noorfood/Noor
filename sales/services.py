"""Sales correction services.

Follows the commerce money-correction pattern, adapted to SalesResult:

- Only the sales manager who recorded the result (or a manager overseeing
  them) may request a correction, with a reason.
- Only an MD who is neither the requester nor the original recorder may
  decide. Approval does NOT edit amounts in place: it marks the original
  record corrected, which excludes it from live holding, performance and
  reconciliation totals, and the recorder then enters a replacement
  SalesResult through the normal flow. The original stays in history.
- Rejection changes nothing and a new request may be made afterwards.
- Duplicate pending/approved requests for the same record are blocked.
- All writes are atomic with row locks, matching commerce services.
"""
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from sales.models import SalesCorrectionRequest, SalesResult


def _active_request(result):
    return SalesCorrectionRequest.objects.filter(
        sales_result=result, status__in=('pending', 'approved')
    ).first()


@transaction.atomic
def request_sales_correction(actor, sales_result_id, reason, key):
    result = SalesResult.objects.select_for_update().get(pk=sales_result_id)
    if actor.role not in ('sales_manager', 'manager'):
        raise ValidationError('Only the recording sales manager or a manager may request a sales correction.')
    if actor.role == 'sales_manager' and result.recorded_by_id != actor.pk:
        raise ValidationError('A sales manager may only request correction of a result they recorded.')
    if not (reason or '').strip():
        raise ValidationError('A correction reason is required.')
    if result.is_corrected:
        raise ValidationError('This sales result has already been corrected.')
    if _active_request(result) is not None:
        raise ValidationError('A correction request for this sales result is already pending or approved.')
    return SalesCorrectionRequest.objects.create(
        request_key=key, sales_result=result, requested_by=actor,
        reason=reason.strip(), status='pending',
    )


@transaction.atomic
def decide_sales_correction(actor, correction_id, decision, note):
    if actor.role != 'md':
        raise ValidationError('Only an MD may decide a sales correction.')
    correction = SalesCorrectionRequest.objects.select_for_update().get(pk=correction_id)
    result = SalesResult.objects.select_for_update().get(pk=correction.sales_result_id)
    if correction.status != 'pending':
        raise ValidationError('This correction request has already been decided.')
    if actor.pk == correction.requested_by_id:
        raise ValidationError('The MD who decides must not be the requester.')
    if actor.pk == result.recorded_by_id:
        raise ValidationError('The MD who decides must not be the original recorder.')
    if decision not in ('approved', 'rejected'):
        raise ValidationError('Decision must be approved or rejected.')
    if not (note or '').strip():
        raise ValidationError('A decision note is required.')
    correction.status = decision
    correction.decision_note = note.strip()
    correction.decided_by = actor
    correction.decided_at = timezone.now()
    correction.save()
    if decision == 'approved':
        result.is_corrected = True
        result.correction_note = (
            f"Corrected on MD approval of request #{correction.pk}: {note.strip()}. "
            f"Original reason: {correction.reason}"
        )
        result.save()
    return correction
