from django.contrib import admin
from .models import CleaningBatch, CleanRawReceipt

@admin.register(CleaningBatch)
class CleaningBatchAdmin(admin.ModelAdmin):
    list_display = ('id', 'date', 'material_type', 'clean_bags_produced', 'loss_kg', 'status')
    list_filter = ('material_type', 'status', 'date')

@admin.register(CleanRawReceipt)
class CleanRawReceiptAdmin(admin.ModelAdmin):
    list_display = ('id', 'date', 'material_type', 'num_bags', 'received_by')
    list_filter = ('material_type', 'date')
