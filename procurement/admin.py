from django.contrib import admin
from .models import RawMaterialReceipt, RawMaterialIssuance

@admin.register(RawMaterialReceipt)
class RawMaterialReceiptAdmin(admin.ModelAdmin):
    list_display = ('id', 'date', 'material_type', 'supplier', 'num_bags', 'received_by')
    list_filter = ('material_type', 'date')
    search_fields = ('supplier', 'reference_no')

@admin.register(RawMaterialIssuance)
class RawMaterialIssuanceAdmin(admin.ModelAdmin):
    list_display = ('id', 'date', 'material_type', 'num_bags_issued', 'issued_to', 'issued_by')
    list_filter = ('material_type', 'date')
