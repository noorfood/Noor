from audit.models import AuditLog


def log_action(request, user, module, action, description='',
               object_type='', object_id='', old_data='', new_data=''):
    """Utility function to create an audit log entry."""
    ip = None
    if request:
        x_forwarded = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded:
            ip = x_forwarded.split(',')[0].strip()
        else:
            ip = request.META.get('REMOTE_ADDR')

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
