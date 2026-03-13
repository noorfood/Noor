from procurement.models import RawMaterialReceipt

def pending_actions(request):
    """
    Context processor to provide global counts of pending actions for MD/Managers.
    Works with the system's session-based role system.
    """
    context = {
        'global_pending_raw_costs': 0,
    }
    
    user_role = request.session.get('user_role')
    
    if user_role == 'md':
        context['global_pending_raw_costs'] = RawMaterialReceipt.objects.filter(cost_status='pending').count()
        
    return context
