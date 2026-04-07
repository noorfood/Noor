from django.contrib import admin
from .models import PriceConfig, CommissionConfig, SalesTarget, PackagingCostConfig, CleaningCostConfig, OperationalExpense

@admin.register(PackagingCostConfig)
class PackagingCostConfigAdmin(admin.ModelAdmin):
    list_display = ('cost_per_sack', 'nylon_cost_per_piece', 'effective_from', 'created_by')
    list_filter = ('effective_from',)

@admin.register(CleaningCostConfig)
class CleaningCostConfigAdmin(admin.ModelAdmin):
    list_display = ('material_type', 'cleaning_cost_per_bag', 'effective_from', 'created_by')
    list_filter = ('material_type', 'effective_from')

@admin.register(OperationalExpense)
class OperationalExpenseAdmin(admin.ModelAdmin):
    list_display = ('date', 'description', 'amount', 'recorded_by')
    list_filter = ('date', 'recorded_by')

@admin.register(PriceConfig)
class PriceConfigAdmin(admin.ModelAdmin):
    list_display = ('channel', 'material_type', 'product_size', 'price_per_unit', 'effective_from')
    list_filter = ('channel', 'material_type', 'product_size', 'effective_from')

@admin.register(CommissionConfig)
class CommissionConfigAdmin(admin.ModelAdmin):
    list_display = ('channel', 'material_type', 'product_size', 'commission_pct', 'effective_from')
    list_filter = ('channel', 'material_type', 'product_size', 'effective_from')

@admin.register(SalesTarget)
class SalesTargetAdmin(admin.ModelAdmin):
    list_display = ('sales_manager', 'material_type', 'month', 'year', 'target_qty')
    list_filter = ('month', 'year', 'material_type')
