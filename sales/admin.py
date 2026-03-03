from django.contrib import admin
from .models import SalesPerson, SalesRecord

@admin.register(SalesPerson)
class SalesPersonAdmin(admin.ModelAdmin):
    list_display = ('name', 'channel', 'status', 'created_at')
    list_filter = ('channel', 'status')
    search_fields = ('name',)

@admin.register(SalesRecord)
class SalesRecordAdmin(admin.ModelAdmin):
    list_display = ('id', 'date', 'sales_person', 'material_type', 'qty_sold', 'total_value', 'status')
    list_filter = ('material_type', 'status', 'date', 'channel')
    search_fields = ('buyer_name',)
