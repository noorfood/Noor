from django.db import models
from accounts.models import User
from procurement.models import MATERIAL_CHOICES

PRODUCT_SIZE_CHOICES = [
    ('10kg', '10 KG'),
]

CHANNEL_CHOICES = [
    ('company', 'Company Direct'),
    ('sales_manager', 'Sales Manager'),
    # Legacy: promoter / driver kept for historical records only
    ('promoter', 'Sales Promoter (Legacy)'),
    ('driver', 'Vehicle Driver (Legacy)'),
]

# Issuances only (sales.SalesRecord shares CHANNEL_CHOICES above, so the
# warehouse value lives here and not in the sales channel list).
ISSUANCE_CHANNEL_CHOICES = CHANNEL_CHOICES + [
    ('warehouse', 'Warehouse Delivery'),
]

ACKNOWLEDGEMENT_CHOICES = [
    ('pending', 'Pending'),
    ('accepted', 'Accepted'),
    ('rejected', 'Rejected'),
]


class FinishedGoodsReceipt(models.Model):
    """Finished goods received into the FG store from production (ledger-based).
    Created automatically when a PackagingBatch is saved; stays Pending until the
    FG Store Officer accepts or rejects it with an optional note."""
    date = models.DateField()
    # Ledger reference: human-readable link back to the packaging batch ID (no FK)
    packaging_ref = models.CharField(max_length=50, blank=True,
                                     help_text='Display ref e.g. "Packaging Batch #7"')
    packaging_batch = models.ForeignKey('production.PackagingBatch', on_delete=models.SET_NULL, null=True, blank=True, related_name='fg_receipts')
    product_size = models.CharField(max_length=5, choices=PRODUCT_SIZE_CHOICES)
    material_type = models.CharField(max_length=10, choices=MATERIAL_CHOICES, default='maize')
    qty_received = models.PositiveIntegerField()
    # Who submitted the receipt (Production Officer)
    submitted_by = models.ForeignKey(User, on_delete=models.PROTECT,
                                     related_name='fg_receipts_submitted',
                                     null=True, blank=True)
    # Who acknowledged the receipt (FG Store Officer)
    received_by = models.ForeignKey(User, on_delete=models.PROTECT,
                                    related_name='fg_receipts_acknowledged',
                                    null=True, blank=True)
    # Handshake status
    status = models.CharField(max_length=15, choices=ACKNOWLEDGEMENT_CHOICES, default='pending')
    rejection_note = models.TextField(blank=True, help_text='Reason for rejection')
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    is_locked = models.BooleanField(default=True)

    class Meta:
        db_table = 'finished_store_receipt'
        ordering = ['-date', '-created_at']

    def __str__(self):
        return f"FG Receipt #{self.pk} | {self.material_type}/{self.product_size} × {self.qty_received} | {self.status.upper()} | {self.date}"


class FinishedGoodsIssuance(models.Model):
    """Finished goods issued from store to sales channel."""
    date = models.DateField()
    product_size = models.CharField(max_length=5, choices=PRODUCT_SIZE_CHOICES)
    material_type = models.CharField(max_length=10, choices=MATERIAL_CHOICES, default='maize')
    qty_issued = models.PositiveIntegerField()
    channel = models.CharField(max_length=15, choices=ISSUANCE_CHANNEL_CHOICES)
    issued_to = models.ForeignKey(User, on_delete=models.PROTECT, related_name='fg_issued_to',
                                  null=True, blank=True)
    issued_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name='fg_issued_by')
    # Link to the SalesRecord that authorised this issuance (legacy / company sales)
    sales_record = models.ForeignKey(
        'sales.SalesRecord', on_delete=models.PROTECT,
        related_name='issuances', null=True, blank=True
    )
    # Link to the SalesManagerCollection (new real-world flow)
    sm_collection = models.ForeignKey(
        'sales.SalesManagerCollection', on_delete=models.PROTECT,
        related_name='issuances', null=True, blank=True,
        help_text='The SM collection this issuance was recorded against'
    )
    # Company channel: who should approve this issuance
    approver = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='fg_issuances_to_approve',
        help_text='GM or MD designated to confirm this company issuance'
    )
    # Company channel: buyer/recipient name
    buyer_name = models.CharField(
        max_length=200, blank=True,
        help_text='Name of the customer or entity receiving the goods (company sales)'
    )
    status = models.CharField(max_length=15, choices=ACKNOWLEDGEMENT_CHOICES, default='pending')
    rejection_note = models.TextField(blank=True, help_text='Reason for rejection')
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    is_locked = models.BooleanField(default=True)

    class Meta:
        db_table = 'finished_store_issuance'
        ordering = ['-date', '-created_at']

    def __str__(self):
        return f"FG Issuance #{self.pk} | {self.material_type}/{self.product_size} × {self.qty_issued} | {self.date}"


class FinishedGoodsReturn(models.Model):
    """Finished goods returned from sales back to store."""
    date = models.DateField()
    product_size = models.CharField(max_length=5, choices=PRODUCT_SIZE_CHOICES)
    material_type = models.CharField(max_length=10, choices=MATERIAL_CHOICES, default='maize')
    qty_returned = models.PositiveIntegerField()
    returned_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name='fg_returned_by',
                                    null=True, blank=True)
    received_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name='fg_return_received',
                                    null=True, blank=True)
    status = models.CharField(max_length=15, choices=ACKNOWLEDGEMENT_CHOICES, default='pending')
    rejection_note = models.TextField(blank=True, help_text='Reason for rejection')
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    is_locked = models.BooleanField(default=True)

    class Meta:
        db_table = 'finished_store_return'
        ordering = ['-date', '-created_at']

    def __str__(self):
        return f"FG Return #{self.pk} | {self.material_type}/{self.product_size} × {self.qty_returned}"


class Warehouse(models.Model):
    """A warehouse in another state that receives finished goods.

    The list is manageable: staff can add more warehouses later, and
    inactive ones stop appearing as choices without deleting history.
    """
    name = models.CharField(max_length=200, unique=True, help_text='e.g. Kano Warehouse')
    state = models.CharField(max_length=100, blank=True, help_text='e.g. Kano State')
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='warehouses_created',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'finished_store_warehouse'
        ordering = ['name']

    def __str__(self):
        return self.name


class WarehouseDelivery(models.Model):
    """One delivery of finished goods to a warehouse in another state.

    Recorded by the Finished Goods Officer. The goods leave the store
    through a linked FinishedGoodsIssuance (channel 'warehouse'), so
    finished-store stock is deducted exactly like any other issuance —
    only once the receiver confirms. The receiver-confirmation step
    mirrors the existing issuance handshake (see acknowledge_issuance):
    the officer records the receiver's confirmation with their name.
    """
    DELIVERY_STATUS = [
        ('pending', 'Sent — waiting for receiver'),
        ('accepted', 'Received'),
        ('rejected', 'Difference reported'),
    ]

    warehouse = models.ForeignKey(
        Warehouse, on_delete=models.PROTECT, related_name='deliveries',
    )
    delivery_name = models.CharField(
        max_length=200, help_text='e.g. March supply run',
    )
    supply_to = models.CharField(
        max_length=200, help_text='Name of the person receiving the goods',
    )
    supply_to_phone = models.CharField(max_length=20, help_text='Receiver phone number')
    quantity = models.PositiveIntegerField(help_text='Number of 10kg sacks')
    material_type = models.CharField(max_length=10, choices=MATERIAL_CHOICES, default='maize')
    product_size = models.CharField(max_length=5, choices=PRODUCT_SIZE_CHOICES, default='10kg')
    date = models.DateField(help_text='Date goods were sent (automatic)')
    recorded_by = models.ForeignKey(
        User, on_delete=models.PROTECT, related_name='warehouse_deliveries_recorded',
    )
    issuance = models.ForeignKey(
        'FinishedGoodsIssuance', on_delete=models.PROTECT, null=True, blank=True,
        related_name='warehouse_deliveries',
        help_text='Stock record for this delivery',
    )
    status = models.CharField(max_length=15, choices=DELIVERY_STATUS, default='pending')
    confirmed_by_name = models.CharField(max_length=200, blank=True)
    confirmed_at = models.DateTimeField(null=True, blank=True)
    confirm_note = models.TextField(blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'finished_store_warehouse_delivery'
        ordering = ['-date', '-created_at']

    def __str__(self):
        return f"{self.delivery_name} → {self.warehouse.name} | {self.material_type} × {self.quantity} | {self.status}"
