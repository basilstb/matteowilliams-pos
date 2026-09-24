from django.utils import timezone
from .models import SystemSettings, Branch


def global_context(request):
    """Context processor providing current session role, branch, and system settings."""
    settings = SystemSettings.get_settings()
    is_general_unlocked = request.session.get('general_unlocked', False)
    user_role = request.session.get('user_role', None)
    branch_id = request.session.get('branch_id', None)
    actor_name = request.session.get('actor_name', '')
    
    current_branch = None
    if branch_id:
        try:
            current_branch = Branch.objects.get(id=branch_id)
        except Branch.DoesNotExist:
            pass

    return {
        'system_settings': settings,
        'is_general_unlocked': is_general_unlocked,
        'user_role': user_role,
        'current_branch': current_branch,
        'actor_name': actor_name,
        'active_branches': Branch.objects.filter(is_active=True),
        'server_time': timezone.now(),
    }
