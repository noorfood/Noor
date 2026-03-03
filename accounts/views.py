from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from accounts.models import User
from accounts.mixins import get_current_user, role_required
from audit.utils import log_action


def login_view(request):
    if request.session.get('user_id'):
        return redirect('dashboard')

    error = None
    if request.method == 'POST':
        username = request.POST.get('username', '').strip()
        password = request.POST.get('password', '')
        try:
            user = User.objects.get(username=username, status__in=['active', 'suspended'])
            if user.status == 'suspended':
                error = 'Your account has been suspended. Please contact management.'
            elif not user.can_login:
                error = 'Sales promoters and drivers do not have system login access. Contact your Sales Manager.'
            elif user.check_password(password):
                request.session['user_id'] = user.pk
                request.session['user_role'] = user.role
                request.session['user_name'] = user.full_name
                request.session['store_type'] = user.store_type or ''
                # Store actual identities for Impersonation engine
                request.session['actual_user_id'] = user.pk
                request.session['actual_user_role'] = user.role
                log_action(request, user, 'accounts', 'LOGIN', f'User {username} logged in')
                return redirect('dashboard')
            else:
                error = 'Invalid username or password.'
        except User.DoesNotExist:
            error = 'Invalid username or password.'

    return render(request, 'accounts/login.html', {'error': error})


def logout_view(request):
    user = get_current_user(request)
    if user:
        log_action(request, user, 'accounts', 'LOGOUT', f'User {user.username} logged out')
    request.session.flush()
    return redirect('login')


def dashboard_redirect(request):
    if not request.session.get('user_id'):
        return redirect('login')

    role = request.session.get('user_role')
    store_type = request.session.get('store_type', '')

    if role == 'store_officer':
        if store_type == 'finished':
            return redirect('/finished-store/list/')
        else:
            return redirect('/procurement/dashboard/')

    role_dashboards = {
        'production_officer': '/production/dashboard/',
        'sales_manager': '/sales/dashboard/',
        'manager': '/reports/dashboard/',
        'md': '/reports/dashboard/',
    }
    return redirect(role_dashboards.get(role, '/'))


# ==========================================
# STAFF MANAGEMENT VIEWS (MD ONLY)
# ==========================================

@role_required('md')
def staff_list(request):
    user = get_current_user(request)
    staff = User.objects.exclude(status='dismissed').order_by('status', 'full_name')
    return render(request, 'accounts/staff_list.html', {'current_user': user, 'staff': staff})


@role_required('md')
def staff_register(request):
    user = get_current_user(request)
    error = None

    if request.method == 'POST':
        full_name = request.POST.get('full_name', '').strip()
        username = request.POST.get('username', '').strip().lower()
        role = request.POST.get('role', '')
        store_type = request.POST.get('store_type', '')
        sales_user_type = request.POST.get('sales_user_type', '')
        password = request.POST.get('password', '')
        confirm_password = request.POST.get('confirm_password', '')

        if not full_name or not username or not role or not password:
            error = "Please fill in all required fields."
        elif password != confirm_password:
            error = "Passwords do not match."
        elif User.objects.filter(username=username).exists():
            error = f"Username '{username}' is already taken."
        else:
            if role != 'sales_user':
                sales_user_type = None
            if role != 'store_officer':
                store_type = None

            new_staff = User(
                username=username,
                full_name=full_name,
                role=role,
                store_type=store_type,
                sales_user_type=sales_user_type,
                created_by=user,
                status='active'
            )
            new_staff.set_password(password)
            new_staff.save()

            log_action(request, user, 'accounts', 'REGISTER_STAFF', f'Registered new staff: {username} ({role})')
            messages.success(request, f"Staff '{full_name}' registered successfully.")
            return redirect('accounts:staff_list')

    return render(request, 'accounts/staff_register.html', {
        'current_user': user,
        'error': error,
        'roles': User.ROLE_CHOICES,
        'sales_types': User.SALES_USER_TYPE_CHOICES
    })


@role_required('md')
def staff_edit(request, pk):
    user = get_current_user(request)
    staff = get_object_or_404(User, pk=pk)
    error = None

    if request.method == 'POST':
        full_name = request.POST.get('full_name', '').strip()
        role = request.POST.get('role', '')
        store_type = request.POST.get('store_type', '')
        sales_user_type = request.POST.get('sales_user_type', '')
        notes = request.POST.get('notes', '').strip()

        if not full_name or not role:
            error = "Full Name and Role are required."
        else:
            old_role = staff.role
            staff.full_name = full_name
            staff.role = role
            staff.sales_user_type = sales_user_type if role == 'sales_user' else None
            staff.notes = notes
            staff.save()

            log_msg = f'Updated staff profile for {staff.username}'
            if old_role != role:
                log_msg += f' (Role changed from {old_role} to {role})'
            log_action(request, user, 'accounts', 'EDIT_STAFF', log_msg)
            
            messages.success(request, f"Profile for '{full_name}' updated.")
            return redirect('accounts:staff_list')

    return render(request, 'accounts/staff_edit.html', {
        'current_user': user,
        'staff': staff,
        'error': error,
        'roles': User.ROLE_CHOICES,
        'sales_types': User.SALES_USER_TYPE_CHOICES
    })

# ==========================================
# IMPERSONATION VIEWS (MD ONLY)
# ==========================================

@role_required('md')
def md_impersonate(request, target_id):
    """MD clicks a button to impersonate a staff member."""
    actual_user = get_current_user(request)
    if not actual_user or getattr(request, 'md_actual_user', actual_user).role != 'md':
        return redirect('dashboard')
        
    target_user = get_object_or_404(User, pk=target_id)
    if target_user.role == 'md':
        messages.error(request, "Cannot impersonate another MD.")
        return redirect('dashboard')
        
    # Set impersonation session variables
    request.session['impersonate_id'] = target_user.pk
    request.session['user_id'] = target_user.pk
    request.session['user_role'] = target_user.role
    request.session['user_name'] = target_user.full_name
    request.session['store_type'] = target_user.store_type or ''
    
    # Properly access md_actual_user attached by get_current_user
    md_user = getattr(request, 'md_actual_user', actual_user)
    if md_user:
        log_action(request, md_user, 'accounts', 'IMPERSONATE_START', f'MD impersonating {target_user.full_name}')
    
    messages.success(request, f"You are now impersonating {target_user.full_name}. You see exactly what they see.")
    return redirect('dashboard')


def md_stop_impersonating(request):
    """Revert session back to the actual MD user."""
    actual_id = request.session.get('actual_user_id')
    if not actual_id:
        return redirect('logout')
        
    try:
        md_user = User.objects.get(pk=actual_id)
        # Restore session
        request.session['user_id'] = md_user.pk
        request.session['user_role'] = md_user.role
        request.session['user_name'] = md_user.full_name
        request.session['store_type'] = md_user.store_type or ''
        
        target_id = request.session.pop('impersonate_id', None)
        if target_id:
            try:
                t = User.objects.get(pk=target_id)
                log_action(request, md_user, 'accounts', 'IMPERSONATE_STOP', f'MD stopped impersonating {t.full_name}')
            except: pass
            
        messages.success(request, "Impersonation ended. You are back to the MD dashboard.")
    except User.DoesNotExist:
        return redirect('logout')
        
    return redirect('dashboard')




@role_required('md')
def staff_reset_password(request, pk):
    user = get_current_user(request)
    staff = get_object_or_404(User, pk=pk)
    error = None

    if request.method == 'POST':
        password = request.POST.get('password', '')
        confirm_password = request.POST.get('confirm_password', '')

        if not password:
            error = "Password cannot be empty."
        elif password != confirm_password:
            error = "Passwords do not match."
        else:
            staff.set_password(password)
            staff.save()
            log_action(request, user, 'accounts', 'RESET_PASSWORD', f'Reset password for user: {staff.username}')
            messages.success(request, f"Password reset for '{staff.full_name}'.")
            return redirect('accounts:staff_list')

    return render(request, 'accounts/staff_reset_password.html', {
        'current_user': user, 'staff': staff, 'error': error
    })


@role_required('md')
def staff_action(request, pk):
    user = get_current_user(request)
    staff = get_object_or_404(User, pk=pk)

    if request.method == 'POST':
        action = request.POST.get('action')
        notes = request.POST.get('notes', '').strip()

        if action in ['suspend', 'dismiss', 'reactivate']:
            old_status = staff.status
            if action == 'suspend':
                staff.status = 'suspended'
            elif action == 'dismiss':
                staff.status = 'dismissed'
            elif action == 'reactivate':
                staff.status = 'active'
            
            if notes:
                staff.notes = f"[{action.upper()}]: {notes}\n" + staff.notes

            if staff.pk == user.pk:
                messages.error(request, "You cannot suspend or dismiss yourself.")
                return redirect('accounts:staff_list')

            staff.save()
            log_action(request, user, 'accounts', f'STAFF_{action.upper()}', f'{action.title()} user: {staff.username}')
            messages.success(request, f"Staff '{staff.full_name}' is now {staff.get_status_display().lower()}.")
    
    return redirect('accounts:staff_list')
