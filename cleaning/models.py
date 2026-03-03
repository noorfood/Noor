from django.db import models
from accounts.models import User
from procurement.models import RawMaterialIssuance, MATERIAL_CHOICES


class CleaningBatch(models.Model):
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('approved', 'Approved'),
    ]

    date = models.DateField()
    material_type = models.CharField(max_length=10, choices=MATERIAL_CHOICES)
    cleaning_manager = models.ForeignKey(User, on_delete=models.PROTECT, null=True, blank=True, related_name='cleaning_batches')
    raw_issuance = models.ForeignKey(
        RawMaterialIssuance, on_delete=models.PROTECT,
        null=True, blank=True, related_name='cleaning_batches',
        help_text='Issuance record this cleaning batch draws from'
    )
    dirty_bags_used = models.PositiveIntegerField()
    approx_dirty_weight_kg = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    clean_bags_produced = models.PositiveIntegerField()
    # Loss auto-calculated: approx_dirty_weight - (clean_bags_produced * 100)
    loss_kg = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='draft')
    approved_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True,
                                    related_name='approved_cleaning_batches')
    approved_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    is_locked = models.BooleanField(default=False)

    class Meta:
        db_table = 'cleaning_batch'
        ordering = ['-date', '-created_at']

    def __str__(self):
        return f"Cleaning #{self.pk} | {self.material_type.upper()} | {self.clean_bags_produced} clean bags | {self.date}"

    def calculate_loss(self):
        """Loss = approx dirty weight - (clean_bags_produced × 100)."""
        return float(self.approx_dirty_weight_kg) - (self.clean_bags_produced * 100)

    def save(self, *args, **kwargs):
        self.loss_kg = self.calculate_loss()
        super().save(*args, **kwargs)


class CleanRawReceipt(models.Model):
    """Clean 100kg bags received into store (after cleaning)."""
    date = models.DateField()
    cleaning_batch = models.OneToOneField(CleaningBatch, on_delete=models.PROTECT, related_name='store_receipt')
    material_type = models.CharField(max_length=10, choices=MATERIAL_CHOICES)
    num_bags = models.PositiveIntegerField()
    weight_per_bag_kg = models.PositiveIntegerField(default=100)
    received_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name='clean_receipts')
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    is_locked = models.BooleanField(default=True)

    class Meta:
        db_table = 'cleaning_clean_receipt'
        ordering = ['-date', '-created_at']

    def __str__(self):
        return f"Clean Receipt #{self.pk} | {self.num_bags} bags × 100kg | {self.date}"
