from django.db import models


class AuditLog(models.Model):
    timestamp = models.DateTimeField(auto_now_add=True)
    user_id = models.IntegerField(null=True, blank=True)
    user_name = models.CharField(max_length=200, blank=True)
    user_role = models.CharField(max_length=50, blank=True)
    module = models.CharField(max_length=100)
    action = models.CharField(max_length=100)
    object_type = models.CharField(max_length=100, blank=True)
    object_id = models.CharField(max_length=50, blank=True)
    description = models.TextField(blank=True)
    old_data = models.TextField(blank=True)
    new_data = models.TextField(blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)

    class Meta:
        db_table = 'audit_log'
        ordering = ['-timestamp']

    def __str__(self):
        return f"[{self.timestamp}] {self.user_name} | {self.module}.{self.action}"
