from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.utils import timezone
from datetime import timedelta
from .models import SystemSettings, Branch, AuditLog
from .decorators import require_general_gateway


def get_client_ip(request):
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        return x_forwarded_for.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR', '127.0.0.1')


def general_login_view(request):
    """Step 1: General Business Gateway Password."""
    settings = SystemSettings.get_settings()
    
    # If already unlocked, proceed to Hub
    if request.session.get('general_unlocked', False):
        return redirect('inventory:portal_hub')
        
    error_msg = None
    if request.method == 'POST':
        entered_password = request.POST.get('general_password', '').strip()
        if entered_password == settings.general_password:
            request.session['general_unlocked'] = True
            request.session['gateway_unlocked_at'] = timezone.now().isoformat()
            
            AuditLog.objects.create(
                user_role='GATEWAY',
                actor_name='Terminal Operator',
                action_type='GATEWAY_UNLOCKED',
                details='General business password entered successfully',
                ip_address=get_client_ip(request)
            )
            messages.success(request, f"Welcome to {settings.business_name}. Access Granted.")
            return redirect('inventory:portal_hub')
        else:
            error_msg = "Invalid business gateway password. Please check with Matteo Williams management."
            AuditLog.objects.create(
                user_role='GATEWAY',
                actor_name='Unknown',
                action_type='GATEWAY_FAILED',
                details='Invalid general password entered',
                ip_address=get_client_ip(request)
            )

    return render(request, 'inventory/auth/general_login.html', {
        'settings': settings,
        'error_msg': error_msg,
    })


@require_general_gateway
def portal_hub_view(request):
    """Step 2: Choose Owner Portal or Branch Terminal."""
    settings = SystemSettings.get_settings()
    branches = Branch.objects.all().order_by('id')
    
    # Refresh lock states on active branches
    for b in branches:
        b.is_currently_locked()
        
    return render(request, 'inventory/auth/portal_hub.html', {
        'settings': settings,
        'branches': branches,
        'now': timezone.now(),
    })


@require_general_gateway
def owner_login_view(request):
    """Owner login with master PIN or Owner credentials."""
    settings = SystemSettings.get_settings()
    error_msg = None
    
    if request.method == 'POST':
        pin_or_pass = request.POST.get('owner_secret', '').strip()
        username = request.POST.get('username', '').strip()
        
        # Valid if Master PIN matches OR Owner Password matches
        is_pin_valid = (pin_or_pass == settings.owner_pin)
        is_pass_valid = (pin_or_pass == settings.owner_password)
        
        if is_pin_valid or is_pass_valid:
            request.session['user_role'] = 'OWNER'
            request.session['actor_name'] = 'Owner (Matteo Williams)'
            request.session['branch_id'] = None  # Owner has cross-branch access
            
            AuditLog.objects.create(
                user_role='OWNER',
                actor_name='Owner',
                action_type='OWNER_LOGIN_SUCCESS',
                details='Owner authenticated to Central Command Dashboard',
                ip_address=get_client_ip(request)
            )
            messages.success(request, "Welcome, Owner! Central Multi-Branch Command Activated.")
            return redirect('inventory:owner_dashboard')
        else:
            error_msg = "Invalid Owner Credentials. Access denied."
            AuditLog.objects.create(
                user_role='OWNER',
                actor_name='Unknown',
                action_type='OWNER_LOGIN_FAILED',
                details='Failed owner login attempt',
                ip_address=get_client_ip(request)
            )

    return render(request, 'inventory/auth/owner_login.html', {
        'settings': settings,
        'error_msg': error_msg,
    })


@require_general_gateway
def branch_login_view(request, branch_id):
    """Branch authentication with cashier/manager PIN & 3-attempt rate limiting."""
    branch = get_object_or_404(Branch, id=branch_id)
    error_msg = None
    lockout_warning = False
    
    # Check if currently locked
    if branch.is_currently_locked():
        remaining_seconds = int((branch.locked_until - timezone.now()).total_seconds())
        remaining_hours = max(1, remaining_seconds // 3600)
        return render(request, 'inventory/auth/branch_locked.html', {
            'branch': branch,
            'remaining_hours': remaining_hours,
            'locked_until': branch.locked_until,
        })

    if request.method == 'POST':
        entered_pin = request.POST.get('pin', '').strip()
        operator_name = request.POST.get('operator_name', '').strip() or 'Staff'

        if entered_pin == branch.cashier_pin:
            # Successful Cashier Login
            branch.failed_pin_attempts = 0
            branch.save(update_fields=['failed_pin_attempts'])
            
            request.session['user_role'] = 'CASHIER'
            request.session['branch_id'] = branch.id
            request.session['actor_name'] = f"{operator_name} (Cashier)"
            
            AuditLog.objects.create(
                branch=branch,
                user_role='CASHIER',
                actor_name=f"{operator_name} (Cashier)",
                action_type='CASHIER_LOGIN_SUCCESS',
                details=f"Cashier logged in at {branch.name}",
                ip_address=get_client_ip(request)
            )
            messages.success(request, f"Welcome {operator_name}! POS Terminal ready at {branch.name}.")
            return redirect('inventory:pos_terminal')

        elif entered_pin == branch.manager_pin:
            # Successful Manager Login
            branch.failed_pin_attempts = 0
            branch.save(update_fields=['failed_pin_attempts'])
            
            request.session['user_role'] = 'MANAGER'
            request.session['branch_id'] = branch.id
            request.session['actor_name'] = f"{operator_name} (Manager)"
            
            AuditLog.objects.create(
                branch=branch,
                user_role='MANAGER',
                actor_name=f"{operator_name} (Manager)",
                action_type='MANAGER_LOGIN_SUCCESS',
                details=f"Branch Manager logged in at {branch.name}",
                ip_address=get_client_ip(request)
            )
            messages.success(request, f"Manager session verified for {branch.name}.")
            return redirect('inventory:branch_dashboard')

        else:
            # Wrong PIN -> Increment attempts & check rate limiting
            just_locked = branch.record_failed_attempt()
            
            if just_locked:
                AuditLog.objects.create(
                    branch=branch,
                    user_role='GATEWAY',
                    actor_name='Unknown',
                    action_type='TERMINAL_SECURITY_LOCKOUT',
                    details=f"SECURITY ALERT: {branch.name} locked for 24 hours after 3 failed PIN attempts",
                    ip_address=get_client_ip(request)
                )
                return render(request, 'inventory/auth/branch_locked.html', {
                    'branch': branch,
                    'remaining_hours': 24,
                    'locked_until': branch.locked_until,
                    'just_locked': True,
                })
            else:
                attempts_left = 3 - branch.failed_pin_attempts
                error_msg = f"Incorrect PIN! Failed attempt {branch.failed_pin_attempts} of 3. ({attempts_left} attempt{'s' if attempts_left > 1 else ''} left before 24-hour lockout)."
                AuditLog.objects.create(
                    branch=branch,
                    user_role='GATEWAY',
                    actor_name='Unknown',
                    action_type='PIN_FAILED_ATTEMPT',
                    details=f"Incorrect PIN attempt #{branch.failed_pin_attempts} on {branch.name}",
                    ip_address=get_client_ip(request)
                )

    return render(request, 'inventory/auth/branch_login.html', {
        'branch': branch,
        'error_msg': error_msg,
        'attempts_count': branch.failed_pin_attempts,
    })


@require_general_gateway
def unlock_branch_view(request, branch_id):
    """Allows Owner or Branch Manager to instantly unlock a 24h locked branch terminal."""
    branch = get_object_or_404(Branch, id=branch_id)
    settings = SystemSettings.get_settings()
    error_msg = None
    
    # If the user is currently logged in as Owner, they can unlock with 1-click
    if request.session.get('user_role') == 'OWNER':
        branch.unlock(unlocked_by="Owner (Session)")
        AuditLog.objects.create(
            branch=branch,
            user_role='OWNER',
            actor_name='Owner',
            action_type='TERMINAL_UNLOCKED',
            details=f"Owner unlocked {branch.name} terminal",
            ip_address=get_client_ip(request)
        )
        messages.success(request, f"{branch.name} terminal has been unlocked successfully!")
        return redirect('inventory:owner_dashboard')

    if request.method == 'POST':
        override_key = request.POST.get('override_key', '').strip()
        operator_title = request.POST.get('operator_title', 'Manager')
        
        # Can be unlocked by Owner Master PIN, Owner Password, or this branch's Manager PIN
        if override_key in [settings.owner_pin, settings.owner_password, branch.manager_pin]:
            unlocked_by = f"Owner Master Key" if override_key in [settings.owner_pin, settings.owner_password] else f"Manager ({branch.name})"
            branch.unlock(unlocked_by=unlocked_by)
            
            AuditLog.objects.create(
                branch=branch,
                user_role='MANAGER' if 'Manager' in unlocked_by else 'OWNER',
                actor_name=unlocked_by,
                action_type='TERMINAL_UNLOCKED',
                details=f"{branch.name} terminal unlocked via authorized override",
                ip_address=get_client_ip(request)
            )
            messages.success(request, f"{branch.name} terminal successfully unlocked! You can now log in.")
            return redirect('inventory:branch_login', branch_id=branch.id)
        else:
            error_msg = "Invalid authorization code! Only the Owner or Branch Manager can unlock."
            AuditLog.objects.create(
                branch=branch,
                user_role='GATEWAY',
                actor_name='Unauthorized User',
                action_type='UNLOCK_FAILED_ATTEMPT',
                details=f"Failed attempt to unlock {branch.name} terminal",
                ip_address=get_client_ip(request)
            )

    return render(request, 'inventory/auth/unlock_terminal.html', {
        'branch': branch,
        'error_msg': error_msg,
    })


def logout_view(request):
    """End current role session, but optionally keep gateway unlocked or full reset."""
    full_lock = request.GET.get('full_lock', False)
    role = request.session.get('user_role', 'User')
    actor = request.session.get('actor_name', 'Operator')
    
    AuditLog.objects.create(
        user_role=request.session.get('user_role', 'GATEWAY') if request.session.get('user_role') in ['OWNER', 'MANAGER', 'CASHIER'] else 'GATEWAY',
        actor_name=actor,
        action_type='LOGOUT',
        details=f"{actor} logged out",
        ip_address=get_client_ip(request)
    )
    
    if full_lock:
        request.session.flush()
        messages.info(request, "Terminal locked. General password required to re-open.")
        return redirect('inventory:general_login')
    else:
        # Clear only user role & branch; gateway remains active for fellow staff
        request.session['user_role'] = None
        request.session['branch_id'] = None
        request.session['actor_name'] = None
        messages.info(request, "Session closed. Return to Hub to switch branch or role.")
        return redirect('inventory:portal_hub')
