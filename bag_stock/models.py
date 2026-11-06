"""Bag-first operational records; optional observed weights are never inferred."""
import uuid
from django.db import models
from django.db.models import Q
from accounts.models import User
from procurement.models import MATERIAL_CHOICES, RawMaterialReceipt

LOCATION_CHOICES = [('raw_store','Raw store'),('cleaning','With cleaner'),('clean_store','Clean store'),('transit','Awaiting production receipt'),('production','Production')]

class BagPosition(models.Model):
    material = models.CharField(max_length=10, choices=MATERIAL_CHOICES)
    location = models.CharField(max_length=20, choices=LOCATION_CHOICES)
    bags = models.PositiveIntegerField(default=0)
    class Meta:
        constraints = [models.UniqueConstraint(fields=['material','location'], name='bag_unique_position'), models.CheckConstraint(condition=Q(bags__gte=0),name='bag_position_nonnegative')]

class CleaningJob(models.Model):
    request_key = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    date = models.DateField()
    material = models.CharField(max_length=10,choices=MATERIAL_CHOICES)
    cleaner = models.CharField(max_length=200)
    issued_bags = models.PositiveIntegerField()
    # Retained only for old development records; never used to infer stock.
    remaining_input_bags = models.PositiveIntegerField(null=True, blank=True)
    status = models.CharField(max_length=16, choices=[('in_progress','In progress'),('closed','Completed'),('needs_review','Needs review')], default='in_progress')
    counts_differ = models.BooleanField(default=False)
    weight_kg = models.DecimalField(max_digits=12,decimal_places=2,null=True,blank=True)
    issued_by = models.ForeignKey(User,on_delete=models.PROTECT,related_name='bag_cleaning_jobs')
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        ordering=['-created_at']
        constraints=[models.CheckConstraint(condition=Q(issued_bags__gt=0),name='bag_job_positive'), models.CheckConstraint(condition=Q(remaining_input_bags__lte=models.F('issued_bags')),name='bag_job_remaining_lte_issued')]

class CleaningReturn(models.Model):
    request_key = models.UUIDField(default=uuid.uuid4,unique=True,editable=False)
    job = models.ForeignKey(CleaningJob,on_delete=models.PROTECT,related_name='returns')
    date = models.DateField()
    # Legacy development data only; staff are no longer asked for this.
    input_bags_accounted = models.PositiveIntegerField(null=True, blank=True)
    is_final = models.BooleanField(null=True, blank=True)
    clean_bags = models.PositiveIntegerField()
    clean_weight_kg = models.DecimalField(max_digits=12,decimal_places=2,null=True,blank=True)
    loss_weight_kg = models.DecimalField(max_digits=12,decimal_places=2,null=True,blank=True)
    received_by = models.ForeignKey(User,on_delete=models.PROTECT,related_name="bag_cleaning_returns")
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        constraints=[models.CheckConstraint(condition=Q(input_bags_accounted__gt=0), name='bag_return_positive_input')]

class ProductionTransfer(models.Model):
    request_key=models.UUIDField(default=uuid.uuid4,unique=True,editable=False)
    date=models.DateField()
    material=models.CharField(max_length=10,choices=MATERIAL_CHOICES)
    bags=models.PositiveIntegerField()
    weight_kg=models.DecimalField(max_digits=12,decimal_places=2,null=True,blank=True)
    sent_by=models.ForeignKey(User,on_delete=models.PROTECT,related_name='bag_transfers_sent')
    recipient=models.ForeignKey(User,on_delete=models.PROTECT,related_name='bag_transfers_received')
    status=models.CharField(max_length=12,choices=[('pending','Waiting'),('accepted','Received'),('rejected','Returned')],default='pending')
    decision_by=models.ForeignKey(User,on_delete=models.PROTECT,null=True,blank=True,related_name='bag_transfers_decided')
    decided_at=models.DateTimeField(null=True,blank=True)
    rejection_reason=models.CharField(max_length=300,blank=True)
    created_at=models.DateTimeField(auto_now_add=True)
    class Meta:
        ordering=['-created_at']
        constraints=[models.CheckConstraint(condition=Q(bags__gt=0),name='bag_transfer_positive')]

class BagMovement(models.Model):
    material=models.CharField(max_length=10,choices=MATERIAL_CHOICES)
    from_location=models.CharField(max_length=20,choices=LOCATION_CHOICES,blank=True)
    to_location=models.CharField(max_length=20,choices=LOCATION_CHOICES,blank=True)
    bags=models.PositiveIntegerField()
    occurred_on=models.DateField()
    recorded_by=models.ForeignKey(User,on_delete=models.PROTECT)
    kind=models.CharField(max_length=30)
    receipt=models.ForeignKey(RawMaterialReceipt,null=True,blank=True,on_delete=models.PROTECT,related_name='bag_movements')
    cleaning_job=models.ForeignKey(CleaningJob,null=True,blank=True,on_delete=models.PROTECT,related_name='movements')
    cleaning_return=models.ForeignKey(CleaningReturn,null=True,blank=True,on_delete=models.PROTECT,related_name='movements')
    transfer=models.ForeignKey(ProductionTransfer,null=True,blank=True,on_delete=models.PROTECT,related_name='movements')
    milling=models.ForeignKey('MillingRecord',null=True,blank=True,on_delete=models.PROTECT,related_name='bag_movements')
    created_at=models.DateTimeField(auto_now_add=True)
    class Meta:
        ordering=['-created_at','-id']
        constraints=[models.CheckConstraint(condition=Q(bags__gt=0),name='bag_movement_positive'),models.UniqueConstraint(fields=['receipt'],condition=Q(receipt__isnull=False),name='bag_one_movement_per_receipt')]
    def save(self,*args,**kwargs):
        if self.pk: raise ValueError('Stock movements cannot be edited.')
        return super().save(*args,**kwargs)
    def delete(self,*args,**kwargs):
        raise ValueError('Stock movements cannot be deleted.')

class ProductionHolding(models.Model):
    """Confirmed clean bags held by one officer, not source attribution."""
    officer=models.ForeignKey(User,on_delete=models.PROTECT,related_name='production_holdings')
    material=models.CharField(max_length=10,choices=MATERIAL_CHOICES)
    bags=models.PositiveIntegerField(default=0)
    class Meta:
        constraints=[models.UniqueConstraint(fields=['officer','material'],name='production_holding_unique'),models.CheckConstraint(condition=Q(bags__gte=0),name='production_holding_nonnegative')]

class PowderHolding(models.Model):
    officer=models.ForeignKey(User,on_delete=models.PROTECT,related_name='powder_holdings')
    material=models.CharField(max_length=10,choices=MATERIAL_CHOICES)
    # None means remaining quantity is unknown, never zero.
    kg=models.DecimalField(max_digits=12,decimal_places=2,default=0,null=True,blank=True)
    class Meta:
        constraints=[models.UniqueConstraint(fields=['officer','material'],name='powder_holding_unique'),models.CheckConstraint(condition=Q(kg__gte=0),name='powder_holding_nonnegative')]

SHIFT_CHOICES=[('morning','Morning'),('afternoon','Afternoon'),('night','Night')]
class MillingRecord(models.Model):
    request_key=models.UUIDField(default=uuid.uuid4,unique=True,editable=False)
    date=models.DateField()
    material=models.CharField(max_length=10,choices=MATERIAL_CHOICES)
    shift=models.CharField(max_length=10,choices=SHIFT_CHOICES)
    bags=models.PositiveIntegerField()
    input_weight_kg=models.DecimalField(max_digits=12,decimal_places=2,null=True,blank=True)
    powder_kg=models.DecimalField(max_digits=12,decimal_places=2)
    powder_bags=models.PositiveIntegerField(null=True,blank=True)
    machine=models.CharField(max_length=100,blank=True)
    officer=models.ForeignKey(User,on_delete=models.PROTECT,related_name='new_milling_records')
    created_at=models.DateTimeField(auto_now_add=True)
    class Meta:
        ordering=['-date','-created_at']
        constraints=[models.CheckConstraint(condition=Q(bags__gt=0),name='milling_bags_positive'),models.CheckConstraint(condition=Q(powder_kg__gt=0),name='milling_powder_positive'),models.CheckConstraint(condition=Q(powder_bags__isnull=True)|Q(powder_bags__gt=0),name='milling_powder_bags_positive')]

class PackagingRecord(models.Model):
    request_key=models.UUIDField(default=uuid.uuid4,unique=True,editable=False)
    date=models.DateField()
    material=models.CharField(max_length=10,choices=MATERIAL_CHOICES)
    shift=models.CharField(max_length=10,choices=SHIFT_CHOICES)
    powder_used_kg=models.DecimalField(max_digits=12,decimal_places=2,null=True,blank=True)
    powder_used_bags=models.PositiveIntegerField(null=True,blank=True)
    packs=models.PositiveIntegerField()
    pack_size_kg=models.DecimalField(max_digits=8,decimal_places=2)
    officer=models.ForeignKey(User,on_delete=models.PROTECT,related_name='new_packaging_records')
    created_at=models.DateTimeField(auto_now_add=True)
    class Meta:
        ordering=['-date','-created_at']
        constraints=[models.CheckConstraint(condition=Q(packs__gt=0),name='packaging_packs_positive'),models.CheckConstraint(condition=Q(powder_used_kg__isnull=True)|Q(powder_used_kg__gt=0),name='packaging_powder_positive'),models.CheckConstraint(condition=Q(powder_used_bags__isnull=True)|Q(powder_used_bags__gt=0),name='packaging_bags_positive'),models.CheckConstraint(condition=Q(pack_size_kg__gt=0),name='packaging_size_positive')]

class FinishedProductionStock(models.Model):
    officer=models.ForeignKey(User,on_delete=models.PROTECT,related_name='finished_production_stocks')
    material=models.CharField(max_length=10,choices=MATERIAL_CHOICES)
    pack_size_kg=models.DecimalField(max_digits=8,decimal_places=2)
    packs=models.PositiveIntegerField(default=0)
    class Meta:
        constraints=[models.UniqueConstraint(fields=['officer','material','pack_size_kg'],name='fg_prod_stock_unique'),models.CheckConstraint(condition=Q(packs__gte=0),name='fg_prod_stock_nonnegative'),models.CheckConstraint(condition=Q(pack_size_kg__gt=0),name='fg_prod_stock_size_positive')]

class FinishedStoreStock(models.Model):
    material=models.CharField(max_length=10,choices=MATERIAL_CHOICES)
    pack_size_kg=models.DecimalField(max_digits=8,decimal_places=2)
    packs=models.PositiveIntegerField(default=0)
    class Meta:
        constraints=[models.UniqueConstraint(fields=['material','pack_size_kg'],name='fg_store_stock_unique'),models.CheckConstraint(condition=Q(packs__gte=0),name='fg_store_stock_nonnegative'),models.CheckConstraint(condition=Q(pack_size_kg__gt=0),name='fg_store_stock_size_positive')]

class FinishedHandover(models.Model):
    request_key=models.UUIDField(default=uuid.uuid4,unique=True,editable=False)
    date=models.DateField()
    material=models.CharField(max_length=10,choices=MATERIAL_CHOICES)
    pack_size_kg=models.DecimalField(max_digits=8,decimal_places=2)
    packs=models.PositiveIntegerField()
    sent_by=models.ForeignKey(User,on_delete=models.PROTECT,related_name='finished_handover_sent')
    recipient=models.ForeignKey(User,on_delete=models.PROTECT,related_name='finished_handover_received')
    status=models.CharField(max_length=12,choices=[('pending','Waiting'),('partial','Part received'),('accepted','Received'),('disputed','Needs review'),('returned','Returned'),('resolved','Resolved')],default='pending')
    received_packs=models.PositiveIntegerField(default=0)
    returned_packs=models.PositiveIntegerField(default=0)
    resolved_by=models.ForeignKey(User,on_delete=models.PROTECT,null=True,blank=True,related_name='finished_handover_resolutions')
    resolved_at=models.DateTimeField(null=True,blank=True)
    resolution_note=models.CharField(max_length=300,blank=True)
    decision_by=models.ForeignKey(User,on_delete=models.PROTECT,null=True,blank=True,related_name='finished_handover_decisions')
    decided_at=models.DateTimeField(null=True,blank=True)
    reason=models.CharField(max_length=300,blank=True)
    returned_by=models.ForeignKey(User,on_delete=models.PROTECT,null=True,blank=True,related_name='finished_handover_returns')
    returned_at=models.DateTimeField(null=True,blank=True)
    created_at=models.DateTimeField(auto_now_add=True)
    class Meta:
        ordering=['-created_at','-id']
        constraints=[models.CheckConstraint(condition=Q(packs__gt=0),name='fg_handover_packs_positive'),models.CheckConstraint(condition=Q(pack_size_kg__gt=0),name='fg_handover_size_positive'),models.CheckConstraint(condition=Q(received_packs__lte=models.F('packs')-models.F('returned_packs')),name='fg_handover_accounted_lte_sent')]

class FinishedStockEvent(models.Model):
    material=models.CharField(max_length=10,choices=MATERIAL_CHOICES)
    pack_size_kg=models.DecimalField(max_digits=8,decimal_places=2)
    packs=models.PositiveIntegerField()
    kind=models.CharField(max_length=20,choices=[('packaged','Packaged'),('sent','Sent'),('received','Received'),('returned','Returned')])
    recorded_by=models.ForeignKey(User,on_delete=models.PROTECT)
    occurred_on=models.DateField()
    packaging=models.ForeignKey(PackagingRecord,on_delete=models.PROTECT,null=True,blank=True,related_name='finished_events')
    handover=models.ForeignKey(FinishedHandover,on_delete=models.PROTECT,null=True,blank=True,related_name='stock_events')
    receipt=models.OneToOneField('FinishedPartialReceipt',on_delete=models.PROTECT,null=True,blank=True,related_name='stock_event')
    goods_return=models.OneToOneField('FinishedPartialReturn',on_delete=models.PROTECT,null=True,blank=True,related_name='stock_event')
    created_at=models.DateTimeField(auto_now_add=True)
    class Meta:
        ordering=['-created_at','-id']
        constraints=[models.CheckConstraint(condition=Q(packs__gt=0),name='fg_event_packs_positive'),models.UniqueConstraint(fields=['packaging'],condition=Q(packaging__isnull=False),name='fg_one_event_per_packaging')]
    def save(self,*args,**kwargs):
        if self.pk: raise ValueError('Stock events cannot be edited.')
        return super().save(*args,**kwargs)
    def delete(self,*args,**kwargs): raise ValueError('Stock events cannot be deleted.')


class FinishedPartialReceipt(models.Model):
    request_key=models.UUIDField(default=uuid.uuid4,unique=True,editable=False)
    handover=models.ForeignKey(FinishedHandover,on_delete=models.PROTECT,related_name='partial_receipts')
    packs=models.PositiveIntegerField()
    is_final=models.BooleanField()
    recorded_by=models.ForeignKey(User,on_delete=models.PROTECT)
    created_at=models.DateTimeField(auto_now_add=True)
    class Meta:
        ordering=['created_at','id']
        constraints=[models.CheckConstraint(condition=Q(packs__gt=0),name='fg_partial_receipt_positive')]
    def save(self,*args,**kwargs):
        if self.pk: raise ValueError('Handover history cannot be edited.')
        return super().save(*args,**kwargs)
    def delete(self,*args,**kwargs): raise ValueError('Handover history cannot be deleted.')

class FinishedPartialReturn(models.Model):
    request_key=models.UUIDField(default=uuid.uuid4,unique=True,editable=False)
    handover=models.ForeignKey(FinishedHandover,on_delete=models.PROTECT,related_name='partial_returns')
    packs=models.PositiveIntegerField()
    recorded_by=models.ForeignKey(User,on_delete=models.PROTECT)
    created_at=models.DateTimeField(auto_now_add=True)
    class Meta:
        ordering=['created_at','id']
        constraints=[models.CheckConstraint(condition=Q(packs__gt=0),name='fg_partial_return_positive')]
    def save(self,*args,**kwargs):
        if self.pk: raise ValueError('Handover history cannot be edited.')
        return super().save(*args,**kwargs)
    def delete(self,*args,**kwargs): raise ValueError('Handover history cannot be deleted.')

class FinishedReviewNote(models.Model):
    request_key=models.UUIDField(default=uuid.uuid4,unique=True,editable=False)
    handover=models.ForeignKey(FinishedHandover,on_delete=models.PROTECT,related_name='review_notes')
    note=models.CharField(max_length=1000)
    recorded_by=models.ForeignKey(User,on_delete=models.PROTECT)
    created_at=models.DateTimeField(auto_now_add=True)
    class Meta:
        ordering=['created_at','id']
    def save(self,*args,**kwargs):
        if self.pk: raise ValueError('Review notes cannot be edited.')
        return super().save(*args,**kwargs)
    def delete(self,*args,**kwargs): raise ValueError('Review notes cannot be deleted.')

class FinishedStoreCount(models.Model):
    request_key=models.UUIDField(default=uuid.uuid4,unique=True,editable=False)
    material=models.CharField(max_length=10,choices=MATERIAL_CHOICES)
    pack_size_kg=models.DecimalField(max_digits=8,decimal_places=2)
    counted_packs=models.PositiveIntegerField()
    counted_at=models.DateTimeField()
    scope=models.CharField(max_length=300)
    note=models.CharField(max_length=1000,blank=True)
    recorded_balance=models.PositiveIntegerField(null=True,blank=True)
    recorded_by=models.ForeignKey(User,on_delete=models.PROTECT)
    created_at=models.DateTimeField(auto_now_add=True)
    class Meta:
        ordering=['-created_at','-id']
        constraints=[models.CheckConstraint(condition=Q(pack_size_kg__gt=0),name='fg_count_size_positive'),models.CheckConstraint(condition=Q(counted_packs__gte=0),name='fg_count_packs_nonnegative')]
    def save(self,*args,**kwargs):
        if self.pk: raise ValueError('Count records cannot be edited.')
        return super().save(*args,**kwargs)
    def delete(self,*args,**kwargs): raise ValueError('Count records cannot be deleted.')

class SalesManagerStock(models.Model):
    officer=models.ForeignKey(User,on_delete=models.PROTECT,related_name='sales_goods_holdings')
    material=models.CharField(max_length=10,choices=MATERIAL_CHOICES)
    pack_size_kg=models.DecimalField(max_digits=8,decimal_places=2)
    packs=models.PositiveIntegerField(default=0)
    class Meta:
        constraints=[models.UniqueConstraint(fields=['officer','material','pack_size_kg'],name='sales_goods_holding_unique'),models.CheckConstraint(condition=Q(packs__gte=0),name='sales_goods_holding_nonnegative'),models.CheckConstraint(condition=Q(pack_size_kg__gt=0),name='sales_goods_holding_size_positive')]

class SalesGoodsHandover(models.Model):
    request_key=models.UUIDField(default=uuid.uuid4,unique=True,editable=False)
    date=models.DateField()
    material=models.CharField(max_length=10,choices=MATERIAL_CHOICES)
    pack_size_kg=models.DecimalField(max_digits=8,decimal_places=2)
    packs=models.PositiveIntegerField()
    sent_by=models.ForeignKey(User,on_delete=models.PROTECT,related_name='sales_goods_sent')
    recipient=models.ForeignKey(User,on_delete=models.PROTECT,related_name='sales_goods_assigned')
    status=models.CharField(max_length=12,choices=[('pending','Waiting'),('received','Received'),('disputed','Needs review'),('returned','Returned')],default='pending')
    reason=models.CharField(max_length=300,blank=True)
    decided_by=models.ForeignKey(User,on_delete=models.PROTECT,null=True,blank=True,related_name='sales_goods_decisions')
    decided_at=models.DateTimeField(null=True,blank=True)
    returned_by=models.ForeignKey(User,on_delete=models.PROTECT,null=True,blank=True,related_name='sales_goods_returned')
    returned_at=models.DateTimeField(null=True,blank=True)
    created_at=models.DateTimeField(auto_now_add=True)
    class Meta:
        ordering=['-created_at','-id']
        constraints=[models.CheckConstraint(condition=Q(packs__gt=0),name='sales_handover_packs_positive'),models.CheckConstraint(condition=Q(pack_size_kg__gt=0),name='sales_handover_size_positive')]

class SalesGoodsEvent(models.Model):
    handover=models.ForeignKey(SalesGoodsHandover,on_delete=models.PROTECT,related_name='events')
    kind=models.CharField(max_length=10,choices=[('sent','Sent'),('received','Received'),('returned','Returned')])
    recorded_by=models.ForeignKey(User,on_delete=models.PROTECT)
    created_at=models.DateTimeField(auto_now_add=True)
    class Meta:
        ordering=['created_at','id']
        constraints=[models.UniqueConstraint(fields=['handover','kind'],name='sales_handover_one_event_per_kind')]
    def save(self,*args,**kwargs):
        if self.pk:raise ValueError('Handover events cannot be edited.')
        return super().save(*args,**kwargs)
    def delete(self,*args,**kwargs):raise ValueError('Handover events cannot be deleted.')

class RawReceiptSubmission(models.Model):
    request_key=models.UUIDField(unique=True,editable=False)
    receipt=models.OneToOneField(RawMaterialReceipt,on_delete=models.PROTECT,related_name='rebuild_submission')
    created_at=models.DateTimeField(auto_now_add=True)
    def save(self,*args,**kwargs):
        if self.pk:raise ValueError('Receipt submissions cannot be edited.')
        return super().save(*args,**kwargs)
    def delete(self,*args,**kwargs):raise ValueError('Receipt submissions cannot be deleted.')
