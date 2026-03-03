from django.contrib import admin
from .models import CleanRawIssuance, CleanRawReturn

@admin.register(CleanRawIssuance)
class CleanRawIssuanceAdmin(admin.ModelAdmin):
    list_display = ('id', 'date', 'material_type', 'num_bags', 'issued_to', 'status')
    list_filter = ('material_type', 'status', 'date')

@admin.register(CleanRawReturn)
class CleanRawReturnAdmin(admin.ModelAdmin):
    list_display = ('id', 'date', 'material_type', 'num_bags', 'returned_by', 'status')
    list_filter = ('material_type', 'status', 'date')
