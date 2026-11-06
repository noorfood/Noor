import uuid
from django.db import models
from django.db.models import Q
from accounts.models import User
from procurement.models import MATERIAL_CHOICES

class ReportedSale(models.Model):
    request_key=models.UUIDField(unique=True,editable=False,default=uuid.uuid4)
    date=models.DateField()
    material=models.CharField(max_length=10,choices=MATERIAL_CHOICES)
    pack_size_kg=models.DecimalField(max_digits=8,decimal_places=2)
    packs=models.PositiveIntegerField()
    unit_price=models.DecimalField(max_digits=12,decimal_places=2)
    total=models.DecimalField(max_digits=14,decimal_places=2)
    buyer=models.CharField(max_length=200,blank=True)
    notes=models.CharField(max_length=1000,blank=True)
    recorded_by=models.ForeignKey(User,on_delete=models.PROTECT,related_name='reported_sales')
    created_at=models.DateTimeField(auto_now_add=True)
    class Meta:
        ordering=['-created_at','-id']
        constraints=[models.CheckConstraint(condition=Q(packs__gt=0),name='reported_sale_packs_positive'),models.CheckConstraint(condition=Q(pack_size_kg__gt=0),name='reported_sale_size_positive'),models.CheckConstraint(condition=Q(unit_price__gt=0),name='reported_sale_price_positive'),models.CheckConstraint(condition=Q(total__gt=0),name='reported_sale_total_positive')]
    def save(self,*args,**kwargs):
        if self.pk:raise ValueError('Sale reports cannot be edited.')
        return super().save(*args,**kwargs)
    def delete(self,*args,**kwargs):raise ValueError('Sale reports cannot be deleted.')

class ReportedCustomerPayment(models.Model):
    request_key=models.UUIDField(unique=True,editable=False,default=uuid.uuid4)
    sale=models.ForeignKey(ReportedSale,on_delete=models.PROTECT,related_name='customer_payments')
    date=models.DateField()
    method=models.CharField(max_length=12,choices=[('cash','Cash'),('transfer','Transfer')])
    amount=models.DecimalField(max_digits=14,decimal_places=2)
    note=models.CharField(max_length=500,blank=True)
    recorded_by=models.ForeignKey(User,on_delete=models.PROTECT,related_name='reported_customer_payments')
    created_at=models.DateTimeField(auto_now_add=True)
    class Meta:
        ordering=['created_at','id']
        constraints=[models.CheckConstraint(condition=Q(amount__gt=0),name='reported_payment_amount_positive')]
    def save(self,*args,**kwargs):
        if self.pk:raise ValueError('Payment reports cannot be edited.')
        return super().save(*args,**kwargs)
    def delete(self,*args,**kwargs):raise ValueError('Payment reports cannot be deleted.')

class MoneyHandover(models.Model):
    """A reported money handover; confirmation is a person's statement, not bank verification."""
    request_key=models.UUIDField(unique=True,editable=False,default=uuid.uuid4)
    date=models.DateField()
    sender=models.ForeignKey(User,on_delete=models.PROTECT,related_name='money_handover_sent')
    recipient=models.ForeignKey(User,on_delete=models.PROTECT,related_name='money_handover_assigned')
    route=models.CharField(max_length=16,choices=[('sales_to_gm','Sales manager to GM'),('gm_to_md','GM to MD')])
    method=models.CharField(max_length=12,choices=[('cash','Cash'),('transfer','Transfer')])
    amount=models.DecimalField(max_digits=14,decimal_places=2)
    reference=models.CharField(max_length=150,blank=True)
    note=models.CharField(max_length=500,blank=True)
    status=models.CharField(max_length=12,choices=[('pending','Waiting'),('confirmed','Confirmed'),('review','Needs review')],default='pending')
    created_at=models.DateTimeField(auto_now_add=True)
    decided_at=models.DateTimeField(null=True,blank=True)
    decided_by=models.ForeignKey(User,on_delete=models.PROTECT,null=True,blank=True,related_name='money_handover_decisions')
    reason=models.CharField(max_length=500,blank=True)
    class Meta:
        ordering=['-created_at','-id']
        constraints=[
            models.CheckConstraint(condition=Q(amount__gt=0),name='money_handover_positive'),
            models.CheckConstraint(condition=~Q(sender=models.F('recipient')),name='money_handover_distinct_people'),
            models.CheckConstraint(condition=Q(method__in=['cash','transfer']),name='money_handover_method_valid'),
            models.CheckConstraint(condition=Q(route__in=['sales_to_gm','gm_to_md']),name='money_handover_route_valid'),
            models.CheckConstraint(condition=(Q(status='pending',decided_at__isnull=True,decided_by__isnull=True)|Q(status__in=['review','confirmed'],decided_at__isnull=False,decided_by__isnull=False)),name='money_handover_decision_consistent'),
        ]
    def save(self,*args,**kwargs):
        if self.pk and set(kwargs.get('update_fields') or ()) != {'status','reason','decided_at','decided_by'}:raise ValueError('Handover details cannot be edited.')
        return super().save(*args,**kwargs)
    def delete(self,*args,**kwargs):raise ValueError('Money handovers cannot be deleted.')

class MoneyHandoverEvent(models.Model):
    handover=models.ForeignKey(MoneyHandover,on_delete=models.PROTECT,related_name='events')
    kind=models.CharField(max_length=12,choices=[('sent','Reported'),('confirmed','Confirmed'),('review','Needs review'),('corrected','Receipt corrected')])
    actor=models.ForeignKey(User,on_delete=models.PROTECT)
    reason=models.CharField(max_length=500,blank=True)
    created_at=models.DateTimeField(auto_now_add=True)
    class Meta:
        ordering=['created_at','id']
        # Multiple decisions can occur after an approved correction.
    def save(self,*args,**kwargs):
        if self.pk:raise ValueError('Handover events cannot be edited.')
        return super().save(*args,**kwargs)
    def delete(self,*args,**kwargs):raise ValueError('Handover events cannot be deleted.')

class MoneyHandoverReceipt(models.Model):
    """A recipient's recorded receipt, not independent bank verification."""
    request_key=models.UUIDField(unique=True,editable=False,default=uuid.uuid4)
    handover=models.ForeignKey(MoneyHandover,on_delete=models.PROTECT,related_name='receipts')
    amount=models.DecimalField(max_digits=14,decimal_places=2)
    actor=models.ForeignKey(User,on_delete=models.PROTECT)
    note=models.CharField(max_length=500,blank=True)
    source=models.CharField(max_length=20,choices=[('entered','Entered'),('legacy_full','Previous full confirmation')],default='entered')
    created_at=models.DateTimeField(auto_now_add=True)
    class Meta:
        ordering=['created_at','id']
        constraints=[models.CheckConstraint(condition=Q(amount__gt=0),name='money_receipt_amount_positive'),models.CheckConstraint(condition=Q(source__in=['entered','legacy_full']),name='money_receipt_source_valid')]
    def save(self,*args,**kwargs):
        if self.pk:raise ValueError('Money receipt records cannot be edited.')
        return super().save(*args,**kwargs)
    def delete(self,*args,**kwargs):raise ValueError('Money receipt records cannot be deleted.')

class ReportedPaymentAllocation(models.Model):
    """Sender's attribution of a reported customer payment to a reported handover.

    It is neither verification of the payment nor proof of receipt by the company.
    """
    request_key=models.UUIDField(unique=True,editable=False,default=uuid.uuid4)
    payment=models.ForeignKey(ReportedCustomerPayment,on_delete=models.PROTECT,related_name='handover_allocations')
    handover=models.ForeignKey(MoneyHandover,on_delete=models.PROTECT,related_name='payment_allocations')
    amount=models.DecimalField(max_digits=14,decimal_places=2)
    recorded_by=models.ForeignKey(User,on_delete=models.PROTECT)
    note=models.CharField(max_length=500,blank=True)
    created_at=models.DateTimeField(auto_now_add=True)
    class Meta:
        ordering=['created_at','id']
        constraints=[models.CheckConstraint(condition=Q(amount__gt=0),name='reported_allocation_positive')]
    def save(self,*args,**kwargs):
        if self.pk:raise ValueError('Reported allocations cannot be edited.')
        return super().save(*args,**kwargs)
    def delete(self,*args,**kwargs):raise ValueError('Reported allocations cannot be deleted.')


class MoneyCorrectionRequest(models.Model):
    """An approved request voids one source entry, retaining its history."""
    request_key=models.UUIDField(unique=True,editable=False,default=uuid.uuid4)
    handover=models.ForeignKey(MoneyHandover,on_delete=models.PROTECT,related_name='corrections')
    receipt=models.ForeignKey(MoneyHandoverReceipt,on_delete=models.PROTECT,null=True,blank=True,related_name='corrections')
    allocation=models.ForeignKey(ReportedPaymentAllocation,on_delete=models.PROTECT,null=True,blank=True,related_name='corrections')
    reason=models.CharField(max_length=500)
    requested_by=models.ForeignKey(User,on_delete=models.PROTECT,related_name='money_corrections_requested')
    created_at=models.DateTimeField(auto_now_add=True)
    status=models.CharField(max_length=10,choices=[('pending','Waiting'),('approved','Approved'),('rejected','Rejected')],default='pending')
    decision_note=models.CharField(max_length=500,blank=True)
    decided_by=models.ForeignKey(User,on_delete=models.PROTECT,null=True,blank=True,related_name='money_corrections_decided')
    decided_at=models.DateTimeField(null=True,blank=True)
    class Meta:
        ordering=['-created_at','-id']
        constraints=[
            models.CheckConstraint(condition=(Q(receipt__isnull=False,allocation__isnull=True)|Q(receipt__isnull=True,allocation__isnull=False)),name='money_correction_one_target'),
            models.CheckConstraint(condition=(Q(status='pending',decided_at__isnull=True,decided_by__isnull=True)|Q(status__in=['approved','rejected'],decided_at__isnull=False,decided_by__isnull=False)),name='money_correction_decision_valid'),
            models.UniqueConstraint(fields=['receipt'],condition=Q(status='pending',receipt__isnull=False),name='one_pending_receipt_correction'),
            models.UniqueConstraint(fields=['allocation'],condition=Q(status='pending',allocation__isnull=False),name='one_pending_allocation_correction'),
            models.UniqueConstraint(fields=['receipt'],condition=Q(status='approved',receipt__isnull=False),name='one_approved_receipt_correction'),
            models.UniqueConstraint(fields=['allocation'],condition=Q(status='approved',allocation__isnull=False),name='one_approved_allocation_correction'),
        ]
    def save(self,*args,**kwargs):
        if self.pk and set(kwargs.get('update_fields') or ()) != {'status','decision_note','decided_by','decided_at'}:raise ValueError('Correction requests cannot be edited.')
        return super().save(*args,**kwargs)
    def delete(self,*args,**kwargs):raise ValueError('Correction requests cannot be deleted.')
