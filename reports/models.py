from django.db import models
from accounts.models import User

class MonthlySnapshot(models.Model):
    """
    A comprehensive end-of-month snapshot of the company's entire operational state.
    Captures balances across Store, Production, Sales, and GM.
    """
    year = models.PositiveIntegerField()
    month = models.PositiveIntegerField()
    
    # --- STORE (Raw Materials) ---
    clean_maize_bags = models.IntegerField(default=0)
    clean_wheat_bags = models.IntegerField(default=0)
    dirty_maize_bags = models.IntegerField(default=0)
    dirty_wheat_bags = models.IntegerField(default=0)

    # --- PRODUCTION ---
    prod_maize_hand = models.IntegerField(default=0)
    prod_wheat_hand = models.IntegerField(default=0)
    prod_maize_transit = models.IntegerField(default=0)
    prod_wheat_transit = models.IntegerField(default=0)
    # Monthly production activity
    prod_maize_milled_bags = models.IntegerField(default=0)
    prod_wheat_milled_bags = models.IntegerField(default=0)
    prod_maize_packaged_sacks = models.IntegerField(default=0)
    prod_wheat_packaged_sacks = models.IntegerField(default=0)

    # --- FINISHED GOODS STORE ---
    fg_maize_10kg = models.IntegerField(default=0)
    fg_wheat_10kg = models.IntegerField(default=0)

    # --- SALES MANAGERS ---
    sm_maize_holding = models.IntegerField(default=0)
    sm_wheat_holding = models.IntegerField(default=0)
    sm_money_outstanding = models.DecimalField(max_digits=14, decimal_places=2, default=0)

    # --- GENERAL MANAGER (GM) ---
    gm_maize_hand = models.IntegerField(default=0)
    gm_wheat_hand = models.IntegerField(default=0)
    gm_retail_pieces_maize = models.IntegerField(default=0)
    gm_retail_pieces_wheat = models.IntegerField(default=0)
    gm_direct_sale_outstanding = models.DecimalField(max_digits=14, decimal_places=2, default=0)

    recorded_by = models.ForeignKey(User, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'reports_monthly_snapshot'
        ordering = ['-year', '-month']
        unique_together = ['year', 'month']

    def __str__(self):
        import calendar
        return f"Company Snapshot: {calendar.month_name[self.month]} {self.year}"
