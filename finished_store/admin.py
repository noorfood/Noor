from django.contrib import admin
from .models import FinishedGoodsReceipt, FinishedGoodsIssuance, FinishedGoodsReturn

@admin.register(FinishedGoodsReceipt)
class FinishedGoodsReceiptAdmin(admin.ModelAdmin):
    list_display = ('id', 'date', 'material_type', 'qty_received', 'status', 'submitted_by')
    list_filter = ('material_type', 'status', 'date')

@admin.register(FinishedGoodsIssuance)
class FinishedGoodsIssuanceAdmin(admin.ModelAdmin):
    list_display = ('id', 'date', 'material_type', 'qty_issued', 'channel', 'status')
    list_filter = ('material_type', 'channel', 'status', 'date')

@admin.register(FinishedGoodsReturn)
class FinishedGoodsReturnAdmin(admin.ModelAdmin):
    list_display = ('id', 'date', 'material_type', 'qty_returned', 'returned_by')
    list_filter = ('material_type', 'date')
