from django.db import models
from accounts.models import User
from procurement.models import MATERIAL_CHOICES
from clean_store.models import CleanRawIssuance

FLAG_CHOICES = [
    ('normal', 'Normal'),
    ('warning', 'Warning'),
    ('critical', 'Critical'),
]

SHIFT_CHOICES = [
    ('morning', 'Morning'),
    ('afternoon', 'Afternoon'),
    ('night', 'Night'),
]

STATUS_CHOICES = [
    ('open', 'Open'),
    ('complete', 'Complete'),
    ('flagged', 'Flagged'),
]


class ProductionThreshold(models.Model):
    """MD-configurable thresholds for loss flag logic. Versioned."""
    material_type = models.CharField(max_length=10, choices=MATERIAL_CHOICES)
    standard_weight_per_bag_kg = models.PositiveIntegerField(default=100)
    expected_loss_pct = models.DecimalField(max_digits=5, decimal_places=2, default=9.00)
    normal_max_loss_pct = models.DecimalField(max_digits=5, decimal_places=2, default=9.00)
    warning_max_loss_pct = models.DecimalField(max_digits=5, decimal_places=2, default=19.00)
    effective_from = models.DateField()
    created_by = models.ForeignKey(User, on_delete=models.PROTECT, limit_choices_to={'role': 'md'})
    created_at = models.DateTimeField(auto_now_add=True)
    notes = models.TextField(blank=True)

    class Meta:
        db_table = 'production_threshold'
        ordering = ['-effective_from']

    def __str__(self):
        return f"Threshold | {self.material_type.upper()} | Normal≤{self.normal_max_loss_pct}% | Warn≤{self.warning_max_loss_pct}% | From {self.effective_from}"


class MillingBatch(models.Model):
    """Milling phase: bags in, bulk powder out."""
    date = models.DateField()
    shift = models.CharField(max_length=10, choices=SHIFT_CHOICES)
    material_type = models.CharField(max_length=10, choices=MATERIAL_CHOICES)
    machine = models.CharField(max_length=100, blank=True)
    production_officer = models.ForeignKey(User, on_delete=models.PROTECT,
                                           related_name='milling_batches',
                                           limit_choices_to={'role': 'production_officer'})
    bags_milled_new = models.PositiveIntegerField(default=0, help_text='New bags milled today (from Available Balance)')
    outstanding_bags_milled = models.PositiveIntegerField(default=0, help_text='Old bags milled today (from Outstanding)')
    # Bulk powder output
    bulk_powder_kg = models.DecimalField(max_digits=12, decimal_places=2, help_text='Actual weight of powder produced')

    # Calculated fields (set on save)
    total_raw_kg = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    loss_kg = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    loss_pct = models.DecimalField(max_digits=6, decimal_places=2, default=0)

    # Flag (set on save, not visible to production officer)
    flag_level = models.CharField(max_length=10, choices=FLAG_CHOICES, default='normal')
    flag_reason = models.TextField(blank=True)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='open')

    # MD correction
    is_locked = models.BooleanField(default=True)
    unlocked_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True,
                                    related_name='unlocked_milling_batches')
    correction_note = models.TextField(blank=True)

    submitted_at = models.DateTimeField(auto_now_add=True)
    created_at = models.DateTimeField(auto_now_add=True)
    notes = models.TextField(blank=True)

    class Meta:
        db_table = 'production_milling_batch'
        ordering = ['-date', '-created_at']

    def __str__(self):
        return f"Milling #{self.pk} | {self.material_type.upper()} | {self.bulk_powder_kg} kg | {self.date}"

    def calculate_outputs(self):
        # Total bags = new bags recorded (outstanding field removed from UI)
        total_milled = self.bags_milled_new + self.outstanding_bags_milled
        total_raw = total_milled * 100
        loss = float(total_raw) - float(self.bulk_powder_kg)
        loss_p = (loss / total_raw * 100) if total_raw > 0 else 0
        return total_raw, loss, loss_p

    def _get_active_threshold(self):
        """Fetch the most recent ProductionThreshold effective on or before this batch's date."""
        return ProductionThreshold.objects.filter(
            material_type=self.material_type,
            effective_from__lte=self.date
        ).order_by('-effective_from').first()

    def determine_flag(self, loss_pct, threshold=None):
        # Load from DB if not supplied
        if threshold is None:
            threshold = self._get_active_threshold()

        if threshold:
            normal_max = float(threshold.normal_max_loss_pct)
            warning_max = float(threshold.warning_max_loss_pct)
        else:
            # Fallback to hardcoded defaults if MD hasn't set thresholds yet
            normal_max = 9.0
            warning_max = 19.0

        if loss_pct <= normal_max:
            return 'normal', ''
        elif loss_pct <= warning_max:
            return 'warning', f'Loss {loss_pct:.1f}% exceeds normal threshold ({normal_max}%). Manager review required.'
        else:
            return 'critical', f'Loss {loss_pct:.1f}% is CRITICAL (above {warning_max}%). Immediate manager review required.'

    def save(self, *args, **kwargs):
        total_raw, loss, loss_p = self.calculate_outputs()
        self.total_raw_kg = total_raw
        self.loss_kg = loss
        self.loss_pct = round(float(loss_p), 2)

        flag, reason = self.determine_flag(float(self.loss_pct))
        self.flag_level = flag
        self.flag_reason = reason

        if flag in ('warning', 'critical'):
            self.status = 'flagged'
        else:
            self.status = 'complete'

        super().save(*args, **kwargs)


class PackagingBatch(models.Model):
    """Packaging phase: bulk powder in, 10kg sacks out."""
    date = models.DateField()
    shift = models.CharField(max_length=10, choices=SHIFT_CHOICES)
    material_type = models.CharField(max_length=10, choices=MATERIAL_CHOICES)
    production_officer = models.ForeignKey(User, on_delete=models.PROTECT,
                                           related_name='packaging_batches',
                                           limit_choices_to={'role': 'production_officer'})
    milling_batch = models.ForeignKey(MillingBatch, on_delete=models.PROTECT, related_name='packaging_batches',
                                      help_text='Milling batch this powder is drawn from')
    powder_used_kg = models.DecimalField(max_digits=12, decimal_places=2, help_text='Kg of powder used')
    qty_10kg = models.PositiveIntegerField(default=0, help_text='Number of 10kg sacks packaged')

    # Packaging Costs (auto-calculated)
    packaging_unit_cost = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    total_packaging_cost = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    # Calculated loss for packaging (if powder spills during sacking)
    total_output_kg = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    loss_kg = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    loss_pct = models.DecimalField(max_digits=6, decimal_places=2, default=0)

    # Flag for consistency
    flag_level = models.CharField(max_length=10, choices=FLAG_CHOICES, default='normal')
    flag_reason = models.TextField(blank=True)

    is_locked = models.BooleanField(default=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    @property
    def get_qty_issued(self):
        """Sum of all sacks already issued to store for this batch (pending or accepted)."""
        from django.db.models import Sum
        return self.fg_receipts.filter(status__in=['pending', 'accepted']).aggregate(t=models.Sum('qty_received'))['t'] or 0

    @property
    def get_qty_remaining(self):
        """Sacks still in the production officer's hand."""
        return max(0, self.qty_10kg - self.get_qty_issued)

    @property
    def is_fully_issued(self):
        return self.get_qty_remaining == 0

    class Meta:
        db_table = 'production_packaging_batch'
        ordering = ['-date', '-created_at']

    def __str__(self):
        return f"Packaging #{self.pk} | {self.qty_10kg} sacks | {self.date}"

    def _get_active_threshold(self):
        """Fetch the most recent ProductionThreshold effective on or before this batch's date."""
        return ProductionThreshold.objects.filter(
            material_type=self.material_type,
            effective_from__lte=self.date
        ).order_by('-effective_from').first()

    def save(self, *args, **kwargs):
        self.total_output_kg = float(self.qty_10kg) * 10
        self.loss_kg = float(self.powder_used_kg) - float(self.total_output_kg)
        self.loss_pct = round(float(self.loss_kg / float(self.powder_used_kg) * 100), 2) if self.powder_used_kg > 0 else 0

        # Use MD-configured thresholds, fall back to defaults
        threshold = self._get_active_threshold()
        if threshold:
            normal_max = float(threshold.normal_max_loss_pct)
            warning_max = float(threshold.warning_max_loss_pct)
        else:
            normal_max = 9.0
            warning_max = 19.0

        loss = float(self.loss_pct)
        if loss <= normal_max:
            self.flag_level, self.flag_reason = 'normal', ''
        elif loss <= warning_max:
            self.flag_level, self.flag_reason = 'warning', f'Packaging Loss {loss:.1f}% exceeds normal threshold ({normal_max}%).'
        else:
            self.flag_level, self.flag_reason = 'critical', f'Packaging Loss {loss:.1f}% is CRITICAL (above {warning_max}%).'

        # Calculate Packaging Costs
        from pricing.models import PackagingCostConfig
        p_config = PackagingCostConfig.get_active_config(self.date)
        if p_config:
            u_cost = float(p_config.cost_per_sack) + float(p_config.nylon_cost_per_piece)
            self.packaging_unit_cost = u_cost
            self.total_packaging_cost = u_cost * float(self.qty_10kg)

        super().save(*args, **kwargs)


class BrandSale(models.Model):
    """Waste/pill-back seeds (brand) sold per sack by General Manager."""
    PAYMENT_CHOICES = [
        ('cash', 'Cash'),
        ('transfer', 'Transfer'),
        ('mixed', 'Cash + Transfer'),
    ]
    date = models.DateField()
    material_type = models.CharField(max_length=10, choices=MATERIAL_CHOICES)
    qty_sacks = models.PositiveIntegerField(help_text='Number of brand sacks sold')
    buyer_name = models.CharField(max_length=200)
    price_per_sack = models.DecimalField(max_digits=12, decimal_places=2)
    total_amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    payment_method = models.CharField(max_length=10, choices=PAYMENT_CHOICES)
    amount_cash = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    amount_transfer = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    recorded_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name='brand_sales',
                                    limit_choices_to={'role': 'manager'})
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    is_locked = models.BooleanField(default=True)

    class Meta:
        db_table = 'production_brand_sale'
        ordering = ['-date', '-created_at']

    def save(self, *args, **kwargs):
        self.total_amount = float(self.price_per_sack) * self.qty_sacks
        super().save(*args, **kwargs)

    def __str__(self):
        return (f"Brand Sale #{self.pk} | {self.material_type} × {self.qty_sacks} sacks"
                f" | ₦{self.total_amount} | {self.date}")
