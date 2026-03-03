from django.contrib import admin
from .models import MoneyReceipt, ReconciliationFlag

@admin.register(MoneyReceipt)
class MoneyReceiptAdmin(admin.ModelAdmin):
    list_display = ('id', 'date', 'sales_person', 'cash_received', 'transfer_received', 'is_locked')
    list_filter = ('date', 'is_locked')
    search_fields = ('notes',)

@admin.register(ReconciliationFlag)
class ReconciliationFlagAdmin(admin.ModelAdmin):
    list_display = ('id', 'date', 'sales_person', 'difference', 'resolved')
    list_filter = ('resolved', 'date')
