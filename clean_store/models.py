from django.db import models
from accounts.models import User
from procurement.models import MATERIAL_CHOICES
from cleaning.models import CleanRawReceipt

ACKNOWLEDGEMENT_CHOICES = [
    ('pending', 'Pending'),
    ('accepted', 'Accepted'),
    ('rejected', 'Rejected'),
]


class CleanRawIssuance(models.Model):
    """Clean 100kg bags issued from store to production."""
    date = models.DateField()
    material_type = models.CharField(max_length=10, choices=MATERIAL_CHOICES)
    num_bags = models.PositiveIntegerField()
    issued_to = models.ForeignKey(User, on_delete=models.PROTECT, related_name='clean_raw_issued_to',
                                  limit_choices_to={'role': 'production_officer'})
    issued_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name='clean_raw_issued_by')
    status = models.CharField(max_length=15, choices=ACKNOWLEDGEMENT_CHOICES, default='pending')
    rejection_note = models.TextField(blank=True, help_text='Reason for rejection')
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    is_locked = models.BooleanField(default=True)

    class Meta:
        db_table = 'clean_store_issuance'
        ordering = ['-date', '-created_at']

    def __str__(self):
        return f"Clean Issuance #{self.pk} | {self.num_bags} bags → {self.issued_to.full_name} | {self.date}"


class CleanRawReturn(models.Model):
    """Clean bags returned from production back to store."""
    date = models.DateField()
    material_type = models.CharField(max_length=10, choices=MATERIAL_CHOICES)
    num_bags = models.PositiveIntegerField()
    returned_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name='clean_raw_returned_by',
                                    limit_choices_to={'role': 'production_officer'})
    received_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name='clean_raw_return_received',
                                    null=True, blank=True)
    status = models.CharField(max_length=15, choices=ACKNOWLEDGEMENT_CHOICES, default='pending')
    rejection_note = models.TextField(blank=True, help_text='Reason for rejection')
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    is_locked = models.BooleanField(default=True)

    class Meta:
        db_table = 'clean_store_return'
        ordering = ['-date', '-created_at']

    def __str__(self):
        return f"Clean Return #{self.pk} | {self.num_bags} bags from {self.returned_by.full_name} | {self.date}"
