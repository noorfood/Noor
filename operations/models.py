"""New stock ledger. Legacy stock has not been imported or reconciled."""
import uuid
from django.db import models
from django.db.models import Q
from accounts.models import User
from procurement.models import MATERIAL_CHOICES, RawMaterialReceipt

LOCATION_CHOICES = [('raw_store', 'Raw store'), ('cleaning', 'With cleaner'), ('clean_store', 'Clean store'), ('transit', 'Awaiting production receipt'), ('production', 'Production'), ('loss', 'Cleaning loss')]

class StockPosition(models.Model):
    material = models.CharField(max_length=10, choices=MATERIAL_CHOICES)
    location = models.CharField(max_length=20, choices=LOCATION_CHOICES)
    quantity_kg = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    class Meta:
        constraints = [models.UniqueConstraint(fields=['material','location'], name='ops_unique_position'), models.CheckConstraint(condition=Q(quantity_kg__gte=0), name='ops_position_nonnegative')]

class CleaningJob(models.Model):
    request_key = models.UUIDField(unique=True, default=uuid.uuid4, editable=False)
    date = models.DateField()
    material = models.CharField(max_length=10, choices=MATERIAL_CHOICES)
    cleaner = models.CharField(max_length=200)
    issued_kg = models.DecimalField(max_digits=14, decimal_places=2)
    remaining_kg = models.DecimalField(max_digits=14, decimal_places=2)
    issued_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name='ops_cleaning_jobs')
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        ordering = ['-created_at']
        constraints = [models.CheckConstraint(condition=Q(issued_kg__gt=0), name='ops_job_issued_positive'), models.CheckConstraint(condition=Q(remaining_kg__gte=0), name='ops_job_remaining_nonnegative')]

class CleaningReturn(models.Model):
    request_key = models.UUIDField(unique=True, default=uuid.uuid4, editable=False)
    job = models.ForeignKey(CleaningJob, on_delete=models.PROTECT, related_name='returns')
    date = models.DateField()
    clean_kg = models.DecimalField(max_digits=14, decimal_places=2)
    loss_kg = models.DecimalField(max_digits=14, decimal_places=2)
    received_by = models.ForeignKey(User, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)

class ProductionTransfer(models.Model):
    request_key = models.UUIDField(unique=True, default=uuid.uuid4, editable=False)
    date = models.DateField()
    material = models.CharField(max_length=10, choices=MATERIAL_CHOICES)
    quantity_kg = models.DecimalField(max_digits=14, decimal_places=2)
    sent_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name='ops_transfers_sent')
    recipient = models.ForeignKey(User, on_delete=models.PROTECT, related_name='ops_transfers_received')
    status = models.CharField(max_length=12, choices=[('pending','Waiting'),('accepted','Received'),('rejected','Returned')], default='pending')
    decision_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.PROTECT, related_name='ops_transfers_decided')
    decided_at = models.DateTimeField(null=True, blank=True)
    rejection_reason = models.CharField(max_length=300, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        ordering = ['-created_at']
        constraints = [models.CheckConstraint(condition=Q(quantity_kg__gt=0), name='ops_transfer_positive')]

class StockMovement(models.Model):
    material = models.CharField(max_length=10, choices=MATERIAL_CHOICES)
    from_location = models.CharField(max_length=20, choices=LOCATION_CHOICES, blank=True)
    to_location = models.CharField(max_length=20, choices=LOCATION_CHOICES)
    quantity_kg = models.DecimalField(max_digits=14, decimal_places=2)
    occurred_on = models.DateField()
    recorded_by = models.ForeignKey(User, on_delete=models.PROTECT)
    receipt = models.ForeignKey(RawMaterialReceipt, null=True, blank=True, on_delete=models.PROTECT, related_name='new_stock_movements')
    cleaning_job = models.ForeignKey(CleaningJob, null=True, blank=True, on_delete=models.PROTECT, related_name='movements')
    cleaning_return = models.ForeignKey(CleaningReturn, null=True, blank=True, on_delete=models.PROTECT, related_name='movements')
    transfer = models.ForeignKey(ProductionTransfer, null=True, blank=True, on_delete=models.PROTECT, related_name='movements')
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        ordering = ['-created_at', '-id']
        constraints = [models.CheckConstraint(condition=Q(quantity_kg__gt=0), name='ops_movement_positive'), models.UniqueConstraint(fields=['receipt'], condition=Q(receipt__isnull=False), name='ops_one_movement_per_receipt')]
    def save(self, *args, **kwargs):
        if self.pk:
            raise ValueError('Stock movements cannot be edited.')
        super().save(*args, **kwargs)
    def delete(self, *args, **kwargs):
        raise ValueError('Stock movements cannot be deleted.')
