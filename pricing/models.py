from django.db import models
from accounts.models import User
from finished_store.models import PRODUCT_SIZE_CHOICES, CHANNEL_CHOICES
from procurement.models import MATERIAL_CHOICES

# CommissionConfig channel choices — who earns commission on sales under the SM
COMMISSION_CHANNEL_CHOICES = [
    ('sales_team', 'Sales Team'),
]


class PriceConfig(models.Model):
    """MD-only price configuration, versioned per channel, material type, and product size."""
    channel = models.CharField(max_length=15, choices=CHANNEL_CHOICES)
    material_type = models.CharField(
        max_length=10, choices=MATERIAL_CHOICES, default='maize',
        help_text='Maize or Wheat'
    )
    product_size = models.CharField(max_length=5, choices=PRODUCT_SIZE_CHOICES)
    price_per_unit = models.DecimalField(max_digits=12, decimal_places=2)
    effective_from = models.DateField()
    created_by = models.ForeignKey(User, on_delete=models.PROTECT, limit_choices_to={'role': 'md'})
    created_at = models.DateTimeField(auto_now_add=True)
    notes = models.TextField(blank=True)

    class Meta:
        db_table = 'pricing_config'
        ordering = ['-effective_from', 'channel', 'material_type', 'product_size']

    def __str__(self):
        return (f"Price | {self.channel}/{self.material_type}/{self.product_size} "
                f"| ₦{self.price_per_unit} | From {self.effective_from}")

    @classmethod
    def get_active_price(cls, channel, material_type, product_size, sale_date):
        """Return the correct price for a given channel, material, size, and date."""
        config = cls.objects.filter(
            channel=channel,
            material_type=material_type,
            product_size=product_size,
            effective_from__lte=sale_date
        ).order_by('-effective_from').first()
        return config.price_per_unit if config else None


class CommissionConfig(models.Model):
    """MD-only commission configuration per sales channel, material type, and product size."""
    channel = models.CharField(
        max_length=20,
        choices=COMMISSION_CHANNEL_CHOICES,
        help_text='Commission applies to everyone in the sales team'
    )
    material_type = models.CharField(max_length=10, choices=MATERIAL_CHOICES, default='maize')
    product_size = models.CharField(max_length=5, choices=PRODUCT_SIZE_CHOICES)
    commission_pct = models.DecimalField(
        max_digits=5, decimal_places=2,
        help_text='Commission percentage (e.g. 10.00 = 10%)'
    )
    effective_from = models.DateField()
    created_by = models.ForeignKey(User, on_delete=models.PROTECT, limit_choices_to={'role': 'md'})
    created_at = models.DateTimeField(auto_now_add=True)
    notes = models.TextField(blank=True)

    class Meta:
        db_table = 'pricing_commission_config'
        ordering = ['-effective_from', 'channel', 'material_type', 'product_size']

    def __str__(self):
        return (f"Commission | {self.channel}/{self.material_type}/{self.product_size} "
                f"| {self.commission_pct}% | From {self.effective_from}")

    @classmethod
    def get_active_pct(cls, channel, material_type, product_size, sale_date):
        """Return the active commission % for a channel/material/size on a given date."""
        # Force looking up the 'sales_team' configuration as per user request
        config = cls.objects.filter(
            channel='sales_team',
            material_type=material_type,
            product_size=product_size,
            effective_from__lte=sale_date
        ).order_by('-effective_from').first()
        return float(config.commission_pct) if config else 0.0


class SalesTarget(models.Model):
    """MD-set monthly sales target for a Sales Manager."""
    sales_manager = models.ForeignKey(
        User, on_delete=models.PROTECT, related_name='sales_targets',
        limit_choices_to={'role': 'sales_manager'}
    )
    material_type = models.CharField(max_length=10, choices=MATERIAL_CHOICES, default='maize')
    product_size = models.CharField(max_length=5, choices=PRODUCT_SIZE_CHOICES)
    month = models.PositiveSmallIntegerField(help_text='Month number 1–12')
    year = models.PositiveSmallIntegerField()
    target_qty = models.PositiveIntegerField(help_text='Target number of sacks to sell')
    created_by = models.ForeignKey(
        User, on_delete=models.PROTECT, related_name='targets_set',
        limit_choices_to={'role': 'md'}
    )
    created_at = models.DateTimeField(auto_now_add=True)
    notes = models.TextField(blank=True)

    class Meta:
        db_table = 'pricing_sales_target'
        ordering = ['-year', '-month', 'sales_manager__full_name']
        unique_together = ('sales_manager', 'material_type', 'product_size', 'month', 'year')

    @property
    def actual_qty(self):
        """Calculate verified sacks sold for this target's criteria."""
        from sales.models import SalesRecord
        # Sum quantity of verified (at least issued) sales for this SM during the specified month/year
        return SalesRecord.objects.filter(
            recorded_by=self.sales_manager,
            material_type=self.material_type,
            product_size=self.product_size,
            date__month=self.month,
            date__year=self.year,
            status__in=['issued', 'paid', 'partial']
        ).aggregate(total=models.Sum('qty_sold'))['total'] or 0

    @property
    def performance_pct(self):
        """Percentage of target achieved."""
        if not self.target_qty:
            return 0
        return round((self.actual_qty / self.target_qty) * 100, 1)

    def __str__(self):
        return (f"Target | {self.sales_manager.full_name} | "
                f"{self.material_type}/{self.product_size} | "
                f"{self.month}/{self.year} | {self.target_qty} sacks")
