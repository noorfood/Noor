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
    channel = models.CharField(max_length=15, choices=CHANNEL_CHOICES)
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
