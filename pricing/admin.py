from django.contrib import admin
from .models import PriceConfig, CommissionConfig, SalesTarget

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
