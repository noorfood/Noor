from django.contrib import admin
from .models import CleanRawReceipt

@admin.register(CleanRawReceipt)
class CleanRawReceiptAdmin(admin.ModelAdmin):
    list_display = ('id', 'date', 'material_type', 'num_bags', 'received_by')
    list_filter = ('material_type', 'date')
