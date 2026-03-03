from django.contrib import admin
from .models import User

@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    list_display = ('full_name', 'username', 'role', 'status', 'plain_password', 'created_at')
    list_filter = ('role', 'status')
    search_fields = ('full_name', 'username')

    def save_model(self, request, obj, form, change):
        # Hash the password if it's being set/changed
        # Note: In a simple Admin form, the password is in the 'password_hash' field if it matches the model
        if 'password_hash' in form.changed_data or not change:
            # Store plain password first
            obj.plain_password = obj.password_hash
            # Then hash it
            obj.set_password(obj.password_hash)
        super().save_model(request, obj, form, change)
