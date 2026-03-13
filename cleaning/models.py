from django.db import models
from accounts.models import User
from procurement.models import RawMaterialIssuance, MATERIAL_CHOICES


class CleanRawReceipt(models.Model):
    """Clean 100kg bags received into store (after cleaning)."""
    date = models.DateField()
    raw_issuance = models.ForeignKey(
        RawMaterialIssuance, on_delete=models.PROTECT, 
        related_name='clean_receipts', null=True, blank=True,
        help_text='Issuance record this receipt draws from'
    )
    approx_dirty_weight_kg = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    loss_kg = models.DecimalField(max_digits=10, decimal_places=2, default=0)
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

    def calculate_loss(self):
        """Loss = approx dirty weight - (clean bags × 100)."""
        return float(self.approx_dirty_weight_kg) - (self.num_bags * self.weight_per_bag_kg)

    def save(self, *args, **kwargs):
        self.loss_kg = self.calculate_loss()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Clean Receipt #{self.pk} | {self.num_bags} bags × 100kg | {self.date}"
