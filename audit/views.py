from django.shortcuts import render
from accounts.mixins import get_current_user
from accounts.mixins import role_required
from audit.models import AuditLog


@role_required('md')
def audit_log_view(request):
    user = get_current_user(request)
    logs = AuditLog.objects.all().order_by('-timestamp')

    # Filters
    f_module = request.GET.get('module', '')
    f_user = request.GET.get('user', '')
    f_action = request.GET.get('action', '')
    f_date_from = request.GET.get('date_from', '')
    f_date_to = request.GET.get('date_to', '')

    if f_module:
        logs = logs.filter(module__icontains=f_module)
    if f_user:
        logs = logs.filter(user_name__icontains=f_user)
    if f_action:
        logs = logs.filter(action__icontains=f_action)
    if f_date_from:
        logs = logs.filter(timestamp__date__gte=f_date_from)
    if f_date_to:
        logs = logs.filter(timestamp__date__lte=f_date_to)

    logs = logs[:500]

    return render(request, 'audit/log.html', {
        'logs': logs,
        'current_user': user,
        'f_module': f_module,
        'f_user': f_user,
        'f_action': f_action,
        'f_date_from': f_date_from,
        'f_date_to': f_date_to,
    })
