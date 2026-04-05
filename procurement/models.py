from django.db import models
from accounts.models import User


MATERIAL_CHOICES = [
    ('maize', 'Maize'),
    ('wheat', 'Wheat'),
]

COST_STATUS_CHOICES = [
    ('pending', 'Pending MD Review'),
    ('approved', 'Cost Approved'),
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

    # MD-approved purchase cost
    cost_per_bag = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True,
        help_text='Purchase cost per bag (entered by MD)'
    )
    total_cost = models.DecimalField(
        max_digits=14, decimal_places=2, null=True, blank=True,
        help_text='Total purchase cost = cost_per_bag × num_bags (auto-calculated)'
    )
    cost_status = models.CharField(
        max_length=10, choices=COST_STATUS_CHOICES, default='pending',
        help_text='Whether the MD has reviewed and set the cost for this receipt'
    )
    cost_approved_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='procurement_costs_approved',
        help_text='MD who set the cost for this receipt'
    )
    cost_approved_at = models.DateTimeField(null=True, blank=True)

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
    is_fully_received = models.BooleanField(default=False, help_text='Set to True when all clean bags are back in store')
    created_at = models.DateTimeField(auto_now_add=True)
    is_locked = models.BooleanField(default=True)

    class Meta:
        db_table = 'procurement_issuance'
        ordering = ['-date', '-created_at']

    def __str__(self):
        return f"Issuance #{self.pk} | {self.num_bags_issued} bags → {self.issued_to} | {self.date}"


class CleaningLossConfig(models.Model):
    """
    MD-configurable maximum acceptable cleaning loss percentage per material type.
    If the actual cleaning loss exceeds this threshold, the system displays a warning.
    The cleaning loss is calculated as: (raw_bags_in - clean_bags_out) / raw_bags_in * 100
    """
    material_type = models.CharField(max_length=10, choices=MATERIAL_CHOICES)
    max_loss_pct = models.DecimalField(
        max_digits=5, decimal_places=2,
        help_text='Maximum acceptable cleaning loss percentage (e.g. 5.00 = 5%)'
    )
    effective_from = models.DateField()
    created_by = models.ForeignKey(
        User, on_delete=models.PROTECT,
        limit_choices_to={'role': 'md'},
        related_name='cleaning_loss_configs',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    notes = models.TextField(blank=True)

    class Meta:
        db_table = 'procurement_cleaning_loss_config'
        ordering = ['-effective_from', 'material_type']

    def __str__(self):
        return f"CleaningLoss | {self.material_type.upper()} | Max {self.max_loss_pct}% | From {self.effective_from}"

    @classmethod
    def get_active_threshold(cls, material_type, date):
        """Return the active max cleaning loss % for a material on a given date."""
        config = cls.objects.filter(
            material_type=material_type,
            effective_from__lte=date,
        ).order_by('-effective_from').first()
        return float(config.max_loss_pct) if config else None
