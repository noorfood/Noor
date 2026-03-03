from django.db import models
from accounts.models import User


MATERIAL_CHOICES = [
    ('maize', 'Maize'),
    ('wheat', 'Wheat'),
]


class RawMaterialReceipt(models.Model):
    """Dirty raw material received from market (pre-clean stage)."""
    date = models.DateField()
    material_type = models.CharField(max_length=10, choices=MATERIAL_CHOICES)
    supplier = models.CharField(max_length=200)
    num_bags = models.PositiveIntegerField()
    approx_weight_kg = models.DecimalField(max_digits=10, decimal_places=2, help_text='Approximate total weight in kg')
    reference_no = models.CharField(max_length=100, blank=True)
    received_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name='raw_receipts')
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    is_locked = models.BooleanField(default=True)

    class Meta:
        db_table = 'procurement_receipt'
        ordering = ['-date', '-created_at']

    def __str__(self):
        return f"Receipt #{self.pk} | {self.material_type.upper()} | {self.num_bags} bags | {self.date}"


class RawMaterialIssuance(models.Model):
    """Dirty raw material issued to a cleaning manager."""
    date = models.DateField()
    receipt = models.ForeignKey(RawMaterialReceipt, on_delete=models.PROTECT, related_name='issuances', null=True, blank=True)
    material_type = models.CharField(max_length=10, choices=MATERIAL_CHOICES)
    num_bags_issued = models.PositiveIntegerField()
    issued_to = models.CharField(max_length=200, help_text='Name of the cleaner or contractor')
    issued_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name='raw_issued_by')
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    is_locked = models.BooleanField(default=True)

    class Meta:
        db_table = 'procurement_issuance'
        ordering = ['-date', '-created_at']

    def __str__(self):
        return f"Issuance #{self.pk} | {self.num_bags_issued} bags → {self.issued_to} | {self.date}"
