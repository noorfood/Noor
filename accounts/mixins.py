from functools import wraps
from django.shortcuts import redirect, render
from accounts.models import User


def forbidden_response(request, message='Access denied.'):
    """A friendly 403 page inside the normal layout, so a denied user can
    still use the menu instead of hitting a bare dead-end page."""
    return render(request, 'rebuild/access_denied.html', {
        'current_user': get_current_user(request),
        'message': message,
    }, status=403)


def get_current_user(request):
    """Return only the active, actual account; impersonation cannot authorize work."""
    actual_id=request.session.get('actual_user_id') or request.session.get('user_id')
    if not actual_id or request.session.get('impersonate_id'):
        return None
    if request.session.get('user_id') != actual_id:
        return None
    return User.objects.filter(pk=actual_id,status='active').first()


def login_required(view_func):
    @wraps(view_func)
    def wrapper(request,*args,**kwargs):
        if not get_current_user(request):return redirect('login')
        return view_func(request,*args,**kwargs)
    return wrapper


def role_required(*roles, md_read=None):
    """Gate a view to `roles`. When `md_read` names who records the work
    (e.g. 'raw store officer'), the MD may open the page (GET) to see the
    data and the balances, but may not submit (POST) — the record must
    show the staff member who actually did the work, so the MD can
    trust the "who has what" figures. A denied MD POST gets the
    friendly page with that explanation."""
    def decorator(view_func):
        @wraps(view_func)
        def wrapper(request,*args,**kwargs):
            if not request.session.get('user_id'):return redirect('login')
            user=get_current_user(request)
            if not user:return forbidden_response(request)
            if user.role in roles:return view_func(request,*args,**kwargs)
            if md_read and user.role=='md':
                if request.method=='POST':
                    return forbidden_response(
                        request,
                        f'This is recorded by the {md_read}. '
                        'You are viewing as MD — the record must show '
                        'the person who did the work.')
                return view_func(request,*args,**kwargs)
            return forbidden_response(request)
        return wrapper
    return decorator


def store_type_required(required_type):
    def decorator(view_func):
        @wraps(view_func)
        def wrapper(request,*args,**kwargs):
            if not request.session.get('user_id'):return redirect('login')
            user=get_current_user(request)
            if not user:return forbidden_response(request)
            if user.role=='store_officer' and user.store_type!=required_type:return forbidden_response(request)
            return view_func(request,*args,**kwargs)
        return wrapper
    return decorator
