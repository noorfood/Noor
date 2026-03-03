from functools import wraps
from django.shortcuts import redirect
from django.http import HttpResponseForbidden


def login_required(view_func):
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.session.get('user_id'):
            return redirect('login')
        return view_func(request, *args, **kwargs)
    return wrapper


def role_required(*roles):
    def decorator(view_func):
        @wraps(view_func)
        def wrapper(request, *args, **kwargs):
            if not request.session.get('user_id'):
                return redirect('login')
            user_role = request.session.get('user_role')
            actual_role = request.session.get('actual_user_role') # For MD impersonation
            
            # If standard role matches OR if the actual person logged in is the MD, grant access
            if user_role not in roles and actual_role != 'md':
                return HttpResponseForbidden(
                    "<h2>Access Denied</h2><p>You do not have permission to view this page.</p>"
                    "<a href='/dashboard/'>Return to Dashboard</a>"
                )
            return view_func(request, *args, **kwargs)
        return wrapper
    return decorator


def store_type_required(required_type):
    """
    Decorator to restrict access based on User.store_type.
    Reads store_type fresh from the database to avoid stale session values.
    MD and operations managers bypass this restriction entirely.
    """
    def decorator(view_func):
        @wraps(view_func)
        def wrapper(request, *args, **kwargs):
            if not request.session.get('user_id'):
                return redirect('login')

            user_role = request.session.get('user_role')
            actual_role = request.session.get('actual_user_role')

            # MD always has access to both stores
            if actual_role == 'md':
                return view_func(request, *args, **kwargs)

            # General Manager (manager) can perform procurement duties.
            # They are restricted from specific Finished Goods Store officer duties via @role_required.
            if user_role == 'manager':
                return view_func(request, *args, **kwargs)

            # For store officers, always read store_type fresh from DB (avoids stale session)
            if user_role == 'store_officer':
                from accounts.models import User
                try:
                    db_user = User.objects.get(pk=request.session['user_id'])
                    live_store_type = db_user.store_type or ''
                    # Keep session in sync
                    if request.session.get('store_type') != live_store_type:
                        request.session['store_type'] = live_store_type
                except User.DoesNotExist:
                    return redirect('login')

                if live_store_type != required_type:
                    return HttpResponseForbidden(
                        f"<h2>Access Denied</h2><p>This area is restricted to {required_type.title()} Material Store Officers only.</p>"
                        "<a href='/dashboard/'>Return to Dashboard</a>"
                    )

            return view_func(request, *args, **kwargs)
        return wrapper
    return decorator


def get_current_user(request):
    """Retrieve the logged-in User object from session. Handles MD impersonation."""
    actual_user_id = request.session.get('actual_user_id') or request.session.get('user_id')
    if not actual_user_id:
        return None
        
    try:
        from accounts.models import User
        # Check if MD is impersonating someone
        impersonate_id = request.session.get('impersonate_id')
        if impersonate_id:
            actual_user = User.objects.get(pk=actual_user_id)
            TargetUser = User.objects.get(pk=impersonate_id)
            # Attach the real MD user to the request so views/templates know
            request.md_actual_user = actual_user
            return TargetUser
            
        return User.objects.get(pk=actual_user_id, status='active')
    except Exception:
        return None
