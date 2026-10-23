from functools import wraps

from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden


def role_required(*roles):
    """Restrict a view to signed-in users with one of the given roles."""
    def decorator(view_func):
        @wraps(view_func)
        def wrapped(request, *args, **kwargs):
            user = request.user
            allowed = user.is_authenticated and user.role in roles
            if "ADMIN" in roles and user.is_authenticated and user.is_superuser:
                allowed = True
            if not allowed:
                return HttpResponseForbidden("You are not authorized to access this page.")
            return view_func(request, *args, **kwargs)
        return login_required(wrapped)
    return decorator
