from django.db import models
from accounts.models import User
from sales.models import SalesRecord


class MoneyReceipt(models.Model):
    """Cash/transfer collected by sales manager from a sales person."""
    date = models.DateField()
    sales_manager = models.ForeignKey(User, on_delete=models.PROTECT, related_name='money_receipts',
                                      limit_choices_to={'role': 'sales_manager'})
    sales_person = models.ForeignKey('sales.SalesPerson', on_delete=models.PROTECT, related_name='money_paid', null=True)
    cash_received = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    transfer_received = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    linked_sales_records = models.ManyToManyField(SalesRecord, blank=True, related_name='money_receipts')
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    is_locked = models.BooleanField(default=True)

    class Meta:
        db_table = 'reconciliation_money_receipt'
        ordering = ['-date', '-created_at']

    @property
    def total_received(self):
        return float(self.cash_received) + float(self.transfer_received)

    def __str__(self):
        sp_name = self.sales_person.name if self.sales_person else "Unknown"
        return f"MoneyReceipt #{self.pk} | From {sp_name} | ₦{self.total_received} | {self.date}"


class ReconciliationFlag(models.Model):
    """Auto-created when money received ≠ sales total for a person/period."""
    date = models.DateField()
    sales_person = models.ForeignKey('sales.SalesPerson', on_delete=models.PROTECT, related_name='recon_flags', null=True)
    period_start = models.DateField()
    period_end = models.DateField()
    expected_amount = models.DecimalField(max_digits=14, decimal_places=2)
    actual_amount = models.DecimalField(max_digits=14, decimal_places=2)
    difference = models.DecimalField(max_digits=14, decimal_places=2)
    flagged_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name='created_flags',
                                   limit_choices_to={'role': 'sales_manager'})
    notes = models.TextField(blank=True)
    resolved = models.BooleanField(default=False)
    resolved_notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'reconciliation_flag'
        ordering = ['-date', '-created_at']

    def __str__(self):
        sp_name = self.sales_person.name if self.sales_person else "Unknown"
        return f"ReconFlag #{self.pk} | {sp_name} | Diff ₦{self.difference} | {self.date}"
