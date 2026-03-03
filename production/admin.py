from django.contrib import admin
from .models import ProductionThreshold, MillingBatch, PackagingBatch, BrandSale

@admin.register(ProductionThreshold)
class ProductionThresholdAdmin(admin.ModelAdmin):
    list_display = ('material_type', 'normal_max_loss_pct', 'warning_max_loss_pct', 'effective_from')

@admin.register(MillingBatch)
class MillingBatchAdmin(admin.ModelAdmin):
    list_display = ('id', 'date', 'material_type', 'bulk_powder_kg', 'loss_pct', 'flag_level', 'status')
    list_filter = ('material_type', 'flag_level', 'status', 'date')

@admin.register(PackagingBatch)
class PackagingBatchAdmin(admin.ModelAdmin):
    list_display = ('id', 'date', 'material_type', 'qty_10kg', 'loss_pct', 'flag_level')
    list_filter = ('material_type', 'flag_level', 'date')

@admin.register(BrandSale)
class BrandSaleAdmin(admin.ModelAdmin):
    list_display = ('id', 'date', 'material_type', 'qty_sacks', 'total_amount', 'buyer_name')
    list_filter = ('material_type', 'date')
