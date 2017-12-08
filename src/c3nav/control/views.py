from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import render


def control_panel_view(func):
    @wraps(func)
    def wrapped_func(self, request, *args, **kwargs):
        if not request.user_permissions.control_panel:
            raise PermissionDenied
        return func(self, request, *args, **kwargs)
    return login_required(login_url='site.login')(wrapped_func)


@control_panel_view
def main_index(request):
    return render(request, 'control/index.html', {})
