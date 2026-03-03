from django.contrib import admin
from .models import AuditLog

@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ('timestamp', 'user_name', 'user_role', 'module', 'action', 'object_type')
    list_filter = ('module', 'action', 'timestamp')
    search_fields = ('user_name', 'description')
    readonly_fields = ('timestamp',)
