from django.db import models
from django.utils import timezone
from accounts.models import User
from procurement.models import MATERIAL_CHOICES
from finished_store.models import PRODUCT_SIZE_CHOICES, CHANNEL_CHOICES
from pricing.models import PriceConfig, CommissionConfig

ACKNOWLEDGEMENT_STATUS = [
    ('pending', 'Pending Acknowledgement'),
    ('accepted', 'Accepted'),
    ('rejected', 'Rejected'),
]


# ─────────────────────────────────────────────────────────────────────────────
# SalesPerson — entity record (NOT a system login user)
# Represents promoters and drivers who receive goods from the company.
# All their transactions are recorded by the Sales Manager on their behalf.
# ─────────────────────────────────────────────────────────────────────────────

class SalesPerson(models.Model):
    """A sales promoter or vehicle driver — a named entity, not a login user."""
    CHANNEL_CHOICES_SP = [
        ('promoter', 'Sales Promoter'),
        ('driver', 'Vehicle Driver'),
    ]
    name = models.CharField(max_length=200)
    channel = models.CharField(max_length=10, choices=CHANNEL_CHOICES_SP)
    phone = models.CharField(max_length=20, blank=True)
    status = models.CharField(max_length=10, default='active')
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name='salesperson_created')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'sales_person'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.name} ({self.get_channel_display()})"


# ─────────────────────────────────────────────────────────────────────────────
# SalesRecord — recorded by Sales Manager on behalf of a SalesPerson
# ─────────────────────────────────────────────────────────────────────────────

class SalesRecord(models.Model):
    """Sale recorded by Sales Manager on behalf of a SalesPerson (promoter/driver)."""
    STATUS_CHOICES = [
        ('pending', 'Pending Issuance'),
        ('issued', 'Goods Issued'),
        ('paid', 'Fully Paid'),
        ('partial', 'Partially Paid'),
    ]

    # Core sale info
    date = models.DateField()
    recorded_by = models.ForeignKey(
        User, on_delete=models.PROTECT, related_name='recorded_sales',
        limit_choices_to={'role': 'sales_manager'},
        null=True, blank=True  # null for legacy records
    )
    sales_person = models.ForeignKey(
        SalesPerson, on_delete=models.PROTECT, related_name='sales_records',
        null=True, blank=True  # null for legacy records that used sales_user
    )
    buyer_name = models.CharField(
        max_length=200, blank=True, 
        help_text='For direct company retail sales where no sales person is involved.'
    )
    material_type = models.CharField(
        max_length=10, choices=MATERIAL_CHOICES,
        default='maize', help_text='Maize or Wheat'
    )
    SALE_UNIT_CHOICES = [
        ('10kg', '10 KG Sacks'),
        ('1kg', '1 KG Pieces (Retail)'),
    ]
    product_size = models.CharField(max_length=10, choices=SALE_UNIT_CHOICES, default='10kg')
    channel = models.CharField(max_length=15, choices=CHANNEL_CHOICES)
    qty_sold = models.PositiveIntegerField(default=0)
    unit_price = models.DecimalField(max_digits=12, decimal_places=2)
    total_value = models.DecimalField(max_digits=14, decimal_places=2)

    # Commission fields (auto-calculated at time of recording)
    commission_pct = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    commission_amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    net_payable = models.DecimalField(max_digits=14, decimal_places=2, default=0)

    notes = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')

    # Acknowledgment fields (kept for legacy; new flow uses SalesPayment)
    acknowledged_by = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.PROTECT,
        related_name='acknowledged_sales', limit_choices_to={'role': 'sales_manager'}
    )
    acknowledged_at = models.DateTimeField(null=True, blank=True)
    amount_received_cash = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    amount_received_transfer = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    manager_notes = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    is_locked = models.BooleanField(default=True)

    class Meta:
        db_table = 'sales_record'
        ordering = ['-date', '-created_at']

    def save(self, *args, **kwargs):
        # net_payable = total_value - commission
        self.net_payable = float(self.total_value) - float(self.commission_amount)
        super().save(*args, **kwargs)

    @property
    def total_paid(self):
        """Sum of all SalesPayments + legacy direct fields."""
        from django.db.models import Sum
        payment_total = self.payments.aggregate(
            t=Sum('amount_cash') + Sum('amount_transfer')
        )['t'] or 0
        legacy = float(self.amount_received_cash) + float(self.amount_received_transfer)
        return float(payment_total) + legacy

    @property
    def amount_outstanding(self):
        """Money still owed on this sale (net_payable − total_paid)."""
        return max(0, float(self.net_payable) - self.total_paid)

    @property
    def is_fully_paid(self):
        return self.amount_outstanding == 0

    @property
    def display_person(self):
        """Return the name of whoever this sale was for."""
        if self.channel == 'company' and self.buyer_name:
            return f"{self.buyer_name} (Retail)"
        if self.sales_person:
            return self.sales_person.name
        return '—'

    def __str__(self):
        return (f"Sale #{self.pk} | {self.display_person} | "
                f"{self.product_size} × {self.qty_sold} | ₦{self.total_value} | {self.status}")


# ─────────────────────────────────────────────────────────────────────────────
# SalesPayment — partial or full payment recorded against a SalesRecord
# ─────────────────────────────────────────────────────────────────────────────

class SalesPayment(models.Model):
    """Payment recorded by Sales Manager against a SalesRecord (can be partial)."""
    sales_record = models.ForeignKey(SalesRecord, on_delete=models.PROTECT, related_name='payments')
    date = models.DateField()
    amount_cash = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    amount_transfer = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    recorded_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name='recorded_payments')
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    is_locked = models.BooleanField(default=True)

    class Meta:
        db_table = 'sales_payment'
        ordering = ['-date', '-created_at']

    @property
    def total(self):
        return float(self.amount_cash) + float(self.amount_transfer)

    def __str__(self):
        return (f"Payment #{self.pk} | Sale #{self.sales_record_id} | "
                f"₦{self.total} | {self.date}")


# ─────────────────────────────────────────────────────────────────────────────
# Company Retail Ledger (1kg Pieces)
# ─────────────────────────────────────────────────────────────────────────────

class CompanyRetailLedger(models.Model):
    """Tracks the balance of 1kg pieces available for retail Company Sales (Operations Manager).
    When pieces run out, a 10kg sack is automatically opened (deducted from FG Store).
    """
    ACTION_CHOICES = [
        ('open_sack', 'Opened 10kg Sack (+10 pieces)'),
        ('retail_sale', 'Retail Sale (Deduction)'),
        ('adjustment', 'Manager Adjustment'),
    ]
    date = models.DateField()
    material_type = models.CharField(max_length=10, choices=MATERIAL_CHOICES, default='maize')
    action = models.CharField(max_length=20, choices=ACTION_CHOICES)
    pieces_changed = models.IntegerField(help_text='Positive for added pieces, negative for sold pieces')
    sales_record = models.ForeignKey(SalesRecord, on_delete=models.SET_NULL, null=True, blank=True, related_name='retail_deductions')
    recorded_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name='retail_ledger_actions')
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'sales_retail_ledger'
        ordering = ['-date', '-created_at']

    def __str__(self):
        return f"{self.get_action_display()} | {self.material_type} | {'+' if self.pieces_changed > 0 else ''}{self.pieces_changed} pcs | {self.date}"


# ─────────────────────────────────────────────────────────────────────────────
# SalesManagerCollection — The CORE new model.
# FG Store Officer records goods released to the Sales Manager.
# Sales Manager must Accept or Reject — only after acceptance does
# the Sales Manager carry financial responsibility for those goods.
# ─────────────────────────────────────────────────────────────────────────────

class SalesManagerCollection(models.Model):
    """
    Represents a batch of finished goods issued from the FG Store to the
    Sales Manager. The Sales Manager must acknowledge receipt.

    COMPANY TRUTH: The company sells ONLY to the Sales Manager.
    Once accepted, those sacks are his responsibility — no matter what
    happens in the market.
    """
    date = models.DateField(help_text='Date goods were physically handed over')
    material_type = models.CharField(max_length=10, choices=MATERIAL_CHOICES)
    qty_sacks = models.PositiveIntegerField(help_text='Number of 10kg sacks collected')

    # The store officer who recorded this collection
    store_officer = models.ForeignKey(
        User, on_delete=models.PROTECT, related_name='sm_collections_recorded',
        limit_choices_to={'role': 'store_officer'}
    )
    # The Sales Manager who collected the goods
    sales_manager = models.ForeignKey(
        User, on_delete=models.PROTECT, related_name='sm_collections',
        limit_choices_to={'role': 'sales_manager'}
    )

    # Price at time of collection (from MD's PriceConfig for sales_manager channel)
    price_per_sack = models.DecimalField(
        max_digits=12, decimal_places=2, default=0,
        help_text='Price per 10kg sack at the time of collection (from MD price config)'
    )
    total_value = models.DecimalField(
        max_digits=14, decimal_places=2, default=0,
        help_text='Total expected value = price_per_sack × qty_sacks'
    )

    # The dual-acknowledgement handshake
    status = models.CharField(max_length=10, choices=ACKNOWLEDGEMENT_STATUS, default='pending')
    rejection_note = models.TextField(blank=True, help_text='Reason if SM rejected collection')

    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    is_locked = models.BooleanField(default=True)

    class Meta:
        db_table = 'sales_sm_collection'
        ordering = ['-date', '-created_at']

    @property
    def total_paid(self):
        """Sum of all confirmed SalesManagerPayments linked to this collection."""
        from django.db.models import Sum
        return float(
            self.payments.filter(status='confirmed').aggregate(
                t=Sum('amount_cash') + Sum('amount_transfer')
            )['t'] or 0
        )

    @property
    def amount_outstanding(self):
        return max(0, float(self.total_value) - self.total_paid)

    @property
    def is_fully_paid(self):
        return self.amount_outstanding == 0

    def save(self, *args, **kwargs):
        self.total_value = float(self.price_per_sack) * self.qty_sacks
        super().save(*args, **kwargs)

    def __str__(self):
        return (f"SM Collection #{self.pk} | {self.sales_manager.full_name} | "
                f"{self.material_type} × {self.qty_sacks} sacks | {self.status.upper()} | {self.date}")


# ─────────────────────────────────────────────────────────────────────────────
# SalesDistributionRecord — PERFORMANCE TRACKING ONLY.
# When the Sales Manager gives sacks to a promoter or driver,
# he records it here. This has ZERO financial impact on the company.
# The Sales Manager alone owes the company.
# ─────────────────────────────────────────────────────────────────────────────

class SalesDistributionRecord(models.Model):
    """
    Internal record of Sales Manager distributing sacks to his
    promoters/drivers. This is purely for performance visibility.

    RULES:
    - Does NOT reduce FG Store balance (already reduced when SM collected)
    - Does NOT create company debt for the SalesPerson
    - Does NOT affect pricing or commissions directly
    - Only used to show MD: 'who sold how much under the SM'
    """
    date = models.DateField()
    collection = models.ForeignKey(
        SalesManagerCollection, on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='distributions',
        help_text='The SM collection batch these sacks came from (optional)'
    )
    sales_person = models.ForeignKey(
        SalesPerson, on_delete=models.PROTECT, related_name='distributions'
    )
    material_type = models.CharField(max_length=10, choices=MATERIAL_CHOICES)
    qty_given = models.PositiveIntegerField(help_text='Number of 10kg sacks given to this person')
    recorded_by = models.ForeignKey(
        User, on_delete=models.PROTECT, related_name='distributions_recorded',
        limit_choices_to={'role': 'sales_manager'}
    )
    
    # Financial Projections (captured at time of distribution)
    unit_price = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    commission_pct = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    commission_amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    expected_return = models.DecimalField(max_digits=14, decimal_places=2, default=0)

    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'sales_distribution_record'
        ordering = ['-date', '-created_at']

    def save(self, *args, **kwargs):
        # Auto-calculate financial projections
        self.commission_amount = (float(self.unit_price) * self.qty_given) * (float(self.commission_pct) / 100)
        self.expected_return = (float(self.unit_price) * self.qty_given) - self.commission_amount
        super().save(*args, **kwargs)

    @property
    def gross_value(self):
        return float(self.unit_price) * self.qty_given

    def __str__(self):
        return (f"Distribution #{self.pk} | {self.sales_person.name} | "
                f"{self.material_type} × {self.qty_given} sacks | {self.date}")


# ─────────────────────────────────────────────────────────────────────────────
# SalesResult — When SP returns money to the SM, the SM records here.
# This tracks individual SP performance and reduces SM's holding balance.
# It does NOT create company debt — only the SM owes the company.
# ─────────────────────────────────────────────────────────────────────────────

class SalesResult(models.Model):
    """
    Recorded by Sales Manager when a SalesPerson returns money after selling.
    Tracks SP performance (qty sold) and reduces SM's outstanding holding.
    Commission is calculated and deducted from the gross amount.
    """
    date = models.DateField()
    distribution = models.ForeignKey(
        SalesDistributionRecord, on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='results',
        help_text='The distribution batch these sales came from (optional)'
    )
    sales_person = models.ForeignKey(
        SalesPerson, on_delete=models.PROTECT, related_name='sales_results'
    )
    material_type = models.CharField(max_length=10, choices=MATERIAL_CHOICES)
    qty_sold = models.PositiveIntegerField(help_text='Number of 10kg sacks sold by this person')
    qty_pieces_sold = models.PositiveIntegerField(default=0, help_text='Number of 1kg pieces sold by this person')
    qty_returned = models.PositiveIntegerField(default=0, help_text='Number of 10kg sacks returned to SM')
    qty_pieces_returned = models.PositiveIntegerField(default=0, help_text='Number of 1kg pieces returned to SM')

    # Commission breakdown (auto-calculated from CommissionConfig)
    unit_price = models.DecimalField(max_digits=12, decimal_places=2, default=0,
                                     help_text='Price per sack from MD config (sales_manager channel)')
    unit_price_piece = models.DecimalField(max_digits=12, decimal_places=2, default=0,
                                           help_text='Price per 1kg piece from MD config (sales_manager channel)')
    
    gross_value = models.DecimalField(max_digits=14, decimal_places=2, default=0,
                                      help_text='(qty_sold × unit_price) + (qty_pieces_sold × unit_price_piece)')
    commission_pct = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    commission_amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    # gross_value − commission_amount — reduces SM outstanding
    net_due_to_company = models.DecimalField(
        max_digits=14, decimal_places=2, default=0,
        help_text='gross_value − commission_amount — reduces SM outstanding'
    )
    
    amount_returned = models.DecimalField(max_digits=14, decimal_places=2, default=0,
                                          help_text='Actual money handed over by the SalesPerson to the SM')

    recorded_by = models.ForeignKey(
        User, on_delete=models.PROTECT, related_name='sales_results_recorded',
        limit_choices_to={'role': 'sales_manager'}
    )
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    is_locked = models.BooleanField(default=True)

    class Meta:
        db_table = 'sales_result'
        ordering = ['-date', '-created_at']

    def save(self, *args, **kwargs):
        self.gross_value = (float(self.unit_price) * self.qty_sold) + (float(self.unit_price_piece) * self.qty_pieces_sold)
        self.commission_amount = self.gross_value * float(self.commission_pct) / 100
        self.net_due_to_company = self.gross_value - self.commission_amount

        super().save(*args, **kwargs)

    @property
    def expected_amount(self):
        return float(self.net_due_to_company)
        
    @property
    def outstanding_amount(self):
        return max(0.0, self.expected_amount - float(self.amount_returned))

    @property
    def equivalent_sacks_sold(self):
        return float(self.qty_sold) + (float(self.qty_pieces_sold) / 10.0)

    @property
    def equivalent_sacks_returned(self):
        return float(self.qty_returned) + (float(self.qty_pieces_returned) / 10.0)

    def __str__(self):
        return (f"SalesResult #{self.pk} | {self.sales_person.name} sold "
                f"{self.qty_sold} sacks | Net ₦{self.net_due_to_company} | {self.date}")


# ─────────────────────────────────────────────────────────────────────────────
# SalesManagerPayment — SM sends money back to the company.
# GM must confirm receipt. Replaces the old SalesPayment flow.
# Each payment can partially or fully cover SM's outstanding balance.
# ─────────────────────────────────────────────────────────────────────────────

class SalesManagerPayment(models.Model):
    """
    Payment recorded by the Sales Manager when sending money to the company.
    The GM (manager role) must confirm receipt before it counts against
    the SM's outstanding balance.
    """
    PAYMENT_STATUS = [
        ('pending_gm', 'Pending GM Confirmation'),
        ('confirmed', 'Confirmed by GM'),
        ('rejected', 'Rejected by GM'),
    ]

    date = models.DateField()
    sales_manager = models.ForeignKey(
        User, on_delete=models.PROTECT, related_name='sm_payments',
        limit_choices_to={'role': 'sales_manager'}
    )
    amount_cash = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    amount_transfer = models.DecimalField(max_digits=14, decimal_places=2, default=0)

    # SM records this payment
    recorded_by = models.ForeignKey(
        User, on_delete=models.PROTECT, related_name='sm_payments_recorded'
    )
    notes = models.TextField(blank=True)

    # GM confirmation
    status = models.CharField(max_length=15, choices=PAYMENT_STATUS, default='pending_gm')
    confirmed_by = models.ForeignKey(
        User, on_delete=models.PROTECT, related_name='sm_payments_confirmed',
        null=True, blank=True, limit_choices_to={'role': 'manager'}
    )
    confirmed_at = models.DateTimeField(null=True, blank=True)
    gm_notes = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    is_locked = models.BooleanField(default=True)

    class Meta:
        db_table = 'sales_sm_payment'
        ordering = ['-date', '-created_at']

    @property
    def total(self):
        return float(self.amount_cash) + float(self.amount_transfer)

    def __str__(self):
        return (f"SM Payment #{self.pk} | {self.sales_manager.full_name} | "
                f"₦{self.total:,.0f} | {self.status.upper()} | {self.date}")


# ─────────────────────────────────────────────────────────────────────────────
# DirectSalePayment — GM records factory-gate / company sales
# The MD must review and confirm or reject each record.
# ─────────────────────────────────────────────────────────────────────────────

class DirectSalePayment(models.Model):
    """
    Recorded by the General Manager (role=manager) when a customer comes directly
    to the factory to purchase goods. The MD reviews and confirms the record.

    Flow:
      1. GM records sale → status=pending_md
      2. MD confirms → status=confirmed  (financial record is finalized)
      3. MD rejects  → status=rejected   (GM must correct and re-submit)
    """
    DIRECT_SALE_STATUS = [
        ('pending_md', 'Pending MD Confirmation'),
        ('confirmed', 'Confirmed by MD'),
        ('rejected', 'Rejected by MD'),
    ]

    date = models.DateField()
    material_type = models.CharField(max_length=10, choices=MATERIAL_CHOICES)
    product_size = models.CharField(
        max_length=5, choices=[('10kg', '10 KG Sacks')], default='10kg'
    )
    qty_sold = models.PositiveIntegerField(help_text='Number of sacks sold')
    unit_price = models.DecimalField(max_digits=12, decimal_places=2, help_text='Price per sack')
    total_sale_value = models.DecimalField(
        max_digits=14, decimal_places=2,
        help_text='Total sale value (auto: qty × unit_price)'
    )
    amount_received_cash = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    amount_received_transfer = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    buyer_name = models.CharField(max_length=200, blank=True, help_text='Name of the customer')

    # Who recorded this sale
    recorded_by = models.ForeignKey(
        User, on_delete=models.PROTECT, related_name='direct_sales_recorded',
        limit_choices_to={'role': 'manager'},
    )
    notes = models.TextField(blank=True)

    # MD confirmation
    status = models.CharField(max_length=15, choices=DIRECT_SALE_STATUS, default='pending_md')
    confirmed_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='direct_sales_confirmed',
        limit_choices_to={'role': 'md'},
    )
    confirmed_at = models.DateTimeField(null=True, blank=True)
    md_notes = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    is_locked = models.BooleanField(default=False)

    class Meta:
        db_table = 'sales_direct_payment'
        ordering = ['-date', '-created_at']

    def save(self, *args, **kwargs):
        self.total_sale_value = float(self.unit_price) * self.qty_sold
        super().save(*args, **kwargs)

    @property
    def total_received(self):
        return float(self.amount_received_cash) + float(self.amount_received_transfer)

    @property
    def outstanding(self):
        return max(0.0, float(self.total_sale_value) - self.total_received)

    def __str__(self):
        return (f"DirectSale #{self.pk} | {self.material_type.upper()} × {self.qty_sold} "
                f"| ₦{self.total_sale_value:,.0f} | {self.status.upper()} | {self.date}")


class GMRemittance(models.Model):
    """
    Payment recorded by the General Manager (manager) when sending money 
    collected from Direct Sales back to the company (confirmed by MD).
    """
    REMITTANCE_STATUS = [
        ('pending_md', 'Pending MD Confirmation'),
        ('confirmed', 'Confirmed by MD'),
        ('rejected', 'Rejected by MD'),
    ]

    date = models.DateField()
    amount_cash = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    amount_transfer = models.DecimalField(max_digits=14, decimal_places=2, default=0)

    # GM records this remittance
    recorded_by = models.ForeignKey(
        User, on_delete=models.PROTECT, related_name='gm_remittances_recorded',
        limit_choices_to={'role': 'manager'}
    )
    notes = models.TextField(blank=True)

    # MD confirmation
    status = models.CharField(max_length=15, choices=REMITTANCE_STATUS, default='pending_md')
    confirmed_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='gm_remittances_confirmed',
        limit_choices_to={'role': 'md'}
    )
    confirmed_at = models.DateTimeField(null=True, blank=True)
    md_notes = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    is_locked = models.BooleanField(default=False)

    class Meta:
        db_table = 'sales_gm_remittance'
        ordering = ['-date', '-created_at']

    @property
    def total(self):
        return float(self.amount_cash) + float(self.amount_transfer)

    def __str__(self):
        return (f"GM Remittance #{self.pk} | ₦{self.total:,.0f} | "
                f"{self.status.upper()} | {self.date}")
