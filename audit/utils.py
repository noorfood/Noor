from audit.models import AuditLog


def log_action(request, user, module, action, description='',
               object_type='', object_id='', old_data='', new_data=''):
    """Utility function to create an audit log entry."""
    # Forwarded headers are client-controlled unless a trusted proxy is configured.
    ip = request.META.get('REMOTE_ADDR') if request else None

    AuditLog.objects.create(
        user_id=user.pk if user else None,
        user_name=user.full_name if user else 'System',
        user_role=user.role if user else '',
        module=module,
        action=action,
        object_type=object_type,
        object_id=str(object_id),
        description=description,
        old_data=old_data,
        new_data=new_data,
        ip_address=ip,
    )
