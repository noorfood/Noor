from django.contrib import admin
from .models import User

@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    list_display = ('full_name', 'username', 'role', 'status', 'created_at')
    list_filter = ('role', 'status')
    search_fields = ('full_name', 'username')
