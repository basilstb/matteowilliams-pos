from functools import wraps
from django.shortcuts import redirect
from django.contrib import messages
from .models import Branch


def require_general_gateway(view_func):
    """Enforces Step 1: User must have entered the general gatekeeper password."""
    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        if not request.session.get('general_unlocked', False):
            messages.warning(request, "Please enter the general gateway password to access the Matteo Williams portal.")
            return redirect('inventory:general_login')
        return view_func(request, *args, **kwargs)
    return _wrapped


def require_roles(*allowed_roles):
    """Enforces role-based boundaries (OWNER, MANAGER, CASHIER)."""
    def decorator(view_func):
        @wraps(view_func)
        def _wrapped(request, *args, **kwargs):
            if not request.session.get('general_unlocked', False):
                return redirect('inventory:general_login')
            
            user_role = request.session.get('user_role')
            if not user_role or user_role not in allowed_roles:
                messages.error(request, f"Access Restricted: Your role ({user_role or 'Guest'}) does not have permission for this area.")
                if user_role == 'OWNER':
                    return redirect('inventory:owner_dashboard')
                elif user_role == 'MANAGER':
                    return redirect('inventory:branch_dashboard')
                elif user_role == 'CASHIER':
                    return redirect('inventory:pos_terminal')
                return redirect('inventory:portal_hub')
            return view_func(request, *args, **kwargs)
        return _wrapped
    return decorator


def require_branch(view_func):
    """Ensures a branch session is active (for Cashier or Manager)."""
    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        user_role = request.session.get('user_role')
        branch_id = request.session.get('branch_id')
        
        # Owner can view without specific branch session or select one
        if user_role == 'OWNER':
            return view_func(request, *args, **kwargs)
            
        if not branch_id:
            messages.warning(request, "Please authenticate into a branch terminal first.")
            return redirect('inventory:portal_hub')
            
        try:
            branch = Branch.objects.get(id=branch_id, is_active=True)
            if branch.is_currently_locked():
                messages.error(request, f"Terminal for {branch.name} is currently locked due to 3 failed PIN attempts.")
                return redirect('inventory:portal_hub')
        except Branch.DoesNotExist:
            messages.error(request, "Assigned branch not found.")
            return redirect('inventory:portal_hub')
            
        return view_func(request, *args, **kwargs)
    return _wrapped
