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
        query_size = '10kg' if product_size == '1kg' else product_size
        config = cls.objects.filter(
            channel=channel,
            material_type=material_type,
            product_size=query_size,
            effective_from__lte=sale_date
        ).order_by('-effective_from').first()
        
        if config:
            if product_size == '1kg' and config.product_size == '10kg':
                return config.price_per_unit / 10
            return config.price_per_unit
        return None


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
        query_size = '10kg' if product_size == '1kg' else product_size
        config = cls.objects.filter(
            channel='sales_team',
            material_type=material_type,
            product_size=query_size,
            effective_from__lte=sale_date
        ).order_by('-effective_from').first()
        return float(config.commission_pct) if config else 0.0


class SalesTarget(models.Model):
    """MD-set monthly sales target for a Sales Manager."""
    sales_manager = models.ForeignKey(
        User, on_delete=models.PROTECT, related_name='sales_targets',
        limit_choices_to={'role': 'sales_manager'}
    )
    TARGET_TYPE_CHOICES = [
        ('monthly', 'Monthly'),
        ('weekly', 'Weekly'),
    ]
    target_type = models.CharField(max_length=10, choices=TARGET_TYPE_CHOICES, default='monthly')
    material_type = models.CharField(max_length=10, choices=MATERIAL_CHOICES, default='maize')
    product_size = models.CharField(max_length=5, choices=PRODUCT_SIZE_CHOICES, default='10kg')
    month = models.PositiveSmallIntegerField(null=True, blank=True, help_text='Month number 1–12')
    week = models.PositiveSmallIntegerField(null=True, blank=True, help_text='ISO week number 1–53')
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
        ordering = ['-year', '-month', '-week', 'sales_manager__full_name']
        unique_together = ('sales_manager', 'material_type', 'product_size', 'target_type', 'month', 'week', 'year')

    @property
    def actual_qty(self):
        """Calculate verified sacks sold for this target's criteria."""
        from sales.models import SalesRecord
        
        filters = {
            'recorded_by': self.sales_manager,
            'material_type': self.material_type,
            'product_size': self.product_size,
            'date__year': self.year,
            'status__in': ['issued', 'paid', 'partial']
        }
        
        if self.target_type == 'weekly' and self.week:
            filters['date__week'] = self.week
        elif self.month:
            filters['date__month'] = self.month
            
        return SalesRecord.objects.filter(**filters).aggregate(total=models.Sum('qty_sold'))['total'] or 0

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

class PackagingCostConfig(models.Model):
    """MD-only configuration for the global cost of packaging (sacks + nylon)."""
    cost_per_sack = models.DecimalField(max_digits=10, decimal_places=2, help_text='Cost of one empty sack + stitching/branding')
    nylon_cost_per_piece = models.DecimalField(max_digits=10, decimal_places=2, default=0, help_text='Cost of one nylon liner')
    effective_from = models.DateField()
    created_by = models.ForeignKey(User, on_delete=models.PROTECT, limit_choices_to={'role': 'md'})
    created_at = models.DateTimeField(auto_now_add=True)
    notes = models.TextField(blank=True)

    class Meta:
        db_table = 'pricing_packaging_cost'
        ordering = ['-effective_from']

    def __str__(self):
        return f"Global Packaging Cost | ₦{self.cost_per_sack} | From {self.effective_from}"

    @classmethod
    def get_active_config(cls, date):
        """Return the active config object on a given date. Falls back to earliest if none found."""
        config = cls.objects.filter(effective_from__lte=date).order_by('-effective_from').first()
        if config:
            return config
        return cls.objects.order_by('effective_from').first()

class CleaningCostConfig(models.Model):
    """MD-only configuration for material-specific cleaning fees."""
    material_type = models.CharField(max_length=10, choices=MATERIAL_CHOICES, default='maize')
    cleaning_cost_per_bag = models.DecimalField(max_digits=10, decimal_places=2, default=0, help_text='Pre-cleaning payment per 100kg raw bag')
    effective_from = models.DateField()
    created_by = models.ForeignKey(User, on_delete=models.PROTECT, limit_choices_to={'role': 'md'})
    created_at = models.DateTimeField(auto_now_add=True)
    notes = models.TextField(blank=True)

    class Meta:
        db_table = 'pricing_cleaning_cost'
        ordering = ['-effective_from', 'material_type']

    def __str__(self):
        return f"Cleaning Cost | {self.material_type} | ₦{self.cleaning_cost_per_bag} | From {self.effective_from}"

    @classmethod
    def get_active_config(cls, material_type, date):
        """Return the active cleaning config for a material on a given date. Falls back to earliest if none found."""
        config = cls.objects.filter(
            material_type=material_type,
            effective_from__lte=date
        ).order_by('-effective_from').first()
        if config:
            return config
        return cls.objects.filter(material_type=material_type).order_by('effective_from').first()

class LabourCostConfig(models.Model):
    """MD-only configuration for the global labour cost per sold sack."""
    labour_cost_per_sack = models.DecimalField(
        max_digits=10, decimal_places=2, default=0, 
        help_text='Labour cost per 10kg sack sold (automated)'
    )
    effective_from = models.DateField()
    created_by = models.ForeignKey(User, on_delete=models.PROTECT, limit_choices_to={'role': 'md'})
    created_at = models.DateTimeField(auto_now_add=True)
    notes = models.TextField(blank=True)

    class Meta:
        db_table = 'pricing_labour_cost'
        ordering = ['-effective_from']

    def __str__(self):
        return f"Labour Cost | ₦{self.labour_cost_per_sack} | From {self.effective_from}"

    @classmethod
    def get_active_config(cls, date):
        """Return the active labour config on a given date. Falls back to earliest if none found."""
        if not date:
            return None
        config = cls.objects.filter(
            effective_from__lte=date
        ).order_by('-effective_from').first()
        if config:
            return config
        return cls.objects.order_by('effective_from').first()

class OperationalExpense(models.Model):
    """General operational expenses recorded by the MD for P&L tracking."""
    date = models.DateField()
    description = models.CharField(max_length=255, help_text='E.g., Fuel, Salaries, Maintenance')
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    notes = models.TextField(blank=True)
    recorded_by = models.ForeignKey(User, on_delete=models.PROTECT, limit_choices_to={'role': 'md'})
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'pricing_expense'
        ordering = ['-date', '-created_at']

    def __str__(self):
        return f"Expense | {self.date} | {self.description} | ₦{self.amount}"
